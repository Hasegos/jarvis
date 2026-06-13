import time
from collections.abc import Iterator

from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.constants.llm import ANSWER_MAX_TOKENS_SIMPLE, ANSWER_MAX_TOKENS_THINKING
from core.constants.tool import TOOL_MAX_ITERATIONS
from core.logger import get_logger
from services.llm.lm_client import lm_client
from services.llm.llm_service import _build_messages, build_llm_kwargs
from services.llm.text_utils import strip_thinking, _StreamThinkFilter
from services.tool.tool_service import (
    TOOL_SPECS,
    execute_tool,
    announce_tool,
    get_forced_tool_specs,
)

logger = get_logger("agent_service")

# 액션 도구: 같은 의도를 여러 번 실행하면 안 되는 도구 (중복 저장·중복 실행 방지)
_DEDUP_TOOLS = frozenset({"vault_write"})


# ─────────────────────────────────────
# 1. 회차별 도구/선택 결정 (강제 가드)
# ─────────────────────────────────────
def _iter_tool_config(
    forced_tools: list[str],
    used_tools: set,
) -> tuple[list[dict], str]:
    """
    이번 회차에 LLM에 넘길 (도구 스펙, tool_choice)을 결정한다.

    forced_tools(등장 순서 강제 목록) 중 아직 실행되지 않은 첫 도구를 골라
    그 도구만 노출 + "required" 로 강제한다.

    Args:
        forced_tools: 등장 순서 강제 도구 목록 (비어 있을 수 있음)
        used_tools  : 지금까지 실행된 도구 이름 집합
    Returns:
        (tools, tool_choice)
    """
    # 강제 목록 중 아직 안 쓴 첫 도구 → 단일 노출 + required
    for name in forced_tools:
        if name not in used_tools:
            specs = get_forced_tool_specs(name)
            if specs:
                return specs, "required"
            break  # 알 수 없는 도구명이면 강제 포기하고 auto로

    # 강제 소진 → auto (중복방지 도구는 이미 썼으면 제외)
    blocked = used_tools & _DEDUP_TOOLS
    if blocked:
        tools = [s for s in TOOL_SPECS if s["function"]["name"] not in blocked]
    else:
        tools = TOOL_SPECS
    return tools, "auto"


# ─────────────────────────────────────
# 2. 중복 도구 호출 제거 (병렬 과잉 차단)
# ─────────────────────────────────────
def _dedup_tool_calls(calls: list, name_of) -> list:
    """
    한 회차에 들어온 도구 호출 중, 중복 방지 대상 도구(_DEDUP_TOOLS)는
    이름당 첫 호출만 남긴다.

    모델이 "메모해줘" 한 번에 vault_write 를 여러 번(내용을 쪼개) 부르는
    과잉 호출을 막는다.

    Args:
        calls  : 이번 회차의 도구 호출 목록 (블로킹: tool_call 객체 / 스트림: acc dict)
        name_of: 호출에서 도구 이름을 꺼내는 함수
    Returns:
        중복 제거된 호출 목록 (순서 유지)
    """
    seen = set()
    out  = []
    for c in calls:
        name = name_of(c)
        if name in _DEDUP_TOOLS:
            if name in seen:
                logger.debug("중복 도구 호출 무시: %s", name)
                continue
            seen.add(name)
        out.append(c)
    return out


