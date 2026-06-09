from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, String, TIMESTAMP,
    Boolean, ForeignKey, func, CheckConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from db.base_class import Base

class Fact(Base):
    __tablename__ = "facts"

    __table_args__ = (
        CheckConstraint("importance IN ('core', 'normal')", name="ck_facts_importance"),
        CheckConstraint("category IN ('preference', 'fact', 'project_status')", name="ck_facts_category"),
    )

    fact_id    : Mapped[int]                = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id : Mapped[int]                = mapped_column(BigInteger, ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False)
    content    : Mapped[str]                = mapped_column(String, nullable=False)
    importance : Mapped[Optional[str]]      = mapped_column(String(20), nullable=True)
    category   : Mapped[Optional[str]]      = mapped_column(String(20), nullable=True)
    embedding  : Mapped[list[float]]        = mapped_column(Vector(1024), nullable=False)
    is_active  : Mapped[Optional[bool]]     = mapped_column(Boolean, server_default="true")
    created_at : Mapped[datetime]           = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at : Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # relationships
    message : Mapped["Message"] = relationship(back_populates="facts")