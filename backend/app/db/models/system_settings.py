"""System Settings — global çalışma modu (Pilot/Co-Pilot) anahtarı.

Tekil satır (singleton, id=1) olarak tutulur.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SQLEnum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemMode(str, enum.Enum):
    PILOT = "PILOT"
    CO_PILOT = "CO_PILOT"


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    system_mode: Mapped[SystemMode] = mapped_column(
        SQLEnum(
            SystemMode,
            name="system_mode",
            native_enum=False,
            length=16,
        ),
        default=SystemMode.CO_PILOT,
        nullable=False,
    )

    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
