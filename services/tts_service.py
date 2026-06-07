import asyncio, os, re ,tempfile, edge_tts

from core.config import settings


# 마크다운 정제 패턴
_CODE_BLOCK_RE  = re.compile(r'```[\s\S]*?```')
_INLINE_CODE_RE = re.compile(r'`([^`]*)`')
_BOLD_ITALIC_RE = re.compile(r'\*{1,3}([^*]+)\*{1,3}|_{1,3}([^_]+)_{1,3}')
_HEADER_RE      = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_LIST_RE        = re.compile(r'^[\-\*\+]\s+|^\d+\.\s+', re.MULTILINE)
_LINK_RE        = re.compile(r'\[([^\]]+)\]\([^\)]+\)')
_SYMBOLS_RE     = re.compile(r'[`#*_>~\[\]|\\]')


# ─────────────────────────────────────
# 1. 마크다운 정제
# ─────────────────────────────────────
def _sanitize(text: str) -> str:
    """
    TTS 전송 전 마크다운·코드블록을 제거한다.

    코드블록은 대체 문구로 치환. 나머지 마크다운 기호는 삭제.

    Args:
        text: 원본 텍스트
    Returns:
        정제된 텍스트
    """
    text = _CODE_BLOCK_RE.sub('코드는 화면을 확인하세요.', text)
    text = _INLINE_CODE_RE.sub(r'\1', text)
    text = _BOLD_ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _HEADER_RE.sub('', text)
    text = _LIST_RE.sub('', text)
    text = _LINK_RE.sub(r'\1', text)
    text = _SYMBOLS_RE.sub('', text)
    return text.strip()


# ─────────────────────────────────────
# 2. 음성 합성
# ─────────────────────────────────────
async def synthesize(text: str) -> bytes:
    """
    텍스트를 Edge TTS로 합성해 mp3 바이트를 반환한다.

    브라우저로 직접 전송하므로 파일 대신 바이트로 반환.

    Args:
        text: 합성할 텍스트
    Returns:
        mp3 바이트
    Raises:
        RuntimeError: 빈 텍스트, 타임아웃, 합성 오류
    """
    text = _sanitize(text)
    if not text:
        raise RuntimeError("합성할 텍스트가 없습니다.")

    tmp_path = None
    try:
        # ──────────────────────────────────────
        # 2-1. 임시 파일에 합성 후 바이트로 읽기
        # ──────────────────────────────────────
        # edge_tts는 파일 저장 방식이라 임시 파일 경유 후 바이트 변환
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        communicate = edge_tts.Communicate(
            text,
            settings.TTS_VOICE,
            rate=settings.TTS_RATE,
        )
        await asyncio.wait_for(
            communicate.save(tmp_path),
            timeout=settings.TTS_TIMEOUT,
        )

        with open(tmp_path, "rb") as f:
            return f.read()

    except asyncio.TimeoutError:
        raise RuntimeError(
            f"TTS 타임아웃 ({settings.TTS_TIMEOUT}초 초과)."
        )
    except Exception as e:
        raise RuntimeError(f"TTS 합성 오류: {e}")
    finally:
        # ──────────────────────────────────────
        # 2-2. 임시 파일 정리
        # ──────────────────────────────────────
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)