"""Email Logs API — Gönderim geçmişi (KVKK uyumlu, PII yok)"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.email_log import EmailLog
from app.deps import get_current_admin, get_db

router = APIRouter()


class LogOut(BaseModel):
    id: str
    draft_id: Optional[str]
    incoming_email_id: Optional[str] = None
    recipient_display: str       # Kurumsal adres — PII değil
    subject: str
    sent_at: datetime
    smtp_message_id: Optional[str]

    model_config = {"from_attributes": True}


@router.get("/emails", response_model=list[LogOut])
async def list_email_logs(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """E-posta gönderim geçmişi. body_anonymized ve recipient_email_hash gösterilmez."""
    q = (
        select(EmailLog)
        .where(EmailLog.deleted_at.is_(None))
        .order_by(EmailLog.sent_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if date_from:
        q = q.where(EmailLog.sent_at >= date_from)
    if date_to:
        q = q.where(EmailLog.sent_at <= date_to)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/emails/{log_id}", response_model=LogOut)
async def get_email_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    result = await db.execute(
        select(EmailLog).where(EmailLog.id == log_id, EmailLog.deleted_at.is_(None))
    )
    log = result.scalar_one_or_none()
    if not log:
        from fastapi import HTTPException
        raise HTTPException(404, "Log bulunamadı.")
    return log
