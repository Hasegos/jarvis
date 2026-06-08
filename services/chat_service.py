import time

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from core.config import settings
from crud.chat_crud import (
    create_message,
    get_messages_by_session,
    get_or_create_session,
)
from models.session_model import Session as ChatSession
from services.embedding_service import embed_text
from services.llm_service import chat, stream_chat, strip_thinking


# ─────────────────────────────────────
# 1. 메시지 처리 (공통 파이프라인)
# ─────────────────────────────────────
async def process_message(
    db        : Session,
    session_id: int | None,
    user_text : str,
) -> tuple[ChatSession, str, dict]:
    """
    텍스트 입력을 받아 세션 판단 → LLM → 임베딩 → DB 저장까지 처리한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 클라이언트가 넘긴 세션 ID
        user_text : STT 또는 텍스트 입력
    Returns:
        (session, answer, timings)
        - session: 현재 세션 객체
        - answer : LLM 답변 텍스트
        - timings: 단계별 소요 시간 딕셔너리
    Raises:
        RuntimeError: LLM 또는 임베딩 오류
    """
    timings = {}

    # ──────────────────────────────────────
    # 1-1. 세션 판단
    # ──────────────────────────────────────
    session = await run_in_threadpool(get_or_create_session, db, session_id)

    # ──────────────────────────────────────
    # 1-2. 대화 히스토리 구성
    # ──────────────────────────────────────
    messages = await run_in_threadpool(
        get_messages_by_session,
        db,
        session.session_id,
        settings.HISTORY_LIMIT,
    )
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
    history.append({"role": "user", "content": user_text})

    # ──────────────────────────────────────
    # 1-3. LLM 호출
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    if settings.LLM_STREAMING:
        tokens = await run_in_threadpool(lambda: list(stream_chat(history)))
        answer = strip_thinking("".join(tokens))
    else:
        answer = await run_in_threadpool(chat, history)
    timings["llm"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 1-4. 임베딩 생성
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    user_embedding      = await run_in_threadpool(embed_text, user_text)
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    timings["embedding"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 1-5. 메시지 저장
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    await run_in_threadpool(
        create_message, db, session.session_id, "user", user_text, user_embedding
    )
    await run_in_threadpool(
        create_message, db, session.session_id, "assistant", answer, assistant_embedding
    )
    timings["db"] = round(time.perf_counter() - t0, 2)

    return session, answer, timings