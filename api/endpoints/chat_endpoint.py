import time, base64

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from services.chat_service import process_message, run_summary_background
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.session import get_db
from schemas.chat_schema import ChatRequest, ChatResponse
from models.session_model import Session as ChatSession
from services.tts_service import synthesize
from crud.chat_crud import get_all_messages_by_session

logger = get_logger("chat_endpoint")

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
    background_tasks  : BackgroundTasks,
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

    # ──────────────────────────────────────
    # 1-1. 공통 파이프라인 (세션+LLM+임베딩+저장)
    # ──────────────────────────────────────
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
    
    t0 = time.perf_counter()
    audio_b64 = None
    try:
        tts_bytes = await synthesize(answer)
        audio_b64 = base64.b64encode(tts_bytes).decode("utf-8")
    except RuntimeError as e:
        logger.warning("TTS 오류 (무시): %s", e)
    tts_time = round(time.perf_counter() - t0, 2)

    logger.info(
        "LLM=%.2fs 임베딩=%.2fs DB=%.2fs TTS=%.2fs 전체=%.2fs",
        timings['llm'], timings['embedding'], timings['db'],
        tts_time, round(time.perf_counter() - t_total, 2),
    )

    # ──────────────────────────────────────
    # 1-3. 백그라운드 요약 갱신
    # ──────────────────────────────────────
    background_tasks.add_task(run_summary_background, session.session_id)

    return ChatResponse(
        session_id=session.session_id,
        answer=answer,
        audio_b64=audio_b64,
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


# ─────────────────────────────────────
# 3. 세션 메시지 조회
# ─────────────────────────────────────
@router.get(
    "/sessions/{session_id}/messages",
    status_code=status.HTTP_200_OK,
)
def get_session_messages(
    session_id: int,
    db        : Session = Depends(get_db),
):
    """
    세션의 전체 메시지를 시간순으로 반환한다.

    그래프 뷰에서 세션 선택 시 대화 내용 복원에 사용한다.

    Args:
        session_id: 조회할 세션 PK
        db        : SQLAlchemy 세션
    Returns:
        메시지 목록 (role, content, created_at)
    """
    messages = get_all_messages_by_session(db, session_id)
    return [
        {
            "role"      : m.role,
            "content"   : m.content,
            "created_at": m.created_at,
        }
        for m in messages
    ]