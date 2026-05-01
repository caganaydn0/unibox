"""Incoming Emails API — Gelen e-posta yönetimi (admin)"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.deps import get_current_admin, get_db

router = APIRouter()


# ---- Pydantic Şemaları ----

class IncomingEmailOut(BaseModel):
    id: str
    sender_email_hash: str
    sender_name: Optional[str]
    subject: Optional[str]
    body_text: Optional[str]
    status: str
    intent_type: Optional[str]
    intent_confidence: Optional[float]
    rag_context_preview: Optional[str]
    rag_source_count: int
    reply_subject: Optional[str]
    reply_body: Optional[str]
    admin_notes: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    send_attempts: int
    last_error: Optional[str]
    has_attachments: bool
    attachment_names_json: str
    received_at: datetime
    fetched_at: datetime
    updated_at: datetime
    reply_sent_at: Optional[datetime]

    model_config = {"from_attributes": True}

    @field_serializer(
        "received_at", "fetched_at", "updated_at", "reviewed_at", "reply_sent_at"
    )
    def _tz_as_utc(self, dt: Optional[datetime]) -> Optional[str]:
        # DB'de naive UTC saklanıyor; istemcinin yerel saate düzgün çevirmesi için
        # ISO8601 çıktısına UTC tz bilgisi ekliyoruz.
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


class IncomingEmailUpdate(BaseModel):
    reply_subject: Optional[str] = None
    reply_body: Optional[str] = None
    admin_notes: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ---- Endpoint'ler ----

@router.get("/", response_model=list[IncomingEmailOut])
async def list_incoming(
    status: Optional[str] = Query(None),
    intent_type: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Gelen e-posta listesi. Status ve intent'e göre filtrele."""
    q = (
        select(IncomingEmail)
        .where(IncomingEmail.deleted_at.is_(None))
        .order_by(IncomingEmail.received_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status:
        try:
            q = q.where(IncomingEmail.status == IncomingEmailStatus(status))
        except ValueError:
            raise HTTPException(400, f"Geçersiz status: {status}")
    if intent_type:
        q = q.where(IncomingEmail.intent_type == intent_type)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{incoming_id}", response_model=IncomingEmailOut)
async def get_incoming(
    incoming_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    ie = await _get_or_404(db, incoming_id)
    return ie


@router.patch("/{incoming_id}", response_model=IncomingEmailOut)
async def update_incoming(
    incoming_id: str,
    body: IncomingEmailUpdate,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin yanıtı düzenler (PENDING_REVIEW durumunda)."""
    ie = await _get_or_404(db, incoming_id)
    if ie.status != IncomingEmailStatus.PENDING_REVIEW:
        raise HTTPException(400, "Sadece PENDING_REVIEW durumunda düzenlenebilir.")

    if body.reply_subject is not None:
        ie.reply_subject = body.reply_subject
    if body.reply_body is not None:
        ie.reply_body = body.reply_body
    if body.admin_notes is not None:
        ie.admin_notes = body.admin_notes

    await db.commit()
    await db.refresh(ie)
    return ie


@router.post("/{incoming_id}/approve")
async def approve_incoming(
    incoming_id: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin onayı — PENDING_REVIEW → APPROVED ve yanıt kuyruğuna ekle."""
    ie = await _get_or_404(db, incoming_id)
    if ie.status != IncomingEmailStatus.PENDING_REVIEW:
        raise HTTPException(
            400,
            f"Sadece PENDING_REVIEW onaylanabilir (mevcut: {ie.status}).",
        )

    ie.status = IncomingEmailStatus.APPROVED
    ie.reviewed_by = admin
    ie.reviewed_at = datetime.utcnow()
    await db.commit()

    from app.tasks.queue import incoming_reply_queue
    await incoming_reply_queue.put(ie.id)

    return {"detail": "Yanıt onaylandı, gönderim kuyruğuna eklendi.", "id": incoming_id}


@router.post("/{incoming_id}/skip")
async def skip_incoming(
    incoming_id: str,
    body: RejectRequest = None,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin bu e-postaya yanıt vermemeyi seçer."""
    ie = await _get_or_404(db, incoming_id)
    if ie.status != IncomingEmailStatus.PENDING_REVIEW:
        raise HTTPException(
            400,
            f"Sadece PENDING_REVIEW atlanabilir (mevcut: {ie.status}).",
        )

    ie.status = IncomingEmailStatus.SKIPPED
    ie.reviewed_by = admin
    ie.reviewed_at = datetime.utcnow()
    if body and body.reason:
        ie.admin_notes = body.reason
    await db.commit()

    return {"detail": "E-posta atlandı, yanıt gönderilmeyecek.", "id": incoming_id}


@router.post("/{incoming_id}/retry")
async def retry_incoming(
    incoming_id: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """FAILED yanıtı yeniden kuyruğa ekle."""
    ie = await _get_or_404(db, incoming_id)
    if ie.status != IncomingEmailStatus.FAILED:
        raise HTTPException(400, "Sadece FAILED durumundakiler yeniden denenebilir.")

    ie.status = IncomingEmailStatus.APPROVED
    ie.last_error = None
    await db.commit()

    from app.tasks.queue import incoming_reply_queue
    await incoming_reply_queue.put(ie.id)

    return {"detail": "Yanıt yeniden kuyruğa eklendi.", "id": incoming_id}


@router.post("/{incoming_id}/reanalyze")
async def reanalyze_incoming(
    incoming_id: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """ANALYSIS_FAILED / PENDING_REVIEW / SENT → RECEIVED, yeniden analiz et."""
    ie = await _get_or_404(db, incoming_id)
    allowed = {
        IncomingEmailStatus.ANALYSIS_FAILED,
        IncomingEmailStatus.PENDING_REVIEW,
        IncomingEmailStatus.REPLIED,
    }
    if ie.status not in allowed:
        raise HTTPException(400, f"Bu durumdan yeniden analiz yapılamaz: {ie.status}")

    ie.status = IncomingEmailStatus.RECEIVED
    ie.last_error = None
    await db.commit()

    from app.tasks.queue import incoming_analysis_queue
    await incoming_analysis_queue.put(ie.id)

    return {"detail": "E-posta yeniden analiz kuyruğuna eklendi.", "id": incoming_id}


# ---- Yardımcı ----

async def _get_or_404(db: AsyncSession, incoming_id: str) -> IncomingEmail:
    result = await db.execute(
        select(IncomingEmail).where(IncomingEmail.id == incoming_id)
    )
    ie = result.scalar_one_or_none()
    if not ie:
        raise HTTPException(404, "Gelen e-posta bulunamadı.")
    return ie
