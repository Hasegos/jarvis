import re, json
from collections.abc import Iterator

from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.constant import (
    SYSTEM_PROMPT,
    PROFILE_EXTRACT_PROMPT,
    PROFILE_SECTIONS,
    TOOL_MAX_ITERATIONS
)
from services.lm_client import lm_client
from services.tool_service import TOOL_SPECS, execute_tool

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
# 3. 문장 스트림 분할
# ─────────────────────────────────────
def sentence_stream(tokens: Iterator[str]) -> Iterator[str]:
    """
    토큰 스트림을 문장 단위로 분할한다.

    파편(3자 미만)은 다음 문장에 합쳐 TTS 낭비를 방지한다.

    Args:
        tokens: LLM 토큰 스트림
    Yields:
        문장 단위 텍스트
    """
    buffer  = ""
    pending = ""

    for token in tokens:
        buffer += token

        # ──────────────────────────────────────
        # 3-1. 문장 경계 감지 + 분할
        # ──────────────────────────────────────
        while True:
            m = re.search(r"[.!?。~]+\s+|\n+", buffer)
            if not m:
                break
            sentence = (pending + buffer[: m.end()]).strip()
            buffer   = buffer[m.end():]

            # 3자 미만 파편은 다음 문장에 합침 — 짧은 TTS 호출 방지
            if len(sentence) < 3:
                pending = sentence + " "
            else:
                pending = ""
                yield sentence

    # ──────────────────────────────────────
    # 3-2. 스트림 종료 후 잔여 버퍼 처리
    # ──────────────────────────────────────
    tail = (pending + buffer).strip()
    if tail:
        yield tail


# ─────────────────────────────────────
# 4. 메시지 빌드 (시스템 프롬프트 + RAG 주입)
# ─────────────────────────────────────
def _build_messages(history: list[dict], rag_context: str | None = None) -> list[dict]:
    """
    대화 히스토리 앞에 시스템 프롬프트를 prepend한다.

    RAG 컨텍스트가 있으면 시스템 프롬프트 뒤 별도 system 메시지로 주입한다.
    (현재 대화 히스토리와 구분되도록 분리 — 시간순 혼선 방지)

    Args:
        history    : user/assistant 대화 히스토리
        rag_context: 과거 대화 참고 블록. None이면 주입 안 함.
    Returns:
        시스템 프롬프트(+RAG) 포함 메시지 리스트
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if rag_context:
        messages.append({"role": "system", "content": rag_context})
    return messages + history


# ─────────────────────
# 5. 블로킹 호출
# ─────────────────────
def chat(history: list[dict], use_thinking: bool = False, rag_context: str | None = None) -> str:
    """
    블로킹 LLM 호출. 완성된 응답 텍스트를 반환한다.

    Args:
        history    : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        rag_context: 과거 대화 참고 블록 (선택)
    Returns:
        thinking 블록이 제거된 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=_build_messages(history, rag_context),
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=settings.LLM_MAX_TOKENS,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking },
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

    content = response.choices[0].message.content or ""
    return strip_thinking(content)


# ─────────────────────
# 6. 스트리밍 호출
# ─────────────────────
def stream_chat(history: list[dict], use_thinking: bool = False, rag_context: str | None = None) -> Iterator[str]:
    """
    스트리밍 LLM 호출. 토큰을 순서대로 yield한다.

    Args:
        history    : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        rag_context: 과거 대화 참고 블록 (선택)
    Yields:
        LLM 응답 토큰 (thinking 블록 포함 원문)
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    try:
        stream = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=_build_messages(history, rag_context),
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=settings.LLM_MAX_TOKENS,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking},
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
    # 6-1. 토큰 스트리밍
    # ──────────────────────────────────────
    try:
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token
    except Exception as e:
        raise RuntimeError(f"LLM 스트리밍 오류: {e}")


# ─────────────────────
# 7. 세션 한 단어 요약
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
# 8. 기억 프로필 갱신 추출
# ─────────────────────────────────────
def extract_profile_updates(profile_text: str, conversation: str) -> list[dict]:
    """
    현재 프로필과 대화를 보고, 갱신할 섹션만 JSON 배열로 추출한다.

    thinking 없이 호출한다. 변경이 없거나 파싱 실패 시 빈 리스트를 반환해
    호출부가 안전하게 스킵하도록 한다.

    Args:
        profile_text: 현재 전체 프로필 텍스트 (섹션별 마크다운 합본)
        conversation: 최근 대화 텍스트
    Returns:
        [{"section": str, "content": str}, ...]. 변경 없음/실패 시 [].
    """
    prompt = PROFILE_EXTRACT_PROMPT.format(
        sections=", ".join(PROFILE_SECTIONS),
        profile=profile_text or "(empty)",
        conversation=conversation,
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
        # 8-1. JSON 파싱 (코드펜스/잡텍스트 방어)
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
# 9. 도구 에이전트 루프
# ─────────────────────────────────────
def chat_with_tools(history: list[dict], use_thinking: bool = False, rag_context: str | None = None) -> str:
    """
    도구(web_search 등)를 사용할 수 있는 블로킹 LLM 호출.

    모델이 tool_calls 를 내면 도구를 실행해 결과를 돌려주고 재호출한다.
    TOOL_MAX_ITERATIONS 초과 시 도구 없이 마지막 답변을 강제해 무한루프를 막는다.

    Args:
        history    : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        rag_context: 프로필/위키/RAG 참고 블록 (선택)
    Returns:
        thinking 블록이 제거된 최종 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    messages = _build_messages(history, rag_context)

    for _ in range(TOOL_MAX_ITERATIONS):
        # ──────────────────────────────────────
        # 9-1. LLM 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        try:
            response = lm_client.chat.completions.create(
                model=settings.LM_STUDIO_MODEL,
                messages=messages,
                tools=TOOL_SPECS,
                timeout=settings.LM_STUDIO_TIMEOUT,
                temperature=settings.LLM_TEMPERATURE,
                top_p=settings.LLM_TOP_P,
                max_tokens=settings.LLM_MAX_TOKENS,
                extra_body={
                    "chat_template_kwargs" : {"enable_thinking": use_thinking},
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
        # 9-2. 도구 실행 → 결과를 대화에 추가 → 재호출
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
    # 9-3. 반복 초과 — 도구 없이 답변 강제
    # ──────────────────────────────────────
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=messages,
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=settings.LLM_MAX_TOKENS,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking},
                "top_k"          : settings.LLM_TOP_K,
                "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
            },
        )
    except Exception as e:
        raise RuntimeError(f"LLM 호출 오류: {e}")

    return strip_thinking(response.choices[0].message.content or "")