import os, tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from faster_whisper import WhisperModel
from pydub import AudioSegment

from core.config import settings
from core.constant import STT_HALLUCINATION_PHRASES


# ─────────────────────────────────────
# 1. STT 모델 로드 (서버 시작 시 1회)
# ─────────────────────────────────────
try:
    _model = WhisperModel(
        settings.STT_MODEL_SIZE,
        device=settings.STT_DEVICE,
        compute_type=settings.STT_COMPUTE_TYPE,
        download_root=settings.STT_MODEL_DIR,
    )
except Exception as e:
    raise RuntimeError(f"STT 모델 로드 실패: {e}")

app = FastAPI(title="Jarvis STT Server")


# ─────────────────────
# 2. 헬스체크
# ─────────────────────
@app.get("/health")
def health():
    """STT 서버 정상 동작 확인."""
    return {"status": "ok"}


# ─────────────────────
# 3. 음성 인식
# ─────────────────────
@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    오디오 파일을 받아 텍스트로 변환한다.

    브라우저가 webm/opus로 보내므로 wav로 변환 후 STT.

    Args:
        file: 업로드된 오디오 파일 (webm, wav 등)
    Returns:
        {"text": "인식된 텍스트"}
    """
    tmp_input = None
    tmp_wav   = None

    try:
        # ──────────────────────────────────────
        # 3-1. 업로드 파일 임시 저장
        # ──────────────────────────────────────
        suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await file.read())
            tmp_input = f.name

        # ──────────────────────────────────────
        # 3-2. wav 변환 (faster-whisper 요구 — 16kHz mono)
        # ──────────────────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = f.name

        audio = AudioSegment.from_file(tmp_input)
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(tmp_wav, format="wav")

        # ──────────────────────────────────────
        # 3-3. STT 변환
        # ──────────────────────────────────────
        segments, _ = _model.transcribe(
            tmp_wav,
            language=settings.STT_LANGUAGE,
        )
        text = "".join(seg.text for seg in segments).strip()

        # 무음·노이즈 구간에서 Whisper가 만드는 유튜브 자막류 환청 차단
        if any(phrase in text for phrase in STT_HALLUCINATION_PHRASES):
            text = ""

        return {"text": text}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    finally:
        # ──────────────────────────────────────
        # 3-4. 임시 파일 정리
        # ──────────────────────────────────────
        for path in (tmp_input, tmp_wav):
            if path and os.path.exists(path):
                os.unlink(path)