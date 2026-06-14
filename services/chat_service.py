import re, time

from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from core.config import settings
from core.constants.llm import THINKING_KEYWORDS, THINKING_LENGTH_THRESHOLD
from core.constants.tool import (
    FORCED_TOOL_KEYWORDS,
    CONFIRM_APPROVE_KEYWORDS,
    CONFIRM_DENY_KEYWORDS,
)
from core.logger import get_logger
from crud.chat_crud import (
    create_message,
    get_messages_by_session,
    get_or_create_session,
)
from models.session_model import Session as ChatSession
from services.agent.agent_service import stream_chat_with_tools, resume_tool_loop
from services.agent.pending_store import (
    store_pending,
    pop_pending,
    find_by_session,
)
from services.embedding_service import embed_text
from services.knowledge.wiki_service import search_wiki
from services.llm.text_utils import strip_markdown
from services.memory.profile_service import _build_profile_context
from services.memory.rag_service import _build_rag_context

logger = get_logger("chat_service")


# ─────────────────────────────────────
# 1. thinking 사용 여부 판단
# ─────────────────────────────────────
def _should_think(user_text: str) -> bool:
    """
    입력 텍스트와 모드 설정으로 thinking 활성화 여부를 결정한다.

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        thinking 활성화 여부
    """
    mode = settings.LLM_THINKING_MODE.lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    if len(user_text) >= THINKING_LENGTH_THRESHOLD:
        return True
    return any(kw in user_text.lower() for kw in THINKING_KEYWORDS)


# ─────────────────────────────────────────
# 2. 강제 도구 판단 (키워드 → 도구명 리스트)
# ─────────────────────────────────────────
def _resolve_forced_tools(user_text: str) -> list[str]:
    """
    입력의 키워드로 강제 호출할 도구들을 등장 순서대로 결정한다.

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        강제할 도구 이름 리스트 (등장 순서). 매칭 없으면 빈 리스트.
    """
    lowered = user_text.lower()
    hits: list[tuple[int, str]] = []
    for tool_name, keywords in FORCED_TOOL_KEYWORDS.items():
        positions = [lowered.find(kw) for kw in keywords if kw in lowered]
        if positions:
            hits.append((min(positions), tool_name))
    hits.sort(key=lambda x: x[0])
    return [tool_name for _pos, tool_name in hits]


# ──────────────────────────────────────────
# 3. 턴 준비 (세션·히스토리·컨텍스트 조립)
# ──────────────────────────────────────────
async def _prepare_turn(
    db: Session,
    session_id: int | None,
    user_text: str,
) -> tuple[ChatSession, list[dict], list[float], str | None, float]:
    """
    한 턴 처리에 필요한 공통 재료를 조립한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 클라이언트가 넘긴 세션 ID. None이면 새 세션 생성.
        user_text : 사용자 입력 텍스트
    Returns:
        (session, history, user_embedding, context, embed_sec)
    """
    # ──────────────────────────────────────
    # 3-1. 세션 판단 + 대화 히스토리 구성
    # ──────────────────────────────────────
    session = await run_in_threadpool(get_or_create_session, db, session_id)
    messages = await run_in_threadpool(
        get_messages_by_session, db, session.session_id, settings.HISTORY_LIMIT,
    )
    history = [{"role": msg.role, "content": msg.content} for msg in messages]
    history.append({"role": "user", "content": user_text})

    # ──────────────────────────────────────
    # 3-2. user 임베딩 + 프로필/위키/RAG 컨텍스트
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    user_embedding = await run_in_threadpool(embed_text, user_text)
    embed_sec = round(time.perf_counter() - t0, 2)

    rag_context = await run_in_threadpool(
        _build_rag_context, db, user_embedding, session.session_id
    )
    profile_context = await run_in_threadpool(
        _build_profile_context, db, user_text
    )
    wiki_context = await run_in_threadpool(search_wiki, user_text)

    context = (
        "\n\n".join(c for c in (profile_context, wiki_context, rag_context) if c)
        or None
    )
    return session, history, user_embedding, context, embed_sec


