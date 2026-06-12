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
from services.tool.tool_service import TOOL_SPECS, execute_tool, announce_tool

logger = get_logger("agent_service")


# ─────────────────────────────────────
# 1. 도구 에이전트 루프 (블로킹, 음성용)
# ─────────────────────────────────────
def chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    context: str | None = None,
    force_search: bool = False,
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
        force_search: True 면 web_search 강제 지시를 주입
    Returns:
        thinking 블록이 제거된 최종 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    messages = _build_messages(history, context, use_thinking, force_search)

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 1-1. LLM 호출 (도구 스펙 포함)
        # ──────────────────────────────────────
        iter_thinking = use_thinking
        iter_tool_choice = (
            "required"
            if (force_search and iteration == 1)
            else "auto"
        )
        try:
            response = lm_client.chat.completions.create(
                messages=messages,
                tools=TOOL_SPECS,
                tool_choice=iter_tool_choice,
                **build_llm_kwargs(iter_thinking, answer_max),
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
        # 1-2. 도구 실행 → 결과를 대화에 추가 → 재호출
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
    # 1-3. 반복 초과 — 도구 없이 답변 강제
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
# 2. 도구 에이전트 루프 (스트리밍, SSE용)
# ─────────────────────────────────────
def stream_chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    context: str | None = None,
    force_search: bool = False,
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
        force_search: True 면 web_search 강제 지시를 주입
    Yields:
        이벤트 dict
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    answer_max = ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    messages = _build_messages(history, context, use_thinking, force_search)

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 2-1. 스트리밍 호출 (도구 스펙 포함)
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
                messages=messages,
                tools=TOOL_SPECS,
                tool_choice=iter_tool_choice,
                stream=True,
                **build_llm_kwargs(iter_thinking, answer_max),
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
        # 2-2. 토큰/도구호출 분리 수신
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
        # 2-3. 도구 실행 → 결과 추가 → 재호출
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
            status_text, speech_text = announce_tool(acc["name"], acc["arguments"])
            yield {"type": "status", "text": status_text, "speech": speech_text}
            result = execute_tool(acc["name"], acc["arguments"])
            messages.append({
                "role": "tool",
                "tool_call_id": acc["id"],
                "content": result,
            })

    # ──────────────────────────────────────
    # 2-4. 반복 초과 — 도구 없이 답변 강제 (스트리밍)
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