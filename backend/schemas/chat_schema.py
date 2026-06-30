from typing import Optional
from pydantic import BaseModel, Field, field_validator


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
    message    : str = Field(..., max_length=10_000)
    image_b64  : Optional[str] = None

    @field_validator("image_b64")
    @classmethod
    def validate_image_b64(cls, v: str | None) -> str | None:
        if v is not None and len(v.encode()) > 2_000_000:
            raise ValueError("image_b64가 허용 크기(2MB)를 초과합니다.")
        return v


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
    text : str = Field(..., max_length=5_000)


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
    

# ────────────────────────────────────
# 5. 화면 스크린샷 분석 요청 스키마
# ────────────────────────────────────
class ScreenAnalysisRequest(BaseModel):
    """
    브라우저가 주기적으로 보내는 화면 스크린샷 분석 요청
    """
    image_b64  : str = Field(..., min_length=1)
    session_id : Optional[int] = None

    @field_validator("image_b64")
    @classmethod
    def validate_image_size(cls, v: str) -> str:
        if len(v.encode()) > 2_000_000:
            raise ValueError("image_b64가 허용 크기(2MB)를 초과합니다.")
        return v