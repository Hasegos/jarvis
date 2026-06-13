import base64, time

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.session import get_db
from services.chat_service import process_message_stream
from services.memory.background_service import run_summary_background
from services.memory.profile_service import _parse_memory_request
from services.speech.stt_service import transcribe_audio
from services.speech.tts_service import synthesize

logger = get_logger("voice_endpoint")

router = APIRouter()


# ─────────────────────
# 1. 음성 대화
# ─────────────────────
@router.post(
    "",
    status_code=status.HTTP_200_OK,
)
async def voice_chat(
    background_tasks: BackgroundTasks,
    session_id: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    음성 파일을 받아 STT → LLM → TTS 파이프라인을 실행하고
    JSON(텍스트 + base64 오디오)을 반환한다.

    채팅과 동일한 스트리밍 파이프라인(process_message_stream)을
    내부에서 소비해, 폭주 차단 등 모든 보호가 동일하게 적용된다.

    Args:
        session_id: 기존 세션 ID. None이면 새 세션 자동 생성.
        file      : 브라우저 녹음 오디오 (webm/opus 등)
        db        : SQLAlchemy 세션
    Returns:
        JSONResponse (session_id, user_text, answer, audio_b64)
    """
    t_total = time.perf_counter()

    # ──────────────────────────────────────
    # 1-1. STT — 음성 → 텍스트
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    audio_bytes = await file.read()
    try:
        user_text = await transcribe_audio(audio_bytes, file.filename or "audio.webm")
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    logger.info("STT=%.2fs", round(time.perf_counter() - t0, 2))
    logger.info("STT 결과: %r", user_text)

    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="음성을 인식할 수 없습니다.",
        )

    # ───────────────────────────────────────────────
    # 1-2. 스트리밍 파이프라인 소비 (채팅과 동일한 경로)
    # ───────────────────────────────────────────────
    session_id_out = session_id
    answer = ""
    timings: dict = {}

    try:
        async for event in process_message_stream(db, session_id, user_text):
            if event["type"] == "answer_complete":
                session_id_out = event["session_id"]
                answer = event["answer"]
                timings = event["timings"]
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # ──────────────────────────────────────
    # 1-3. TTS — 텍스트 → 음성
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    audio_b64 = None
    try:
        tts_bytes = await synthesize(answer)
        audio_b64 = base64.b64encode(tts_bytes).decode("utf-8")
    except RuntimeError as e:
        logger.warning("TTS 오류 (무시): %s", e)
    logger.info(
        "TTS=%.2fs LLM=%.2fs 임베딩=%.2fs DB=%.2fs 전체=%.2fs",
        round(time.perf_counter() - t0, 2),
        timings.get("llm", 0),
        timings.get("embedding", 0),
        timings.get("db", 0),
        round(time.perf_counter() - t_total, 2),
    )

    # ──────────────────────────────────────
    # 1-4. 백그라운드 요약 갱신
    # ──────────────────────────────────────
    immediate_profile, forced_section = _parse_memory_request(user_text)
    background_tasks.add_task(
        run_summary_background,
        session_id_out,
        immediate_profile,
        forced_section,
    )

    # ──────────────────────────────────────
    # 1-5. JSON 반환
    # ──────────────────────────────────────
    return JSONResponse({
        "session_id": session_id_out,
        "user_text": user_text,
        "answer": answer,
        "audio_b64": audio_b64,
    })