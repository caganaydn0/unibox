from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.email_draft import EmailDraft
    from app.db.models.request_intent import RequestIntent


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # KVKK: session_token asla TCKN veya gerçek kimliğe bağlanmaz.
    # Tarayıcı tarafında üretilen rastgele UUID — hash'lenerek saklanır.
    session_token: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Anonim meta — gerçek kimlik bilgisi içermez
    department_hint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="tr", nullable=False)

    # KVKK: İçerik yazım anında anonymizer.py tarafından maskelenir.
    # Format: JSON array — [{"role": "user"|"assistant", "content": str, "ts": iso}]
    messages_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # Soft delete — KVKK silme hakkı için
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # started_at + CONVERSATION_RETENTION_DAYS (varsayılan 90 gün)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # İlişkiler
    email_drafts: Mapped[list[EmailDraft]] = relationship(
        "EmailDraft", back_populates="conversation", cascade="all, delete-orphan"
    )
    intents: Mapped[list[RequestIntent]] = relationship(
        "RequestIntent", back_populates="conversation", cascade="all, delete-orphan"
    )
