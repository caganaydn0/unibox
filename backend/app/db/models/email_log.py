from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.email_draft import EmailDraft


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # Outgoing email draft (nullable — gelen email yanıtlarında None)
    draft_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    # Incoming email yanıtı (nullable — outgoing draft'larda None)
    incoming_email_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("incoming_emails.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # KVKK: Öğrenci kimliği bu tabloda ASLA bulunmaz.
    # recipient_email kurumsal adres olduğu için saklanabilir,
    # ama SHA-256 hash'i de denetim için ekliyoruz.
    recipient_email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_display: Mapped[str] = mapped_column(String(255), nullable=False)

    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    # body_anonymized: PII maskeleme uygulanmış içerik
    body_anonymized: Mapped[str] = mapped_column(Text, nullable=False)

    sent_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    smtp_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # KVKK veri saklama: sent_at + EMAIL_LOG_RETENTION_DAYS (varsayılan 180 gün)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # İlişkiler
    draft: Mapped[Optional[EmailDraft]] = relationship("EmailDraft", back_populates="log")
