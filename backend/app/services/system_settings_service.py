"""System Settings Service — Pilot/Co-Pilot çalışma modu okuma/yazma."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_settings import SystemMode, SystemSettings

SETTINGS_ROW_ID = 1


async def _get_or_create(session: AsyncSession) -> SystemSettings:
    result = await session.execute(
        select(SystemSettings).where(SystemSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = SystemSettings(id=SETTINGS_ROW_ID, system_mode=SystemMode.CO_PILOT)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def get_settings(session: AsyncSession) -> SystemSettings:
    return await _get_or_create(session)


async def get_mode(session: AsyncSession) -> SystemMode:
    row = await _get_or_create(session)
    return row.system_mode


async def set_mode(session: AsyncSession, mode: SystemMode, admin_username: str) -> SystemSettings:
    row = await _get_or_create(session)
    row.system_mode = mode
    row.updated_by = admin_username
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row
