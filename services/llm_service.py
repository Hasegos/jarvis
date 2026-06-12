import re, json, time
from collections.abc import Iterator

from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.constant import (
    SYSTEM_PROMPT,
    PROFILE_EXTRACT_PROMPT,
    PROFILE_SECTIONS,
    TOOL_MAX_ITERATIONS,
    ANSWER_MAX_TOKENS_SIMPLE,
    ANSWER_MAX_TOKENS_THINKING,
)
from core.logger import get_logger
from services.lm_client import lm_client
from services.tool_service import TOOL_SPECS, execute_tool

logger = get_logger("llm_service")

_MD_BOLD_RE     = re.compile(r'\*\*([^*\n]+)\*\*')
_MD_ITALIC_RE   = re.compile(r'\*([^*\n]+)\*|_([^_\n]+)_')
_MD_HEADER_RE   = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_LIST_RE     = re.compile(r'^[ \t]*[-*+]\s+', re.MULTILINE)
_MD_INLINE_RE   = re.compile(r'`([^`\n]+)`')


# ─────────────────────
# 1. thinking 블록 제거
# ─────────────────────
def strip_thinking(text: str) -> str:
    """
    <think>...</think> 블록을 제거한다.

    Args:
        text: LLM 원본 응답
    Returns:
        thinking 블록이 제거된 텍스트
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ─────────────────────────────────────
# 2. 마크다운 강조 기호 제거
# ─────────────────────────────────────
def strip_markdown(text: str) -> str:
    """
    LLM 응답에서 **bold**, ## 헤더 기호를 제거한다.

    코드 블록은 건드리지 않는다.

    Args:
        text: LLM 응답 텍스트
    Returns:
        마크다운 기호가 제거된 텍스트
    """
    text = _MD_BOLD_RE.sub(r'\1', text)
    text = _MD_ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _MD_HEADER_RE.sub('', text)
    text = _MD_LIST_RE.sub('', text)
    text = _MD_INLINE_RE.sub(r'\1', text)
    return text.strip()


# ─────────────────────────────────────
# 3. 메시지 빌드 (시스템 프롬프트 + RAG 주입)
# ─────────────────────────────────────
def _build_messages(
    history: list[dict],
    rag_context: str | None = None,
    use_thinking: bool = False,
    force_search: bool = False,
) -> list[dict]:
    """
    대화 히스토리 앞에 시스템 프롬프트를 prepend한다.

    RAG 컨텍스트가 있으면 시스템 프롬프트 뒤 별도 system 메시지로 주입한다.

    Args:
        history     : user/assistant 대화 히스토리
        rag_context : 과거 대화 참고 블록. None이면 주입 안 함.
        use_thinking: thinking 활성화 여부 (호환용 인자, 현재 메시지 구성엔 미반영).
        force_search: True 면 web_search 강제 지시를 맨 끝에 주입.
    Returns:
        시스템 프롬프트(+RAG, +강제검색 지시) 포함 메시지 리스트
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if rag_context:
        messages.append({"role": "system", "content": rag_context})
    messages = messages + history
    if force_search:
        messages.append({
            "role": "system",
            "content": (
                "사용자가 검색을 명시적으로 요청했습니다. "
                "과거 대화나 이전 답변에 비슷한 내용이 있더라도 신뢰하지 말고, "
                "반드시 web_search 도구를 먼저 호출해 최신 정보를 확인한 뒤 답하세요."
            ),
        })
    return messages


# ─────────────────────
# 4. 세션 한 단어 요약
# ─────────────────────
def generate_summary(history: list[dict]) -> str:
    """
    대화 내용을 주제를 나타내는 한 단어로 요약한다.

    thinking 없이 max_tokens=20으로 빠르게 호출한다.

    Args:
        history: user/assistant 대화 히스토리
    Returns:
        한 단어 요약. 실패 시 빈 문자열.
    """
    conversation = "\n".join(
        f"{m['role']}: {m['content']}" for m in history
    )
    prompt = (
        "/no_think\n"
        "다음 대화의 핵심 주제를 한국어 명사 한 단어로만 답해. "
        "예시: 코딩, 날씨, 요리, 역사\n"
        "단어 하나만 출력해. 문장 금지. 설명 금지.\n\n"
        f"{conversation}"
    )
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": "너는 대화 주제를 한 단어로 분류하는 분류기야."},
                {"role": "user",   "content": prompt},
            ],
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=0.1,
            max_tokens=20,
        )
        content = response.choices[0].message.content or ""
        word = strip_thinking(content).strip().split()[0] if content.strip() else ""
        return word
    except Exception as e:
        raise RuntimeError(f"요약 생성 오류: {e}")


