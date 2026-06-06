from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.session import get_db
from crud.chat_crud import (
    get_or_create_session,
    create_message,
    get_messages_by_session,
)
from services.llm_service import chat, stream_chat, strip_thinking
from services.embedding_service import embed_text
from schemas.chat_schema import ChatRequest, ChatResponse
from core.config import settings

router = APIRouter()


# ─────────────────────
# 1. 채팅 메시지 전송
# ─────────────────────
@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
def send_message(
    req: ChatRequest,
    db : Session = Depends(get_db),
):
    """
    사용자 메시지를 받아 LLM 답변을 생성하고 저장한다.

    session_id가 없거나 30분 이상 경과하면 새 세션을 자동 생성한다.

    Args:
        req: 요청 바디 (session_id, message)
        db : SQLAlchemy 세션
    Returns:
        ChatResponse (session_id, answer)
    """
    # ──────────────────────────────────────
    # 1-1. 세션 판단 (시간 기반 자동 분기)
    # ──────────────────────────────────────
    session = get_or_create_session(db, req.session_id)

    # ──────────────────────────────────────
    # 1-2. 대화 히스토리 구성
    # ──────────────────────────────────────
    messages = get_messages_by_session(
        db,
        session.session_id,
        limit=settings.HISTORY_LIMIT,
    )
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
    history.append({"role": "user", "content": req.message})

    # ──────────────────────────────────────
    # 1-3. LLM 호출
    # ──────────────────────────────────────
    try:
        if settings.LLM_STREAMING:
            tokens = stream_chat(history)
            answer = strip_thinking("".join(tokens))
        else:
            answer = chat(history)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # ──────────────────────────────────────
    # 1-4. 임베딩 생성
    # ──────────────────────────────────────
    try:
        user_embedding      = embed_text(req.message)
        assistant_embedding = embed_text(answer)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # ──────────────────────────────────────
    # 1-5. 메시지 저장
    # ──────────────────────────────────────
    create_message(
        db,
        session_id=session.session_id,
        role="user",
        content=req.message,
        embedding=user_embedding,
    )
    create_message(
        db,
        session_id=session.session_id,
        role="assistant",
        content=answer,
        embedding=assistant_embedding,
    )

    return ChatResponse(
        session_id=session.session_id,
        answer=answer,
    )


# ─────────────────────────────────────
# 2. 세션 목록 조회
# ─────────────────────────────────────
@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
)
def get_sessions(db: Session = Depends(get_db)):
    """
    전체 세션 목록을 최신순으로 반환한다.

    Args:
        db: SQLAlchemy 세션
    Returns:
        세션 목록 (session_id, started_at, last_active_at, summary)
    """
    from models.session_model import Session as ChatSession

    sessions = (
        db.query(ChatSession)
        .order_by(ChatSession.started_at.desc())
        .all()
    )
    return [
        {
            "session_id"    : s.session_id,
            "started_at"    : s.started_at,
            "last_active_at": s.last_active_at,
            "summary"       : s.summary,
        }
        for s in sessions
    ]