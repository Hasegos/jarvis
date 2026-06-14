import uuid

from core.logger import get_logger

logger = get_logger("pending_store")

# ─────────────────────────────────────
# confirm 보류 저장소 (메모리)
# ─────────────────────────────────────
# destructive 도구 실행 전, 사용자 확인을 기다리는 보류 상태를 담는다.
_PENDING: dict[str, dict] = {}


# ─────────────────────────────────────
# 1. 보류 저장
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

    Args:
        session_id    : 세션 PK
        user_text     : 재개 완료 후 저장할 사용자 입력
        user_embedding: 재개 완료 후 저장할 user 임베딩 (재계산 방지)
        resume        : agent 루프 재개 상태
    Returns:
        새 action_id (hex)
    """
    for aid in [a for a, p in _PENDING.items() if p["session_id"] == session_id]:
        _PENDING.pop(aid, None)

    action_id = uuid.uuid4().hex
    _PENDING[action_id] = {
        "session_id": session_id,
        "user_text": user_text,
        "user_embedding": user_embedding,
        "resume": resume,
    }
    logger.debug("보류 저장: action_id=%s session=%s", action_id, session_id)
    return action_id


# ─────────────────────────────────────
# 2. 보류 꺼내기 (제거)
# ─────────────────────────────────────
def pop_pending(action_id: str) -> dict | None:
    """
    action_id로 보류를 꺼내며 저장소에서 제거한다.

    Args:
        action_id: 보류 식별자
    Returns:
        보류 dict. 없으면 None.
    """
    return _PENDING.pop(action_id, None)


# ─────────────────────────────────────
# 3. 세션으로 보류 조회 (음성 자동 해소용)
# ─────────────────────────────────────
def find_by_session(session_id: int) -> tuple[str, dict] | None:
    """
    세션에 걸린 보류를 조회한다 (제거하지 않음).

    Args:
        session_id: 세션 PK
    Returns:
        (action_id, 보류 dict). 없으면 None.
    """
    for aid, p in _PENDING.items():
        if p["session_id"] == session_id:
            return aid, p
    return None