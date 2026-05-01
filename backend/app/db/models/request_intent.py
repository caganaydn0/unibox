from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.conversation import Conversation
    from app.db.models.email_draft import EmailDraft


class RequestIntent(Base):
    __tablename__ = "request_intents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email_draft_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Intent taksonomisi
    # Örnekler: "transcript_request", "certificate_request",
    #           "enrollment_letter", "general_question", "complaint"
    intent_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    requires_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # LLM ham çıktısı — debug ve model iyileştirme için
    raw_classifier_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    detected_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    # İlişkiler
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="intents"
    )
    email_draft: Mapped[Optional[EmailDraft]] = relationship(
        "EmailDraft",
        back_populates="intent",
        foreign_keys=[email_draft_id],
    )
