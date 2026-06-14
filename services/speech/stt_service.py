import httpx

from core.config import settings
from core.logger import get_logger

logger = get_logger("speech.stt")


# ─────────────────────────────────────
# 1. STT 서버 호출
# ─────────────────────────────────────
async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """
    호스트 STT 서버에 오디오를 전송하고 인식된 텍스트를 반환한다.

    Docker 컨테이너 → host.docker.internal:8001 로 호출.

    Args:
        audio_bytes: 오디오 파일 바이트
        filename   : 파일명 (확장자로 포맷 판단)
    Returns:
        인식된 텍스트
    Raises:
        RuntimeError: STT 서버 연결 실패, 오류
    """
    try:
        async with httpx.AsyncClient(timeout=settings.STT_TIMEOUT) as client:
            response = await client.post(
                f"{settings.STT_SERVER_URL}/transcribe",
                files={"file": (filename, audio_bytes)},
            )
            response.raise_for_status()
            return response.json().get("text", "")

    except httpx.ConnectError:
        raise RuntimeError(
            "STT 서버에 연결할 수 없습니다. "
            "호스트에서 stt_server가 실행 중인지 확인하세요."
        )
    except httpx.TimeoutException:
        raise RuntimeError("STT 서버 응답 타임아웃.")
    except Exception as e:
        logger.error("STT 오류: %s", e)
        raise RuntimeError(f"STT 오류: {e}")