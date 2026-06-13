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


# ─────────────────────────────────────
# 상수 — 도구 호출 가드
# ─────────────────────────────────────
_MAX_TOOL_CALLS_PER_TURN = 1

# 한 회차에 같은 도구를 부를 수 있는 최대 횟수 (후처리 보조).
_MAX_CALLS_PER_TOOL = {
    "vault_write": 1,
    "web_search": 1,
}
_DEFAULT_MAX_CALLS = 1

# 1회 실행 후 이후 회차 후보에서 제외할 도구.
_DEDUP_TOOLS = frozenset({"vault_write", "web_search"})


# ─────────────────────────────────────
# 1. 회차별 도구/선택 결정
# ─────────────────────────────────────
def _iter_tool_config(
    forced_tools: list[str],
    used_tools: set,
) -> tuple[list[dict], str]:
    """
    이번 회차에 LLM에 넘길 (도구 스펙, tool_choice)을 결정한다.

    Args:
        forced_tools: 등장 순서 강제 도구 목록
        used_tools  : 지금까지 실행된 도구 이름 집합
    Returns:
        (tools, tool_choice)
    """
    for name in forced_tools:
        if name not in used_tools:
            specs = get_forced_tool_specs(name)
            if specs:
                return specs, "required"
            break

    blocked = used_tools & _DEDUP_TOOLS
    if blocked:
        tools = [s for s in TOOL_SPECS if s["function"]["name"] not in blocked]
    else:
        tools = TOOL_SPECS
    return tools, "auto"


# ─────────────────────────────────────
# 2. 도구 호출 상한 제한 (후처리 보조)
# ─────────────────────────────────────
def _dedup_tool_calls(calls: list, name_of) -> list:
    """
    한 회차에 들어온 도구 호출을 도구별 횟수 상한으로 제한한다.

    Args:
        calls  : 도구 호출 목록 (acc dict)
        name_of: 호출에서 도구 이름을 꺼내는 함수
    Returns:
        상한 적용된 호출 목록 (순서 유지)
    """
    counts: dict[str, int] = {}
    out = []
    for c in calls:
        name = name_of(c)
        limit = _MAX_CALLS_PER_TOOL.get(name, _DEFAULT_MAX_CALLS)
        n = counts.get(name, 0)
        if n >= limit:
            logger.debug("도구 호출 상한 초과 무시: %s (상한 %d)", name, limit)
            continue
        counts[name] = n + 1
        out.append(c)
    return out


# ─────────────────────────────────────
# 3. 도구 스트리밍 루프 (단일 파이프라인)
# ─────────────────────────────────────
def stream_chat_with_tools(
    history: list[dict],
    use_thinking: bool = False,
    context: str | None = None,
    forced_tools: list[str] | None = None,
) -> Iterator[dict]:
    """
    도구 호출을 처리하는 단일 스트리밍 파이프라인.

    채팅·음성 모두 이 함수 하나를 거친다.
    항상 stream=True 로 LLM을 호출해, 도구 폭주 시 생성 도중에
    스트림을 끊는다 — 양쪽 경로 동일 보호.

    Yields:
        {"type": "token",  "text": str}                 — 답변 텍스트 조각
        {"type": "status", "text": str, "speech": str}  — 도구 실행 상태
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    forced = list(forced_tools or [])
    answer_max = (
        ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    )
    messages = _build_messages(history, context, use_thinking, bool(forced))
    used_tools: set = set()

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 3-1. LLM 스트리밍 호출
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
                "LM Studio에 연결할 수 없습니다. "
                "LM Studio가 실행 중인지 확인하세요."
            )
        except APITimeoutError:
            raise RuntimeError(
                f"LM Studio 응답 타임아웃 "
                f"({settings.LM_STUDIO_TIMEOUT}초 초과)."
            )
        except Exception as e:
            raise RuntimeError(f"LLM 호출 오류: {e}")

        # ──────────────────────────────────────
        # 3-2. 토큰 / 도구호출 분리 수신 + 폭주 차단
        # ──────────────────────────────────────
        think_filter = _StreamThinkFilter()
        pending_ws = ""
        started = False
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}

        try:
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                # ── 도구 호출 수집 + B 가드 ──
                if delta.tool_calls:
                    overflow = False
                    for tc in delta.tool_calls:
                        if (
                            tc.index not in tool_acc
                            and len(tool_acc) >= _MAX_TOOL_CALLS_PER_TURN
                        ):
                            overflow = True
                            break
                        acc = tool_acc.setdefault(
                            tc.index,
                            {"id": "", "name": "", "arguments": ""},
                        )
                        if tc.id:
                            acc["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                acc["name"] = tc.function.name
                            if tc.function.arguments:
                                acc["arguments"] += tc.function.arguments
                    if overflow:
                        logger.debug(
                            "폭주 차단: 회차당 도구 상한 %d 초과, 스트림 중단",
                            _MAX_TOOL_CALLS_PER_TURN,
                        )
                        break
                    continue

                # ── 텍스트 토큰 수신 ──
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
                    yield {"type": "token", "text": pending_ws + tail}
                else:
                    yield {"type": "token", "text": tail}
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"LLM 스트리밍 오류: {e}")

        logger.debug(
            "스트림 %d회차: LLM=%.2fs tool_calls=%d",
            iteration,
            time.perf_counter() - t_llm,
            len(tool_acc),
        )

        # ──────────────────────────────────────
        # 3-3. 도구 호출 없으면 답변 완료
        # ──────────────────────────────────────
        if not tool_acc:
            return

        # ──────────────────────────────────────
        # 3-4. 도구 실행 → 결과 추가 → 재호출
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
                    "function": {
                        "name": acc["name"],
                        "arguments": acc["arguments"],
                    },
                }
                for acc in accs
            ],
        })
        for acc in accs:
            status_text, speech_text = announce_tool(
                acc["name"], acc["arguments"]
            )
            yield {
                "type": "status",
                "text": status_text,
                "speech": speech_text,
            }
            result = execute_tool(acc["name"], acc["arguments"])
            used_tools.add(acc["name"])
            messages.append({
                "role": "tool",
                "tool_call_id": acc["id"],
                "content": result,
            })

    # ──────────────────────────────────────
    # 3-5. 반복 초과 — 도구 없이 답변 강제
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