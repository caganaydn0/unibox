"""Incoming Email — Gelen öğrenci e-postası modeli

KVKK: sender_email Fernet ile şifrelenir, REPLIED/SKIPPED sonrası NULL'lanır.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IncomingEmailStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    REPLY_GENERATED = "REPLY_GENERATED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REPLIED = "REPLIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


VALID_INCOMING_TRANSITIONS: dict[IncomingEmailStatus, set[IncomingEmailStatus]] = {
    IncomingEmailStatus.RECEIVED: {IncomingEmailStatus.ANALYZING},
    IncomingEmailStatus.ANALYZING: {
        IncomingEmailStatus.REPLY_GENERATED,
        IncomingEmailStatus.ANALYSIS_FAILED,
    },
    IncomingEmailStatus.REPLY_GENERATED: {IncomingEmailStatus.PENDING_REVIEW},
    IncomingEmailStatus.PENDING_REVIEW: {
        IncomingEmailStatus.APPROVED,
        IncomingEmailStatus.SKIPPED,
    },
    IncomingEmailStatus.APPROVED: {
        IncomingEmailStatus.REPLIED,
        IncomingEmailStatus.FAILED,
    },
    IncomingEmailStatus.REPLIED: set(),       # terminal
    IncomingEmailStatus.FAILED: {IncomingEmailStatus.APPROVED},  # retry
    IncomingEmailStatus.SKIPPED: set(),       # terminal
    IncomingEmailStatus.ANALYSIS_FAILED: {IncomingEmailStatus.RECEIVED},  # retry
}


class IncomingEmail(Base):
    __tablename__ = "incoming_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )

    # IMAP tanımlayıcılar — dedup için
    message_id: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )
    imap_uid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Gönderen — KVKK: email Fernet ile şifrelenir
    sender_email_enc: Mapped[str] = mapped_column(Text, nullable=False)
    sender_email_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # E-posta içeriği
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attachment_names_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # İşleme durumu
    status: Mapped[IncomingEmailStatus] = mapped_column(
        SQLEnum(
            IncomingEmailStatus,
            name="incoming_email_status",
            native_enum=False,
            length=32,
        ),
        default=IncomingEmailStatus.RECEIVED,
        index=True,
        nullable=False,
    )

    # Intent tespiti
    intent_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    intent_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # RAG bağlamı (admin görünümü için kısaltılmış)
    rag_context_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rag_source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AI yanıtı
    reply_subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    reply_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Admin incelemesi
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Pilot Modu: insan incelemesi olmadan otomatik onaylandı mı (KVKK/denetim izi)
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Gönderim takibi
    send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    smtp_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Zaman damgaları
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # KVKK saklama süresi
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
