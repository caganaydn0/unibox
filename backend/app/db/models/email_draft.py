from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.conversation import Conversation
    from app.db.models.email_log import EmailLog
    from app.db.models.request_intent import RequestIntent


class EmailDraftStatus(str, enum.Enum):
    IDLE = "IDLE"
    COLLECTING_INFO = "COLLECTING_INFO"
    DRAFT_CREATED = "DRAFT_CREATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Geçerli durum geçişleri (state machine guard)
VALID_TRANSITIONS: dict[EmailDraftStatus, set[EmailDraftStatus]] = {
    EmailDraftStatus.IDLE: {EmailDraftStatus.COLLECTING_INFO},
    EmailDraftStatus.COLLECTING_INFO: {
        EmailDraftStatus.DRAFT_CREATED,
        EmailDraftStatus.CANCELLED,
    },
    EmailDraftStatus.DRAFT_CREATED: {
        EmailDraftStatus.PENDING_APPROVAL,
        EmailDraftStatus.CANCELLED,
    },
    EmailDraftStatus.PENDING_APPROVAL: {
        EmailDraftStatus.APPROVED,
        EmailDraftStatus.REJECTED,
        EmailDraftStatus.CANCELLED,
    },
    EmailDraftStatus.APPROVED: {
        EmailDraftStatus.SENT,
        EmailDraftStatus.FAILED,
    },
    EmailDraftStatus.REJECTED: set(),   # terminal
    EmailDraftStatus.SENT: set(),       # terminal
    EmailDraftStatus.FAILED: {EmailDraftStatus.APPROVED},  # retry
    EmailDraftStatus.CANCELLED: set(),  # terminal
}


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )

    status: Mapped[EmailDraftStatus] = mapped_column(
        SQLEnum(EmailDraftStatus, name="email_draft_status", native_enum=False, length=32),
        default=EmailDraftStatus.COLLECTING_INFO,
        index=True,
        nullable=False,
    )

    # Intent tipi: "transcript_request", "certificate_request" vb.
    intent_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # Alıcı bilgisi — kurumsal adres, öğrenci PII'sı değil
    recipient_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_department: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # KVKK: Öğrenciden toplanan alanlar Fernet ile şifrelenmiş JSON.
    # SENT veya REJECTED durumuna geçince NULL'lanır.
    collected_fields_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Admin aksiyonları
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Zaman damgaları
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # FAILED takibi
    send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # İlişkiler
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="email_drafts"
    )
    log: Mapped[Optional[EmailLog]] = relationship(
        "EmailLog", back_populates="draft", uselist=False
    )
    intent: Mapped[Optional[RequestIntent]] = relationship(
        "RequestIntent", back_populates="email_draft", uselist=False,
        foreign_keys="RequestIntent.email_draft_id",
    )