# ─────────────────────────────────────
# 5. 기억 프로필 갱신 추출
# ─────────────────────────────────────
def extract_profile_updates(
        profile_text: str,
        conversation: str,
        forced_section: str | None = None
) -> list[dict]:
    """
    현재 프로필과 대화를 보고, 갱신할 섹션만 JSON 배열로 추출한다.

    thinking 없이 호출한다. 변경이 없거나 파싱 실패 시 빈 리스트를 반환해
    호출부가 안전하게 스킵하도록 한다.

    Args:
        profile_text: 현재 전체 프로필 텍스트 (섹션별 마크다운 합본)
        conversation: 최근 대화 텍스트
        forced_section: 지정 시 추출된 모든 사실을 이 섹션에 강제 저장. None이면 LLM 자동 분류.
    Returns:
        [{"section": str, "content": str}, ...]. 변경 없음/실패 시 [].
    """
    prompt = PROFILE_EXTRACT_PROMPT.format(
        sections=", ".join(PROFILE_SECTIONS),
        profile=profile_text or "(empty)",
        conversation=conversation,
        forced_section=forced_section or "(none)",
    )
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": "You extract durable user facts as strict JSON."},
                {"role": "user",   "content": "/no_think\n" + prompt},
            ],
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=0.1,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        raw = response.choices[0].message.content or ""
        raw = strip_thinking(raw).strip()

        # ──────────────────────────────────────
        # 5-1. JSON 파싱 (코드펜스/잡텍스트 방어)
        # ──────────────────────────────────────
        start = raw.find("[")
        end   = raw.rfind("]")
        if start == -1 or end == -1 or end < start:
            return []
        items = json.loads(raw[start : end + 1])

        # 형식 검증: 정해진 섹션 + 비어있지 않은 content 문자열만 통과
        result = []
        for it in items:
            if (
                isinstance(it, dict)
                and it.get("section") in PROFILE_SECTIONS
                and isinstance(it.get("content"), str)
                and it["content"].strip()
            ):
                result.append({"section": it["section"], "content": it["content"].strip()})
        return result
    except Exception:
        return []


