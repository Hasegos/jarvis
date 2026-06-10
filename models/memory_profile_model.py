from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base

class MemoryProfile(Base):
    __tablename__ = "memory_profiles"

    profile_id : Mapped[int]                = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    section    : Mapped[str]                = mapped_column(String(50), nullable=False, unique=True)
    content    : Mapped[str]                = mapped_column(Text, nullable=False, server_default="")
    updated_at : Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )