import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from crud.chat_crud import (
    create_message,
    get_messages_by_session,
    get_or_create_session,
)
from core.config import settings
from db.session import get_db
from services.embedding_service import embed_text
from services.llm_service import chat, stream_chat, strip_thinking
from services.stt_service import transcribe_audio
from services.tts_service import synthesize

router = APIRouter()


# ─────────────────────
# 1. 음성 대화
# ─────────────────────
@router.post(
    "",
    status_code=status.HTTP_200_OK,
)
async def voice_chat(
    session_id: int | None = None,
    file      : UploadFile  = File(...),
    db        : Session     = Depends(get_db),
):
    """
    음성 파일을 받아 STT → LLM → TTS 파이프라인을 실행하고
    JSON(텍스트 + base64 오디오)을 반환한다.

    Args:
        session_id: 기존 세션 ID. None이면 새 세션 자동 생성.
        file      : 브라우저 녹음 오디오 (webm/opus 등)
        db        : SQLAlchemy 세션
    Returns:
        JSONResponse (session_id, user_text, answer, audio_b64)
    """
    # ──────────────────────────────────────
    # 1-1. STT — 음성 → 텍스트
    # ──────────────────────────────────────
    audio_bytes = await file.read()
    try:
        user_text = await transcribe_audio(audio_bytes, file.filename or "audio.webm")
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="음성을 인식할 수 없습니다.",
        )

    # ──────────────────────────────────────
    # 1-2. 세션 판단
    # ──────────────────────────────────────
    session = get_or_create_session(db, session_id)

    # ──────────────────────────────────────
    # 1-3. 대화 히스토리 구성
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
    history.append({"role": "user", "content": user_text})

    # ──────────────────────────────────────
    # 1-4. LLM 호출
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
    # 1-5. 임베딩 생성
    # ──────────────────────────────────────
    try:
        user_embedding      = embed_text(user_text)
        assistant_embedding = embed_text(answer)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # ──────────────────────────────────────
    # 1-6. 메시지 저장
    # ──────────────────────────────────────
    create_message(db, session.session_id, "user",      user_text, user_embedding)
    create_message(db, session.session_id, "assistant", answer,    assistant_embedding)

    # ──────────────────────────────────────
    # 1-7. TTS — 텍스트 → 음성
    # ──────────────────────────────────────
    try:
        tts_bytes = await synthesize(answer)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # ──────────────────────────────────────
    # 1-8. JSON 반환 (오디오 base64 인코딩)
    # ──────────────────────────────────────
    # HTTP 헤더는 latin-1만 허용 → 한국어 텍스트는 헤더 불가
    # 오디오를 base64로 인코딩해서 JSON에 포함
    return JSONResponse({
        "session_id" : session.session_id,
        "user_text"  : user_text,
        "answer"     : answer,
        "audio_b64"  : base64.b64encode(tts_bytes).decode("utf-8"),
    })