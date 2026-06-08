import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.session import get_db
from services.chat_service import process_message
from schemas.chat_schema import ChatRequest, ChatResponse

router = APIRouter()


# ─────────────────────
# 1. 채팅 메시지 전송
# ─────────────────────
@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def send_message(
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
    t_total = time.perf_counter()

    try:
        session, answer, timings = await process_message(
            db,
            req.session_id,
            req.message,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    print(
        f"[chat] LLM={timings['llm']}s "
        f"임베딩={timings['embedding']}s "
        f"DB={timings['db']}s "
        f"전체={round(time.perf_counter() - t_total, 2)}s"
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