# ─────────────────────────────────────
# 6. 도구 에이전트 루프
# ─────────────────────────────────────
def chat_with_tools(history: list[dict], use_thinking: bool = False, rag_context: str | None = None, force_search: bool = False) -> str:
    """
    도구(web_search 등)를 사용할 수 있는 블로킹 LLM 호출.

    모델이 tool_calls 를 내면 도구를 실행해 결과를 돌려주고 재호출한다.
    TOOL_MAX_ITERATIONS 초과 시 도구 없이 마지막 답변을 강제해 무한루프를 막는다.
    답변 토큰 상한은 복잡도(use_thinking)에 따라 다르게 적용한다.

    Args:
        history    : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        rag_context: 프로필/위키/RAG 참고 블록 (선택)
        force_search: True 면 web_search 강제 지시를 주입
    Returns:
        thinking 블록이 제거된 최종 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    messages = _build_messages(history, rag_context, use_thinking, force_search)

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 6-1. LLM 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        iter_thinking = use_thinking
        iter_tool_choice = (
            "required"
            if (force_search and iteration == 1)
            else "auto"
        )
        try:
            response = lm_client.chat.completions.create(
                model=settings.LM_STUDIO_MODEL,
                messages=messages,
                tools=TOOL_SPECS,
                tool_choice=iter_tool_choice,
                timeout=settings.LM_STUDIO_TIMEOUT,
                temperature=settings.LLM_TEMPERATURE,
                top_p=settings.LLM_TOP_P,
                max_tokens=answer_max,
                extra_body={
                    "chat_template_kwargs" : {"enable_thinking": iter_thinking},
                    "top_k"          : settings.LLM_TOP_K,
                    "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
                },
            )
        except APIConnectionError:
            raise RuntimeError(
                "LM Studio에 연결할 수 없습니다. LM Studio가 실행 중인지 확인하세요."
            )
        except APITimeoutError:
            raise RuntimeError(
                f"LM Studio 응답 타임아웃 ({settings.LM_STUDIO_TIMEOUT}초 초과)."
            )
        except Exception as e:
            raise RuntimeError(f"LLM 호출 오류: {e}")

        msg = response.choices[0].message

        # 도구 호출이 없으면 최종 답변
        if not msg.tool_calls:
            return strip_thinking(msg.content or "")

        # ──────────────────────────────────────
        # 6-2. 도구 실행 → 결과를 대화에 추가 → 재호출
        # ──────────────────────────────────────
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            result = execute_tool(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # ──────────────────────────────────────
    # 6-3. 반복 초과 — 도구 없이 답변 강제
    # ──────────────────────────────────────
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=messages,
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=answer_max,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking},
                "top_k"          : settings.LLM_TOP_K,
                "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
            },
        )
    except Exception as e:
        raise RuntimeError(f"LLM 호출 오류: {e}")

    return strip_thinking(response.choices[0].message.content or "")


# ─────────────────────────────────────
# 7. 스트리밍 도구 에이전트 루프 (SSE용)
# ─────────────────────────────────────
class _StreamThinkFilter:
    """
    스트리밍 토큰에서 <think>...</think> 구간을 걸러내는 상태 보존 필터.

    thinking ON 시 사고 과정이 사용자에게 노출되지 않도록, </think> 가
    나올 때까지 토큰을 버퍼에 보류한다. think 블록이 아니면 즉시 통과시킨다.
    """
    def __init__(self):
        self._done = False
        self._buf  = ""

    def feed(self, token: str) -> str:
        """토큰을 받아 출력 가능한 부분만 반환한다 (보류 중이면 빈 문자열)."""
        if self._done:
            return token
        self._buf += token
        stripped = self._buf.lstrip()
        if not stripped:
            return ""
        if not stripped.startswith("<"):
            self._done = True
            out, self._buf = self._buf, ""
            return out
        if not stripped.startswith("<think"):
            if len(stripped) >= 6:
                self._done = True
                out, self._buf = self._buf, ""
                return out
            return ""
        end = self._buf.find("</think>")
        if end == -1:
            return ""
        self._done = True
        out = self._buf[end + len("</think>"):]
        self._buf = ""
        return out.lstrip("\n")

    def flush(self) -> str:
        """
        스트림 종료 시 호출. 미완성 think 블록(</think> 미도래)에 갇혀
        출력이 비는 것을 방어한다. think 태그를 제거한 잔여 텍스트를 반환한다.
        """
        if self._done or not self._buf:
            return ""
        leftover = strip_thinking(self._buf).strip()
        self._buf = ""
        self._done = True
        return leftover


def _tool_status_texts(name: str, arguments_json: str) -> tuple[str, str]:
    """
    도구 호출을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    화면은 간결한 상태, 음성은 JARVIS가 말하듯 자연스러운 문장으로 만든다.

    Args:
        name          : 도구 이름
        arguments_json: LLM이 생성한 인자 JSON 문자열
    Returns:
        (status_text, speech_text)
    """
    if name == "web_search":
        query = ""
        try:
            query = json.loads(arguments_json or "{}").get("query", "")
        except json.JSONDecodeError:
            pass
        if query:
            return (f"검색 중: {query}", f"{query}, 검색해 보겠습니다.")
        return ("검색 중...", "검색해 보겠습니다.")
    return (f"{name} 실행 중...", "잠시만요, 확인해 보겠습니다.")


def stream_chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    rag_context: str | None = None,
    force_search: bool = False,
) -> Iterator[dict]:
    """
    도구 사용이 가능한 스트리밍 LLM 호출 (SSE용).

    이벤트 dict 를 순서대로 yield 한다:
        {"type": "token",  "text": str}  — 답변 텍스트 조각 (think 필터 적용됨)
        {"type": "status", "text": str}  — 도구 실행 상태 ("웹 검색 중: ...")
    최종 답변 텍스트는 호출부가 token 이벤트를 누적해 만든다.

    Args:
        history    : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        rag_context: 프로필/위키/RAG 참고 블록 (선택)
        force_search: True 면 web_search 강제 지시를 주입
    Yields:
        이벤트 dict
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    messages = _build_messages(history, rag_context, use_thinking, force_search)

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 7-1. 스트리밍 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        iter_thinking = use_thinking
        iter_tool_choice = (
            "required"
            if (force_search and iteration == 1)
            else "auto"
        )
        t_llm = time.perf_counter()
        try:
            stream = lm_client.chat.completions.create(
                model=settings.LM_STUDIO_MODEL,
                messages=messages,
                tools=TOOL_SPECS,
                tool_choice=iter_tool_choice,
                timeout=settings.LM_STUDIO_TIMEOUT,
                temperature=settings.LLM_TEMPERATURE,
                top_p=settings.LLM_TOP_P,
                max_tokens=answer_max,
                extra_body={
                    "chat_template_kwargs" : {"enable_thinking": iter_thinking},
                    "top_k"          : settings.LLM_TOP_K,
                    "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
                },
                stream=True,
            )
        except APIConnectionError:
            raise RuntimeError(
                "LM Studio에 연결할 수 없습니다. LM Studio가 실행 중인지 확인하세요."
            )
        except APITimeoutError:
            raise RuntimeError(
                f"LM Studio 응답 타임아웃 ({settings.LM_STUDIO_TIMEOUT}초 초과)."
            )
        except Exception as e:
            raise RuntimeError(f"LLM 호출 오류: {e}")

        # ──────────────────────────────────────
        # 7-2. 토큰/도구호출 분리 수신
        # ──────────────────────────────────────
        think_filter  = _StreamThinkFilter()
        pending_ws    = ""
        started       = False
        content_parts = []
        tool_acc: dict[int, dict] = {}

        try:
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        acc = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            acc["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                acc["name"] = tc.function.name
                            if tc.function.arguments:
                                acc["arguments"] += tc.function.arguments
                    continue

                token = delta.content or ""
                if not token:
                    continue
                content_parts.append(token)

                out = think_filter.feed(token)
                if not out:
                    continue
                if not started:
                    pending_ws += out
                    if pending_ws.strip():
                        started = True
                        yield {"type": "token", "text": pending_ws}
                        pending_ws = ""
                else:
                    yield {"type": "token", "text": out}

            tail = think_filter.flush()
            if tail:
                if not started:
                    started = True
                    yield {"type": "token", "text": (pending_ws + tail)}
                    pending_ws = ""
                else:
                    yield {"type": "token", "text": tail}
        except Exception as e:
            raise RuntimeError(f"LLM 스트리밍 오류: {e}")

        logger.debug(
            "스트림 %d회차: LLM=%.2fs tool_calls=%d",
            iteration, time.perf_counter() - t_llm, len(tool_acc),
        )

        if not tool_acc:
            return

        # ──────────────────────────────────────
        # 7-3. 도구 실행 → 결과 추가 → 재호출
        # ──────────────────────────────────────
        messages.append({
            "role": "assistant",
            "content": strip_thinking("".join(content_parts)),
            "tool_calls": [
                {
                    "id": acc["id"],
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]},
                }
                for acc in (tool_acc[i] for i in sorted(tool_acc))
            ],
        })
        for i in sorted(tool_acc):
            acc = tool_acc[i]
            status_text, speech_text = _tool_status_texts(acc["name"], acc["arguments"])
            yield {"type": "status", "text": status_text, "speech": speech_text}
            result = execute_tool(acc["name"], acc["arguments"])
            messages.append({
                "role": "tool",
                "tool_call_id": acc["id"],
                "content": result,
            })

    # ──────────────────────────────────────
    # 7-4. 반복 초과 — 도구 없이 답변 강제 (스트리밍)
    # ──────────────────────────────────────
    try:
        stream = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=messages,
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=answer_max,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking},
                "top_k"          : settings.LLM_TOP_K,
                "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
            },
            stream=True,
        )
        think_filter = _StreamThinkFilter()
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if not token:
                continue
            out = think_filter.feed(token)
            if out:
                yield {"type": "token", "text": out}
    except Exception as e:
        raise RuntimeError(f"LLM 스트리밍 오류: {e}")