# ─────────────────────────────────────────
# 4. confirm 자동 해소 판정 (음성/텍스트 공통)
# ─────────────────────────────────────────
def _confirm_verdict(user_text: str) -> bool | None:
    """
    보류 중인 confirm을 입력의 긍정·부정으로 해소할지 판정한다.

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        True(승인) / False(거부) / None(판정 불가 → 정상 처리)
    """
    tokens = {
        re.sub(r"[^0-9a-z가-힣]", "", tok)
        for tok in user_text.strip().lower().split()
    }
    tokens.discard("")
    if tokens & CONFIRM_DENY_KEYWORDS:
        return False
    if tokens & CONFIRM_APPROVE_KEYWORDS:
        return True
    return None


# ─────────────────────────────────────────
# 5. 메시지 처리 (단일 스트리밍 파이프라인)
# ─────────────────────────────────────────
async def process_message_stream(
    db: Session,
    session_id: int | None,
    user_text: str,
):
    """
    단일 스트리밍 파이프라인 — 채팅·음성 모두 이 함수 하나를 거친다.

    턴 준비 → LLM 스트리밍(도구 포함) → 임베딩 → DB 저장까지 한 곳에서 처리.
    보류 중인 confirm이 있고 입력이 긍정/부정이면 새 턴 대신 재개한다.

    Yields:
        {"type": "token",  "text": str}                         — 답변 조각
        {"type": "status", "text": str, "speech": str}          — 도구 실행 상태
        {"type": "confirm_required", ...}                       — destructive 확인 요청
        {"type": "answer_complete", session_id, answer, user_text, timings} — 저장 완료
    """
    # ────────────────────────────────────────────────
    # 5-1. confirm 보류 자동 해소 (음성/텍스트 공통)
    # ────────────────────────────────────────────────
    if session_id is not None:
        found = find_by_session(session_id)
        if found:
            action_id, pending = found
            verdict = _confirm_verdict(user_text)
            if verdict is not None:
                pop_pending(action_id)
                logger.debug("confirm 자동 해소: approved=%s", verdict)
                async for ev in _resume_stream(db, pending, verdict):
                    yield ev
                return

    # ──────────────────────────────────────
    # 5-2. 공통 턴 준비
    # ──────────────────────────────────────
    session, history, user_embedding, context, embed_sec = await _prepare_turn(
        db, session_id, user_text
    )
    timings: dict = {"embedding": embed_sec}

    # ──────────────────────────────────────
    # 5-3. LLM 스트리밍 (도구 포함) → 공통 소비
    # ──────────────────────────────────────
    use_thinking = _should_think(user_text)
    forced_tools = _resolve_forced_tools(user_text)
    logger.debug(
        "thinking=%s forced_tools=%s | input_len=%d",
        "on" if use_thinking else "off",
        forced_tools,
        len(user_text),
    )

    gen = stream_chat_with_tools(history, use_thinking, context, forced_tools)
    async for ev in _consume_agent_stream(
        db, gen, session.session_id, user_text, user_embedding, timings
    ):
        yield ev


# ─────────────────────────────────────────
# 6. agent 스트림 소비 (최초/재개 공통)
# ─────────────────────────────────────────
async def _consume_agent_stream(
    db: Session,
    gen,
    session_id: int,
    user_text: str,
    user_embedding: list[float],
    timings: dict,
):
    """
    agent 제너레이터를 소비한다 — 토큰은 흘리고, confirm은 보류 저장 후 종료,
    완료되면 _finalize로 저장한다. 최초 턴과 confirm 재개 턴이 공유한다.

    Args:
        db            : SQLAlchemy 세션
        gen           : stream_chat_with_tools / resume_tool_loop 제너레이터
        session_id    : 세션 PK
        user_text     : 사용자 입력
        user_embedding: user 임베딩 (재계산 방지)
        timings       : 누적 타이밍 dict (embedding 키가 있을 수 있음)
    Yields:
        token / status / confirm_required / answer_complete
    """
    t0 = time.perf_counter()
    answer_parts: list[str] = []

    async for event in iterate_in_threadpool(gen):
        if event["type"] == "confirm_required":
            action_id = store_pending(
                session_id, user_text, user_embedding, event["_resume"]
            )
            yield {
                "type": "confirm_required",
                "action_id": action_id,
                "session_id": session_id,
                "tool": event["tool"],
                "args": event["args"],
                "preview": event["preview"],
            }
            return
        if event["type"] == "token":
            answer_parts.append(event["text"])
        yield event

    timings["llm"] = round(time.perf_counter() - t0, 2)
    yield await _finalize(
        db, session_id, user_text, user_embedding, answer_parts, timings
    )


