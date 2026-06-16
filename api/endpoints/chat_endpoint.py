import time, base64, json

from fastapi.responses import StreamingResponse
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    status,
    HTTPException
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.session import get_db
from schemas.chat_schema import ChatRequest, ConfirmRequest, LocationRequest
from models.session_model import Session as ChatSession
from crud.chat_crud import (
    get_all_messages_by_session,
    delete_session
)
from services.chat_service import process_message_stream, process_confirm_stream
from services.agent.location_store import update_location
from services.memory.background_service import run_summary_background
from services.memory.profile_service import _parse_memory_request
from services.speech.tts_service import synthesize


logger = get_logger("chat_endpoint")

router = APIRouter()


# ─────────────────────
# 1. SSE 직렬화
# ─────────────────────
def _sse(payload: dict) -> str:
    """이벤트 dict 를 SSE 한 줄(data: {...}\\n\\n)로 직렬화한다."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ─────────────────────
# 2. SSE 스트림 래퍼
# ─────────────────────
def _stream_sse(source, background_tasks: BackgroundTasks):
    """
    파이프라인 이벤트 소스를 SSE 응답으로 감싼다 (최초 전송·confirm 재개 공용).

    answer_complete 에서 TTS 합성 + 백그라운드 요약 등록 후 done 을 송출하고,
    그 외 이벤트(status/token/confirm_required)는 그대로 흘려보낸다.

    Args:
        source          : process_message_stream / process_confirm_stream 제너레이터
        background_tasks : 요약 백그라운드 등록용
    Returns:
        SSE 문자열을 yield 하는 async 제너레이터
    """
    async def event_stream():
        t_total = time.perf_counter()
        try:
            async for ev in source:
                # ─────────────────────────────────────────────────
                # 2-1. 답변 완성 — TTS + 백그라운드 등록 후 done 송출
                # ─────────────────────────────────────────────────
                if ev["type"] == "answer_complete":
                    immediate_profile, forced_section = _parse_memory_request(
                        ev.get("user_text", "")
                    )
                    background_tasks.add_task(
                        run_summary_background,
                        ev["session_id"],
                        immediate_profile,
                        forced_section,
                    )

                    t0 = time.perf_counter()
                    audio_b64 = None
                    try:
                        tts_bytes = await synthesize(ev["answer"])
                        audio_b64 = base64.b64encode(tts_bytes).decode("utf-8")
                    except RuntimeError as e:
                        logger.debug("TTS 생략: %s", e)

                    logger.info(
                        "TTS 완료: %.2fs초 (전체 %.2fs초)",
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
            logger.warning("스트림 처리 오류: %s", e)
            yield _sse({"type": "error", "message": "처리 중 오류가 발생했습니다."})

    return event_stream()


# ─────────────────────────────────────
# 3. 채팅 메시지 전송 (SSE 스트리밍)
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

    Args:
        req: 요청 바디 (session_id, message)
        db : SQLAlchemy 세션
    Returns:
        StreamingResponse (text/event-stream)
    """
    return StreamingResponse(
        _stream_sse(
            process_message_stream(db, req.session_id, req.message),
            background_tasks,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        background=background_tasks,
    )


# ───────────────────────────────────────────
# 4. destructive 도구 실행 확인 (SSE 스트리밍)
# ───────────────────────────────────────────
@router.post(
    "/confirm",
    status_code=status.HTTP_200_OK,
)
async def confirm_action(
    req: ConfirmRequest,
    background_tasks: BackgroundTasks,
    db : Session = Depends(get_db),
):
    """
    보류된 destructive 작업을 승인/취소하고, 이어지는 답변을 SSE 로 스트리밍한다.

    Args:
        req: 요청 바디 (action_id, approved)
        db : SQLAlchemy 세션
    Returns:
        StreamingResponse (text/event-stream)
    """
    return StreamingResponse(
        _stream_sse(
            process_confirm_stream(db, req.action_id, req.approved),
            background_tasks,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        background=background_tasks,
    )


# ─────────────────────────────────────
# 5. 세션 목록 조회
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
# 6. 세션 메시지 조회
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
# 7. 세션 삭제 (DB 영구 삭제)
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


# ─────────────────────────────────────
# 8. 현재 위치 갱신 (브라우저 GPS)
# ─────────────────────────────────────
@router.post(
    "/location",
    status_code=status.HTTP_200_OK,
)
def update_location_endpoint(req: LocationRequest):
    """
    브라우저가 보낸 GPS 좌표로 현재 위치를 갱신한다.

    Args:
        req: 요청 바디 (lat, lng)
    Returns:
        {"ok": True}
    """
    update_location(req.lat, req.lng)
    return {"ok": True}