import os, subprocess, tempfile, webbrowser
from pathlib import Path

import psutil
from fastapi import Body, FastAPI, File, HTTPException, UploadFile, status
from faster_whisper import WhisperModel
from pydub import AudioSegment

from core.config import settings
from core.constants.speech import (
    STT_HALLUCINATION_PHRASES, STT_INITIAL_PROMPT
)
from core.logger import get_logger

logger = get_logger("stt_server")


# ───────────────────────────────────────────
# 1. OS 조작 화이트리스트 (별칭 → 실행파일·라벨)
# ───────────────────────────────────────────
def _collect_allowed_apps() -> dict:
    """
    OS_APP_{별칭}={한글라벨}:{실행경로} 형태 환경변수를 모두 수집한다.

    Returns:
        {별칭: {"exe": 실행경로, "label": 한글라벨}}
    """
    raw: dict[str, str] = {}

    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            raw[k.strip()] = v.strip()

    for k, v in os.environ.items():
        if k.startswith("OS_APP_"):
            raw[k] = v

    apps: dict[str, dict] = {}
    for key, value in raw.items():
        if not key.startswith("OS_APP_") or ":" not in value:
            continue
        alias = key[len("OS_APP_"):].strip()
        if not alias:
            continue
        label, exe = value.split(":", 1)
        label = label.strip()
        exe = exe.strip().strip('"').strip("'")
        if not label or not exe:
            continue
        apps[alias] = {"exe": exe, "label": label}
    return apps


ALLOWED_APPS = _collect_allowed_apps()

_BYTES_PER_GB = 1024 ** 3


# ─────────────────────────────────────
# 2. STT 모델 로드 (서버 시작 시 1회)
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
# 3. 헬스체크
# ─────────────────────
@app.get("/health")
def health():
    """STT 서버 정상 동작 확인."""
    return {"status": "ok"}


# ─────────────────────
# 4. 음성 인식
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
        # 4-1. 업로드 파일 임시 저장
        # ──────────────────────────────────────
        suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await file.read())
            tmp_input = f.name

        # ──────────────────────────────────────
        # 4-2. wav 변환 (faster-whisper 요구 — 16kHz mono)
        # ──────────────────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = f.name

        audio = AudioSegment.from_file(tmp_input)
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(tmp_wav, format="wav")

        # ──────────────────────────────────────
        # 4-3. STT 변환
        # ──────────────────────────────────────
        segments, _ = _model.transcribe(
            tmp_wav,
            language=settings.STT_LANGUAGE,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=True,
            temperature=0.0,
            initial_prompt=STT_INITIAL_PROMPT,
        )
        text = "".join(seg.text for seg in segments).strip()

        # 무음·노이즈 구간에서 Whisper가 만드는 유튜브 자막류 환청 차단
        if any(phrase in text for phrase in STT_HALLUCINATION_PHRASES):
            text = ""

        return {"text": text}

    except Exception as e:
        logger.warning("STT 변환 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="음성 인식에 실패했습니다",
        )
    finally:
        # ──────────────────────────────────────
        # 4-4. 임시 파일 정리
        # ──────────────────────────────────────
        for path in (tmp_input, tmp_wav):
            if path and os.path.exists(path):
                os.unlink(path)


# ─────────────────────
# 5. 앱 실행 (OS 조작)
# ─────────────────────
@app.post("/action")
def action(payload: dict = Body(...)):
    """
    화이트리스트 안의 앱을 호스트에서 비차단 실행한다.

    도커 컨테이너의 os_control 도구가 호출한다.

    Args:
        payload: {"action": "launch", "target": "notepad"}
    Returns:
        {"ok": true, "pid": int, "label": str}
        또는 {"ok": false, "error": str} (+ 400)
    """
    action_name = (payload.get("action") or "").strip()
    target      = (payload.get("target") or "").strip()

    if action_name != "launch":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "error": "지원하지 않는 작업입니다"},
        )

    app_conf = ALLOWED_APPS.get(target)
    if app_conf is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "error": "허용되지 않은 앱입니다"},
        )

    try:
        # Popen으로 비차단 실행 — 자식 프로세스를 띄우고 즉시 반환한다.
        proc = subprocess.Popen(f'"{app_conf["exe"]}"', shell=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "error": "앱 실행에 실패했습니다"},
        )

    logger.info("앱 실행: %s (%s) pid=%s", target, app_conf["label"], proc.pid)
    return {"ok": True, "pid": proc.pid, "label": app_conf["label"]}


# ─────────────────────
# 6. 시스템 정보 조회
# ─────────────────────
@app.get("/system-info")
def system_info():
    """
    호스트의 CPU·메모리·디스크 사용 현황을 반환한다 (읽기 전용).

    Returns:
        {"cpu_percent": float,
        "memory": {"used_gb": float, "total_gb": float},
        "disk":   {"used_gb": float, "total_gb": float}}
    """
    try:
        # ─────────────────────
        # 6-1. CPU 사용률
        # ─────────────────────
        cpu_percent = psutil.cpu_percent(interval=0.5)

        # ──────────────────────────
        # 6-2. 메모리 사용량/총량 (GB)
        # ──────────────────────────
        mem = psutil.virtual_memory()
        memory = {
            "used_gb":  round(mem.used  / _BYTES_PER_GB, 1),
            "total_gb": round(mem.total / _BYTES_PER_GB, 1),
        }

        # ──────────────────────────
        # 5-3. 디스크 사용량/총량
        # ──────────────────────────
        usage = psutil.disk_usage("C:/")
        disk = {
            "used_gb":  round(usage.used  / _BYTES_PER_GB, 1),
            "total_gb": round(usage.total / _BYTES_PER_GB, 1),
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "error": "시스템 정보를 가져오지 못했습니다"},
        )

    return {"cpu_percent": cpu_percent, "memory": memory, "disk": disk}


# ─────────────────────
# 7. 브라우저 열기 (URL 열기)
# ─────────────────────
@app.post("/browse")
def browse(payload: dict = Body(...)):
    """
    전달받은 URL을 호스트의 기본 브라우저로 연다.

    Args:
        payload: {"url": "https://..."}
    Returns:
        {"ok": true, "url": str}
        또는 {"ok": false, "error": str} (+ 400)
    """
    url = (payload.get("url") or "").strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "error": "허용되지 않은 URL입니다"},
        )

    try:
        webbrowser.open(url)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "error": "페이지를 열지 못했습니다"},
        )

    logger.info("브라우저 열기: %s", url)
    return {"ok": True, "url": url}