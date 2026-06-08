from datetime import datetime, timezone
from sqlalchemy.orm import Session

from models.session_model import Session as ChatSession
from models.message_model import Message


# ─────────────────────
# 1. 세션 생성
# ─────────────────────
def create_session(db: Session) -> ChatSession:
    """
    새 대화 세션을 생성한다.

    Args:
        db: SQLAlchemy 세션
    Returns:
        생성된 ChatSession 객체
    """
    session = ChatSession(started_at=datetime.now(timezone.utc))
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# ─────────────────────
# 2. 세션 조회
# ─────────────────────
def get_session_by_id(db: Session, session_id: int) -> ChatSession | None:
    """
    session_id로 세션을 조회한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 조회할 세션 PK
    Returns:
        ChatSession 객체. 없으면 None.
    """
    return db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()


# ─────────────────────────────────────
# 3. 세션 판단 (시간 기반 자동 분기)
# ─────────────────────────────────────
def get_or_create_session(db: Session, session_id: int | None) -> ChatSession:
    """
    세션 ID가 있으면 시간 기반으로 유효성 판단, 없으면 새 세션 생성.

    마지막 활동 후 SESSION_IDLE_MINUTES 이상 경과하면 새 세션으로 분기.
    — 음성 대화에서 "한참 후에 다시 말 걸면 새 대화"를 구현하는 핵심 로직.

    Args:
        db        : SQLAlchemy 세션
        session_id: 클라이언트가 넘긴 세션 ID. None이면 무조건 새 세션.
    Returns:
        유효한 ChatSession 객체
    """
    IDLE_MINUTES = 30

    if session_id is None:
        return create_session(db)

    session = get_session_by_id(db, session_id)
    if session is None:
        return create_session(db)

    # 마지막 활동 후 30분 이상 경과 시 새 세션
    if session.last_active_at is not None:
        now = datetime.now(timezone.utc)
        last = session.last_active_at
        # timezone-aware 비교
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds() / 60
        if elapsed >= IDLE_MINUTES:
            return create_session(db)

    return session


# ─────────────────────
# 4. 메시지 저장
# ─────────────────────
def create_message(
    db       : Session,
    session_id: int,
    role     : str,
    content  : str,
    embedding: list[float],
) -> Message:
    """
    메시지를 저장하고 세션 last_active_at을 갱신한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 메시지가 속할 세션 PK
        role      : 'user' 또는 'assistant'
        content   : 메시지 내용
        embedding : bge-m3 임베딩 벡터 (1024차원)
    Returns:
        저장된 Message 객체
    """
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        embedding=embedding,
    )
    db.add(message)

    # ──────────────────────────────────────
    # 4-1. 세션 last_active_at 갱신
    # ──────────────────────────────────────
    session = get_session_by_id(db, session_id)
    if session:
        session.last_active_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(message)
    return message


# ─────────────────────────────────────
# 5. 세션의 메시지 목록 조회
# ─────────────────────────────────────
def get_messages_by_session(
    db        : Session,
    session_id: int,
    limit     : int = 20,
) -> list[Message]:
    """
    세션의 최근 메시지를 시간순으로 조회한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 조회할 세션 PK
        limit     : 가져올 최대 메시지 수 (기본 HISTORY_LIMIT)
    Returns:
        Message 객체 리스트 (오래된 것부터)
    """
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


# ─────────────────────
# 6. 세션 요약 갱신
# ─────────────────────
def update_session_summary(
    db        : Session,
    session_id: int,
    summary   : str,
) -> None:
    """
    compact 요약 결과를 세션에 저장한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 갱신할 세션 PK
        summary   : LLM이 생성한 요약 텍스트
    """
    session = get_session_by_id(db, session_id)
    if session:
        session.summary = summary
        db.commit()