# ─────────────────────────────────────────
# 7. 턴 마무리 (임베딩 + 저장 + answer_complete)
# ─────────────────────────────────────────
async def _finalize(
    db: Session,
    session_id: int,
    user_text: str,
    user_embedding: list[float],
    answer_parts: list[str],
    timings: dict,
) -> dict:
    """
    답변을 정리해 임베딩·저장하고 answer_complete 이벤트를 만든다.

    최초 턴과 confirm 재개 턴이 공유한다. user 메시지는 여기서 한 번에
    저장된다 (보류 중에는 저장하지 않으므로 찌꺼기가 없다).

    Args:
        db            : SQLAlchemy 세션
        session_id    : 세션 PK
        user_text     : 사용자 입력
        user_embedding: user 임베딩 (턴 준비 때 계산해 둔 값)
        answer_parts  : 스트리밍으로 모은 답변 조각
        timings       : 누적 타이밍 dict
    Returns:
        answer_complete 이벤트 dict
    """
    answer = strip_markdown("".join(answer_parts).strip())

    t0 = time.perf_counter()
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    timings["embedding"] = round(
        timings.get("embedding", 0) + (time.perf_counter() - t0), 2
    )

    t0 = time.perf_counter()
    await run_in_threadpool(
        create_message, db, session_id, "user", user_text, user_embedding
    )
    await run_in_threadpool(
        create_message, db, session_id, "assistant", answer, assistant_embedding
    )
    timings["db"] = round(time.perf_counter() - t0, 2)

    return {
        "type": "answer_complete",
        "session_id": session_id,
        "answer": answer,
        "user_text": user_text,
        "timings": timings,
    }


# ─────────────────────────────────────────
# 8. confirm 재개 스트림
# ─────────────────────────────────────────
async def _resume_stream(db: Session, pending: dict, approved: bool):
    """
    보류된 도구를 실행/취소하고 LLM 루프를 이어서 답변을 스트리밍한다.

    Args:
        db      : SQLAlchemy 세션
        pending : 보류 dict (session_id, user_text, user_embedding, resume)
        approved: 승인 여부
    Yields:
        token / status / confirm_required / answer_complete
    """
    gen = resume_tool_loop(pending["resume"], approved)
    async for ev in _consume_agent_stream(
        db,
        gen,
        pending["session_id"],
        pending["user_text"],
        pending["user_embedding"],
        {},
    ):
        yield ev


# ─────────────────────────────────────────
# 9. confirm 엔드포인트용 처리
# ─────────────────────────────────────────
async def process_confirm_stream(db: Session, action_id: str, approved: bool):
    """
    /chat/confirm 진입점 — action_id로 보류를 꺼내 재개 스트림을 위임한다.

    Args:
        db       : SQLAlchemy 세션
        action_id: 보류 식별자
        approved : 승인 여부
    Yields:
        _resume_stream과 동일한 이벤트
    Raises:
        RuntimeError: 보류가 없거나 만료된 경우
    """
    pending = pop_pending(action_id)
    if pending is None:
        raise RuntimeError("만료되었거나 존재하지 않는 확인 요청입니다.")
    async for ev in _resume_stream(db, pending, approved):
        yield ev