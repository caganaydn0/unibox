from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.document_chunk import DocumentChunk


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_base_documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # PDF dosyası DB'de BYTEA olarak saklanır
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 — duplikat tespiti ve bütünlük doğrulama
    sha256_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Chunk sayacı (denormalize — dashboard için)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[ProcessingStatus] = mapped_column(
        SQLEnum(ProcessingStatus, name="processing_status", native_enum=False, length=32),
        default=ProcessingStatus.PENDING,
        index=True,
        nullable=False,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Admin meta
    uploaded_by: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Arama / filtreleme meta
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON array: ["admissions", "transcripts", "2024"] — pgvector filtresi için
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # İlişki — chunk'lar
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
