from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Text, TIMESTAMP, func
from sqlalchemy.orm import relationship, Mapped, mapped_column

from db.base_class import Base


class Session(Base):
    __tablename__ = "sessions"

    session_id     : Mapped[int]                = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    summary        : Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    started_at     : Mapped[datetime]           = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    last_active_at : Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    # relationships
    messages : Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )