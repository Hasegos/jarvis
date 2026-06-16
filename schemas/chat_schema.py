from typing import Optional
from pydantic import BaseModel


# ─────────────────────
# 1. 요청 스키마
# ─────────────────────
class ChatRequest(BaseModel):
    """
    채팅 메시지 요청 스키마.

    Args:
        session_id: 기존 세션 ID. None이면 새 세션 자동 생성.
        message   : 사용자 입력 텍스트.
    """
    session_id : Optional[int] = None
    message    : str


# ───────────────────────
# 2. confirm 요청 스키마
# ───────────────────────
class ConfirmRequest(BaseModel):
    """
    destructive 도구 실행 확인 요청 스키마.

    Args:
        action_id: 보류된 작업 식별자 (confirm_required 이벤트로 받은 값).
        approved : True면 실행, False면 취소.
    """
    action_id : str
    approved  : bool


# ─────────────────────
# 3. TTS 요청 스키마
# ─────────────────────
class TtsRequest(BaseModel):
    """
    임의 텍스트 음성 합성 요청 스키마.

    Args:
        text: 합성할 텍스트.
    """
    text : str


# ─────────────────────
# 4. 위치 요청 스키마
# ─────────────────────
class LocationRequest(BaseModel):
    """
    브라우저 GPS 현재 위치 갱신 요청 스키마.

    Args:
        lat: 위도.
        lng: 경도.
    """
    lat : float
    lng : float