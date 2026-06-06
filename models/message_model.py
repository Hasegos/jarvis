from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, String, Text, TIMESTAMP,
    ForeignKey, func, CheckConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from db.base_class import Base

class Message(Base):
    __tablename__ = "messages"

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )

    message_id : Mapped[int]                = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id : Mapped[int]                = mapped_column(BigInteger, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    role       : Mapped[str]                = mapped_column(String(20), nullable=False)
    content    : Mapped[str]                = mapped_column(Text, nullable=False)
    embedding  : Mapped[list[float]]        = mapped_column(Vector(1024), nullable=False)
    created_at : Mapped[datetime]           = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    # relationships
    session : Mapped["Session"] = relationship(back_populates="messages")
    facts   : Mapped[list["Fact"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )