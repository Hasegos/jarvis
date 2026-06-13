import time

from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from core.config import settings
from core.constants.llm import THINKING_KEYWORDS, THINKING_LENGTH_THRESHOLD
from core.constants.tool import FORCED_TOOL_KEYWORDS
from core.logger import get_logger
from crud.chat_crud import (
    create_message,
    get_messages_by_session,
    get_or_create_session,
)
from models.session_model import Session as ChatSession
from services.agent.agent_service import stream_chat_with_tools
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
# 4. 메시지 처리 (단일 스트리밍 파이프라인)
# ─────────────────────────────────────────
async def process_message_stream(
    db: Session,
    session_id: int | None,
    user_text: str,
):
    """
    단일 스트리밍 파이프라인 — 채팅·음성 모두 이 함수 하나를 거친다.

    턴 준비 → LLM 스트리밍(도구 포함) → 임베딩 → DB 저장까지 한 곳에서 처리.
    채팅은 토큰 이벤트를 SSE로 즉시 전달하고,
    음성은 answer_complete 이벤트에서 답변을 꺼내 TTS에 넘긴다.

    Yields:
        {"type": "token",  "text": str}                                — 답변 조각
        {"type": "status", "text": str, "speech": str}                 — 도구 실행 상태
        {"type": "answer_complete", "session_id", "answer", "timings"} — 저장 완료
    """
    timings: dict = {}

    # ──────────────────────────────────────
    # 4-1. 공통 턴 준비
    # ──────────────────────────────────────
    session, history, user_embedding, context, embed_sec = await _prepare_turn(
        db, session_id, user_text
    )
    timings["embedding"] = embed_sec

    # ──────────────────────────────────────
    # 4-2. LLM 스트리밍 (도구 포함)
    # ──────────────────────────────────────
    use_thinking = _should_think(user_text)
    forced_tools = _resolve_forced_tools(user_text)
    logger.debug(
        "thinking=%s forced_tools=%s | input_len=%d",
        "on" if use_thinking else "off",
        forced_tools,
        len(user_text),
    )

    t0 = time.perf_counter()
    answer_parts: list[str] = []
    gen = stream_chat_with_tools(history, use_thinking, context, forced_tools)
    async for event in iterate_in_threadpool(gen):
        if event["type"] == "token":
            answer_parts.append(event["text"])
        yield event

    answer = strip_markdown("".join(answer_parts).strip())
    timings["llm"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 4-3. assistant 임베딩 + DB 저장
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    timings["embedding"] = round(
        timings["embedding"] + (time.perf_counter() - t0), 2
    )

    t0 = time.perf_counter()
    await run_in_threadpool(
        create_message, db, session.session_id, "user", user_text, user_embedding
    )
    await run_in_threadpool(
        create_message, db, session.session_id, "assistant", answer, assistant_embedding
    )
    timings["db"] = round(time.perf_counter() - t0, 2)

    yield {
        "type": "answer_complete",
        "session_id": session.session_id,
        "answer": answer,
        "timings": timings,
    }