from datetime import datetime
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


# ─────────────────────
# 2. 응답 스키마
# ─────────────────────
class ChatResponse(BaseModel):
    """
    채팅 메시지 응답 스키마.

    Args:
        session_id: 현재 대화 세션 ID.
        answer    : 어시스턴트 답변 텍스트.
    """
    session_id : int
    answer     : str
    audio_b64  : Optional[str] = None


# ─────────────────────
# 3. 세션 스키마
# ─────────────────────
class SessionOut(BaseModel):
    """
    세션 조회 응답 스키마.

    Args:
        session_id    : 세션 PK.
        started_at    : 세션 시작 시각.
        last_active_at: 마지막 활동 시각.
        summary       : compact 요약 (없으면 None).
    """
    session_id      : int
    started_at      : datetime
    last_active_at  : Optional[datetime] = None
    summary         : Optional[str] = None

    model_config = {"from_attributes" : True}