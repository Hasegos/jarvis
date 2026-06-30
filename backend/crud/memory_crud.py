from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.memory_profile_model import MemoryProfile


# ─────────────────────────────────────
# 1. 전체 프로필 섹션 조회
# ─────────────────────────────────────
def get_all_sections(db: Session) -> list[MemoryProfile]:
    """
    모든 기억 프로필 섹션을 조회한다.

    Args:
        db: SQLAlchemy 세션
    Returns:
        MemoryProfile 객체 리스트 (섹션명 순)
    """
    return (
        db.query(MemoryProfile)
        .order_by(MemoryProfile.section.asc())
        .all()
    )


# ─────────────────────────────────────
# 2. 특정 섹션들 조회 (이름 목록)
# ─────────────────────────────────────
def get_sections_by_names(db: Session, names: list[str]) -> list[MemoryProfile]:
    """
    주어진 섹션명 목록에 해당하는 프로필만 조회한다.

    주입 시 '필수 섹션 + 키워드로 매칭된 섹션'만 골라 가져올 때 사용한다.

    Args:
        db   : SQLAlchemy 세션
        names: 조회할 섹션명 리스트 (예: ["Identity", "Schedule"])
    Returns:
        MemoryProfile 객체 리스트. 빈 names면 빈 리스트.
    """
    if not names:
        return []
    return (
        db.query(MemoryProfile)
        .filter(MemoryProfile.section.in_(names))
        .order_by(MemoryProfile.section.asc())
        .all()
    )


# ─────────────────────────────────────
# 3. 섹션 내용 갱신 (upsert)
# ─────────────────────────────────────
def upsert_section(db: Session, section: str, content: str) -> MemoryProfile:
    """
    섹션의 content를 갱신한다. 섹션이 없으면 새로 생성한다.

    PostgreSQL의 INSERT ... ON CONFLICT를 사용해 DB 레벨에서
    원자적으로 처리한다. ON CONFLICT는 DB가 행 잠금을 보장하므로
    이 레이스를 원천적으로 제거한다.

    Args:
        db     : SQLAlchemy 세션
        section: 섹션명 (예: "Identity")
        content: 새 마크다운 본문
    Returns:
        갱신/생성된 MemoryProfile 객체
    """
    stmt = pg_insert(MemoryProfile).values(
        section=section,
        content=content,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["section"],
        set_={"content": stmt.excluded.content},
    )
    db.execute(stmt)
    db.commit()

    return MemoryProfile(section=section, content=content)