from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, String, Text, TIMESTAMP,
    ForeignKey, func, CheckConstraint, Index
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from db.base_class import Base

class Message(Base):
    __tablename__ = "messages"

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),

        Index("ix_messages_session_id", "session_id"),

        # 임베딩 벡터 검색용 HNSW 인덱스 (코사인 거리)
        Index(
            "ix_messages_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    message_id : Mapped[int]                = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id : Mapped[int]                = mapped_column(BigInteger, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    role       : Mapped[str]                = mapped_column(String(20), nullable=False)
    content    : Mapped[str]                = mapped_column(Text, nullable=False)
    embedding  : Mapped[list[float]]        = mapped_column(Vector(1024), nullable=False)
    created_at : Mapped[datetime]           = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # relationships
    session : Mapped["Session"] = relationship(back_populates="messages")