from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.knowledge_document import KnowledgeDocument


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        # Komşu birleştirme ve belge sırasına dizme, chunk_index'in doküman
        # içinde tekil ve sıralı olmasına dayanıyor.
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # Yapısal meta veri — madde no, başlık, bölüm, parça bilgisi.
    # tags_json'dan AYRI tutuluyor: orası intent etiketleri için ve
    # rag_engine intent bonusunu oradan hesaplıyor.
    # Şekli için: app/services/chunking.py
    meta_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    # İlişki
    document: Mapped[KnowledgeDocument] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )
