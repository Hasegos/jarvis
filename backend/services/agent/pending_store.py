import time, uuid

from core.logger import get_logger

logger = get_logger("pending_store")

# ─────────────────────────────────────
# confirm 보류 저장소 (메모리)
# ─────────────────────────────────────
# destructive 도구 실행 전, 사용자 확인을 기다리는 보류 상태를 담는다.
_PENDING: dict[str, dict] = {}

# confirm 응답이 이 시간(초) 동안 안 오면 보류를 자동 폐기한다.
_PENDING_TTL_SEC = 300
_MAX_PENDING = 500


# ─────────────────────────────────────
# 1. 만료된 보류 청소
# ─────────────────────────────────────
def _evict_expired() -> None:
    """
    TTL을 초과한 보류 항목을 제거한다.

    별도 백그라운드 스케줄러 없이 store_pending 호출 시점마다
    자연스럽게 청소되는 lazy eviction 방식이다.
    """
    now = time.monotonic()
    expired = [
        aid for aid, p in _PENDING.items()
        if now - p["created_at"] > _PENDING_TTL_SEC
    ]
    for aid in expired:
        _PENDING.pop(aid, None)
        logger.debug("보류 만료 폐기: action_id=%s", aid)


# ─────────────────────────────────────
# 2. 보류 저장
# ─────────────────────────────────────
def store_pending(
    session_id: int,
    user_text: str,
    user_embedding: list[float],
    resume: dict,
) -> str:
    """
    보류 상태를 저장하고 action_id를 반환한다.

    한 세션에는 보류를 하나만 유지한다 — 새 보류 저장 시 기존 보류를 제거한다.
    호출 시점에 만료된 보류도 함께 청소한다.

    Args:
        session_id    : 세션 PK
        user_text     : 재개 완료 후 저장할 사용자 입력
        user_embedding: 재개 완료 후 저장할 user 임베딩 (재계산 방지)
        resume        : agent 루프 재개 상태
    Returns:
        새 action_id (hex)
    """
    _evict_expired()

    if len(_PENDING) >= _MAX_PENDING:
        oldest = min(_PENDING, key=lambda a: _PENDING[a]["created_at"])
        _PENDING.pop(oldest, None)

    for aid in [a for a, p in _PENDING.items() if p["session_id"] == session_id]:
        _PENDING.pop(aid, None)

    action_id = uuid.uuid4().hex
    _PENDING[action_id] = {
        "session_id": session_id,
        "user_text": user_text,
        "user_embedding": user_embedding,
        "resume": resume,
        "created_at": time.monotonic(),
    }
    logger.debug("보류 저장: action_id=%s session=%s", action_id, session_id)
    return action_id


# ─────────────────────────────────────
# 3. 보류 꺼내기 (제거)
# ─────────────────────────────────────
def pop_pending(action_id: str) -> dict | None:
    """
    action_id로 보류를 꺼내며 저장소에서 제거한다.

    TTL이 지난 보류는 존재하더라도 만료 처리하여 None을 반환한다.

    Args:
        action_id: 보류 식별자
    Returns:
        보류 dict. 없거나 만료됐으면 None.
    """
    p = _PENDING.pop(action_id, None)
    if p is None:
        return None
    if time.monotonic() - p["created_at"] > _PENDING_TTL_SEC:
        logger.debug("보류 만료(꺼내기 시점): action_id=%s", action_id)
        return None
    return p


# ─────────────────────────────────────
# 4. 세션으로 보류 조회 (음성 자동 해소용)
# ─────────────────────────────────────
def find_by_session(session_id: int) -> tuple[str, dict] | None:
    """
    세션에 걸린 보류를 조회한다 (제거하지 않음). 만료된 보류는 무시한다.

    Args:
        session_id: 세션 PK
    Returns:
        (action_id, 보류 dict). 없거나 만료됐으면 None.
    """
    now = time.monotonic()
    for aid, p in _PENDING.items():
        if p["session_id"] == session_id:
            if now - p["created_at"] > _PENDING_TTL_SEC:
                return None
            return aid, p
    return None