import time, base64, json

from fastapi.responses import StreamingResponse  
from fastapi import APIRouter, BackgroundTasks, Depends, status, HTTPException
from services.chat_service import run_summary_background, process_message_stream
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.session import get_db
from schemas.chat_schema import ChatRequest
from models.session_model import Session as ChatSession
from services.tts_service import synthesize
from crud.chat_crud import get_all_messages_by_session, delete_session

logger = get_logger("chat_endpoint")

router = APIRouter()

def _sse(payload: dict) -> str:
    """이벤트 dict 를 SSE 한 줄(data: {...}\\n\\n)로 직렬화한다."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

# ─────────────────────────────────────
# 1. 채팅 메시지 전송 (SSE 스트리밍)
# ─────────────────────────────────────
@router.post(
    "/stream",
    status_code=status.HTTP_200_OK,
)
async def send_message_stream(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    db : Session = Depends(get_db),
):
    """
    사용자 메시지를 받아 답변을 SSE 로 스트리밍한다.

    이벤트(JSON): status(도구 상태) / token(답변 조각) /
    done(session_id, 최종 answer, audio_b64) / error(message).
    TTS 는 답변 완성 후 done 이벤트에 통짜로 싣는다.

    Args:
        req: 요청 바디 (session_id, message)
        db : SQLAlchemy 세션
    Returns:
        StreamingResponse (text/event-stream)
    """
    async def event_stream():
        t_total = time.perf_counter()
        try:
            async for ev in process_message_stream(db, req.session_id, req.message):
                # ──────────────────────────────────────────────
                # 답변 완성 — TTS + 백그라운드 등록 후 done 송출
                # ──────────────────────────────────────────────
                if ev["type"] == "answer_complete":
                    background_tasks.add_task(run_summary_background, ev["session_id"])

                    t0 = time.perf_counter()
                    audio_b64 = None
                    try:
                        tts_bytes = await synthesize(ev["answer"])
                        audio_b64 = base64.b64encode(tts_bytes).decode("utf-8")
                    except RuntimeError as e:
                        logger.warning("TTS 오류 (무시): %s", e)

                    logger.info(
                        "stream TTS=%.2fs 전체=%.2fs",
                        round(time.perf_counter() - t0, 2),
                        round(time.perf_counter() - t_total, 2),
                    )
                    yield _sse({
                        "type"      : "done",
                        "session_id": ev["session_id"],
                        "answer"    : ev["answer"],
                        "audio_b64" : audio_b64,
                    })
                else:
                    yield _sse(ev)
        except RuntimeError as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        background=background_tasks,
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
    전체 세션 목록을 최근 활동순으로 반환한다.

    Args:
        db: SQLAlchemy 세션
    Returns:
        세션 목록 (session_id, started_at, last_active_at, summary)
    """

    sessions = (
        db.query(ChatSession)
        .order_by(func.coalesce(ChatSession.last_active_at, ChatSession.started_at).desc())
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

# ─────────────────────────────────────
# 4. 세션 삭제 (DB 영구 삭제)
# ─────────────────────────────────────
@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
)
def delete_session_endpoint(
    session_id: int,
    db        : Session = Depends(get_db),
):
    """
    세션과 그에 속한 메시지/팩트를 영구 삭제한다 (하드 삭제, 복구 불가).

    Args:
        session_id: 삭제할 세션 PK
        db        : SQLAlchemy 세션
    Returns:
        {"deleted": True, "session_id": ...}. 대상이 없으면 404.
    """
    deleted = delete_session(db, session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다.",
        )
    return {"deleted": True, "session_id": session_id}