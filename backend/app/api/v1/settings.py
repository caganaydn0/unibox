"""Settings API — Pilot/Co-Pilot çalışma modu (admin)"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ws_manager import ws_manager
from app.db.models.system_settings import SystemMode
from app.deps import get_current_admin, get_db
from app.services import system_settings_service

router = APIRouter()


class SystemModeOut(BaseModel):
    mode: SystemMode
    updated_by: Optional[str]
    updated_at: datetime

    @field_serializer("updated_at")
    def _tz_as_utc(self, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


class SystemModeUpdate(BaseModel):
    mode: SystemMode


@router.get("/system-mode", response_model=SystemModeOut)
async def get_system_mode(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    row = await system_settings_service.get_settings(db)
    return SystemModeOut(mode=row.system_mode, updated_by=row.updated_by, updated_at=row.updated_at)


@router.put("/system-mode", response_model=SystemModeOut)
async def set_system_mode(
    body: SystemModeUpdate,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    row = await system_settings_service.set_mode(db, body.mode, admin)

    await ws_manager.broadcast_to_admins({
        "type": "system_mode_changed",
        "mode": row.system_mode.value,
        "updated_by": row.updated_by,
    })

    return SystemModeOut(mode=row.system_mode, updated_by=row.updated_by, updated_at=row.updated_at)