# ─────────────────────────────────────
# 3. 도구 에이전트 루프 (블로킹, 음성용)
# ─────────────────────────────────────
def chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    context: str | None = None,
    forced_tools: list[str] | None = None,
) -> str:
    """
    도구(web_search 등)를 사용할 수 있는 블로킹 LLM 호출.

    모델이 tool_calls 를 내면 도구를 실행해 결과를 돌려주고 재호출한다.
    TOOL_MAX_ITERATIONS 초과 시 도구 없이 마지막 답변을 강제해 무한루프를 막는다.
    답변 토큰 상한은 복잡도(use_thinking)에 따라 다르게 적용한다.

    Args:
        history     : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        context     : 프로필/위키/RAG 참고 블록 (선택)
        forced_tools: 등장 순서 강제 도구 목록 (선택). 키워드 트리거로 결정됨.
    Returns:
        thinking 블록이 제거된 최종 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    forced = list(forced_tools or [])
    messages = _build_messages(history, context, use_thinking, bool(forced))
    used_tools: set = set()

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 3-1. LLM 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        iter_tools, iter_tool_choice = _iter_tool_config(forced, used_tools)
        try:
            response = lm_client.chat.completions.create(
                messages=messages,
                tools=iter_tools,
                tool_choice=iter_tool_choice,
                **build_llm_kwargs(use_thinking, answer_max),
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

        if not msg.tool_calls:
            return strip_thinking(msg.content or "")

        # ──────────────────────────────────────
        # 3-2. 도구 실행 → 결과를 대화에 추가 → 재호출
        # ──────────────────────────────────────
        tool_calls = _dedup_tool_calls(list(msg.tool_calls), lambda tc: tc.function.name)
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            result = execute_tool(tc.function.name, tc.function.arguments)
            used_tools.add(tc.function.name)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # ──────────────────────────────────────
    # 3-3. 반복 초과 — 도구 없이 답변 강제
    # ──────────────────────────────────────
    try:
        response = lm_client.chat.completions.create(
            messages=messages,
            **build_llm_kwargs(use_thinking, answer_max),
        )
    except Exception as e:
        raise RuntimeError(f"LLM 호출 오류: {e}")

    return strip_thinking(response.choices[0].message.content or "")


# ─────────────────────────────────────
# 4. 도구 에이전트 루프 (스트리밍, SSE용)
# ─────────────────────────────────────
def stream_chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    context: str | None = None,
    forced_tools: list[str] | None = None,
) -> Iterator[dict]:
    """
    도구 사용이 가능한 스트리밍 LLM 호출 (SSE용).

    이벤트 dict 를 순서대로 yield 한다:
        {"type": "token",  "text": str}  — 답변 텍스트 조각 (think 필터 적용됨)
        {"type": "status", "text": str}  — 도구 실행 상태 ("검색 중: ...")
    최종 답변 텍스트는 호출부가 token 이벤트를 누적해 만든다.

    Args:
        history     : user/assistant 대화 히스토리
        use_thinking: thinking 활성화 여부
        context     : 프로필/위키/RAG 참고 블록 (선택)
        forced_tools: 등장 순서 강제 도구 목록 (선택). 키워드 트리거로 결정됨.
    Yields:
        이벤트 dict
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    forced = list(forced_tools or [])
    messages = _build_messages(history, context, use_thinking, bool(forced))
    used_tools: set = set()

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 4-1. 스트리밍 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        iter_tools, iter_tool_choice = _iter_tool_config(forced, used_tools)
        t_llm = time.perf_counter()
        try:
            stream = lm_client.chat.completions.create(
                messages=messages,
                tools=iter_tools,
                tool_choice=iter_tool_choice,
                stream=True,
                **build_llm_kwargs(use_thinking, answer_max),
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
        # 4-2. 토큰/도구호출 분리 수신
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
        # 4-3. 도구 실행 → 결과 추가 → 재호출
        # ──────────────────────────────────────
        accs = _dedup_tool_calls(
            [tool_acc[i] for i in sorted(tool_acc)],
            lambda a: a["name"],
        )
        messages.append({
            "role": "assistant",
            "content": strip_thinking("".join(content_parts)),
            "tool_calls": [
                {
                    "id": acc["id"],
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]},
                }
                for acc in accs
            ],
        })
        for acc in accs:
            status_text, speech_text = announce_tool(acc["name"], acc["arguments"])
            yield {"type": "status", "text": status_text, "speech": speech_text}
            result = execute_tool(acc["name"], acc["arguments"])
            used_tools.add(acc["name"])
            messages.append({
                "role": "tool",
                "tool_call_id": acc["id"],
                "content": result,
            })

    # ──────────────────────────────────────
    # 4-4. 반복 초과 — 도구 없이 답변 강제 (스트리밍)
    # ──────────────────────────────────────
    try:
        stream = lm_client.chat.completions.create(
            messages=messages,
            stream=True,
            **build_llm_kwargs(use_thinking, answer_max),
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