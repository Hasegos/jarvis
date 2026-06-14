import json, time
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
    requires_confirm,
    preview_tool,
    get_forced_tool_specs,
)
from services.tool.result import ok

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
    도구 호출을 처리하는 단일 스트리밍 파이프라인

    채팅·음성 모두 이 함수 하나를 거친다.

    Yields:
        {"type": "token",  "text": str}                 — 답변 텍스트 조각
        {"type": "status", "text": str, "speech": str}  — 도구 실행 상태
        {"type": "confirm_required", ...}               — destructive 도구 확인 요청
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    forced = list(forced_tools or [])
    messages = _build_messages(history, context, use_thinking, bool(forced))
    yield from _run_tool_loop(messages, set(), use_thinking, forced)


# ─────────────────────────────────────
# 4. 보류 작업 재개 (confirm 승인/거부 후)
# ─────────────────────────────────────
def resume_tool_loop(rs: dict, approved: bool) -> Iterator[dict]:
    """
    confirm 보류 상태(rs)에서 도구를 실행/취소하고 루프를 이어서 돈다.

    Args:
        rs      : 보류 상태 (messages, used_tools, use_thinking, forced, pending_tool)
        approved: True면 보류 도구 실행, False면 취소 결과 주입
    Yields:
        _run_tool_loop와 동일한 이벤트
    """
    pt = rs["pending_tool"]
    if approved:
        result = execute_tool(pt["name"], pt["arguments"])
    else:
        result = ok(cancelled=True, reason="사용자가 실행을 취소했습니다.")
    rs["used_tools"].add(pt["name"])
    rs["messages"].append({
        "role": "tool",
        "tool_call_id": pt["id"],
        "content": result,
    })
    yield from _run_tool_loop(
        rs["messages"], rs["used_tools"], rs["use_thinking"], rs["forced"]
    )


# ─────────────────────────────────────
# 5. 공통 도구 루프 (최초/재개 공유)
# ─────────────────────────────────────
def _run_tool_loop(
    messages: list[dict],
    used_tools: set,
    use_thinking: bool,
    forced: list[str],
) -> Iterator[dict]:
    """
    도구 호출 루프 본체 — 최초 진입과 재개가 공유한다.

    destructive 도구를 만나면 실행하지 않고 confirm_required를 yield한 뒤
    종료한다 (호출자가 보류 저장 → 이후 resume_tool_loop로 재개).

    Args:
        messages    : LLM 메시지 (재개 시 tool_call/결과까지 포함된 상태)
        used_tools  : 이미 실행된 도구 이름 집합
        use_thinking: thinking 모드
        forced      : 강제 도구 목록
    Yields:
        token / status / confirm_required 이벤트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    answer_max = (
        ANSWER_MAX_TOKENS_THINKING if use_thinking else ANSWER_MAX_TOKENS_SIMPLE
    )

    for iteration in range(1, TOOL_MAX_ITERATIONS + 1):
        # ──────────────────────────────────────
        # 5-1. LLM 스트리밍 호출
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
            logger.error("LLM 호출 오류: %s", e)
            raise RuntimeError("LLM 호출 중 오류가 발생했습니다.")

        # ──────────────────────────────────────────
        # 5-2. 토큰 / 도구호출 분리 수신 + 폭주 차단
        # ──────────────────────────────────────────
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        try:
            yield from _consume_llm_stream(stream, content_parts, tool_acc)
        except RuntimeError:
            raise
        except Exception as e:
            logger.error("LLM 스트리밍 오류: %s", e)
            raise RuntimeError("LLM 응답 처리 중 오류가 발생했습니다.")

        logger.debug(
            "스트림 %d회차: LLM=%.2fs tool_calls=%d",
            iteration,
            time.perf_counter() - t_llm,
            len(tool_acc),
        )

        # ──────────────────────────────────────
        # 5-3. 도구 호출 없으면 답변 완료
        # ──────────────────────────────────────
        if not tool_acc:
            return

        # ──────────────────────────────────────
        # 5-4. 도구 실행 → 결과 추가 → 재호출
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
                "tool": acc["name"],
                "text": status_text,
                "speech": speech_text,
            }

            # ──────────────────────────────────────────────
            # 5-4-1. confirm 게이트 — destructive는 일시정지
            # ──────────────────────────────────────────────
            try:
                args_obj = json.loads(acc["arguments"] or "{}")
            except json.JSONDecodeError:
                args_obj = {}

            if requires_confirm(acc["name"], args_obj):
                logger.debug("confirm 일시정지: %s", acc["name"])
                yield {
                    "type": "confirm_required",
                    "tool": acc["name"],
                    "args": args_obj,
                    "preview": preview_tool(acc["name"], acc["arguments"]),
                    "_resume": {
                        "messages": messages,
                        "used_tools": used_tools,
                        "use_thinking": use_thinking,
                        "forced": forced,
                        "pending_tool": {
                            "id": acc["id"],
                            "name": acc["name"],
                            "arguments": acc["arguments"],
                        },
                    },
                }
                return

            result = execute_tool(acc["name"], acc["arguments"])
            used_tools.add(acc["name"])
            messages.append({
                "role": "tool",
                "tool_call_id": acc["id"],
                "content": result,
            })

    # ──────────────────────────────────────
    # 5-5. 반복 초과 — 도구 없이 답변 강제
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
        logger.error("LLM 스트리밍 오류: %s", e)
        raise RuntimeError("LLM 응답 처리 중 오류가 발생했습니다.")


# ─────────────────────────────────────────────
# 6. LLM 스트림 소비 (토큰 yield + 도구호출 누적)
# ─────────────────────────────────────────────
def _consume_llm_stream(
    stream,
    content_parts: list[str],
    tool_acc: dict[int, dict],
) -> Iterator[dict]:
    """
    LLM 스트림을 읽어 텍스트 토큰을 yield하고, content_parts·tool_acc를
    제자리에서 채운다. 회차당 도구 상한(_MAX_TOOL_CALLS_PER_TURN)을 넘으면
    스트림을 끊는다 (B 가드).

    Args:
        stream       : lm_client 스트리밍 응답
        content_parts: 텍스트 누적 리스트 (in-place 갱신)
        tool_acc     : 도구 호출 누적 dict (in-place 갱신)
    Yields:
        {"type": "token", "text": str}
    """
    think_filter = _StreamThinkFilter()
    pending_ws = ""
    started = False

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta is None:
            continue

        # ── 도구 호출 수집 ──
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