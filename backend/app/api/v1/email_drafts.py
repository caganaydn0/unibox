"""Email Drafts API — CRUD + approve/reject/retry"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.email_draft import EmailDraft, EmailDraftStatus
from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.deps import get_current_admin, get_db
from app.services.email_workflow import approve_draft, reject_draft

router = APIRouter()


class DraftOut(BaseModel):
    id: str
    conversation_id: str
    status: str
    intent_type: str
    recipient_email: Optional[str]
    recipient_name: Optional[str]
    recipient_department: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    admin_notes: Optional[str]
    rejection_reason: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    send_attempts: int
    last_error: Optional[str]

    model_config = {"from_attributes": True}


class DraftUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    recipient_email: Optional[str] = None
    recipient_name: Optional[str] = None
    admin_notes: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str


# ---- Unified (Draft + IncomingReply) ----

class UnifiedEmailItem(BaseModel):
    id: str
    item_type: str          # "draft" | "incoming_reply"
    status: str             # normalized display status
    subject: Optional[str]
    recipient_display: Optional[str]   # draft → recipient_email
    sender_display: Optional[str]      # incoming_reply → sender_name / hash
    intent_type: Optional[str]
    created_at: datetime
    send_attempts: int
    last_error: Optional[str]

    model_config = {"from_attributes": True}


# Unified filtre → draft statüsü eşlemesi
_DRAFT_FILTER: dict[str, EmailDraftStatus] = {
    "PENDING_APPROVAL": EmailDraftStatus.PENDING_APPROVAL,
    "APPROVED":         EmailDraftStatus.APPROVED,
    "SENT":             EmailDraftStatus.SENT,
    "REJECTED":         EmailDraftStatus.REJECTED,
    "FAILED":           EmailDraftStatus.FAILED,
}

# Unified filtre → incoming statüsü eşlemesi
_INCOMING_FILTER: dict[str, IncomingEmailStatus] = {
    "PENDING_APPROVAL": IncomingEmailStatus.PENDING_REVIEW,
    "APPROVED":         IncomingEmailStatus.APPROVED,
    "SENT":             IncomingEmailStatus.REPLIED,
    "REJECTED":         IncomingEmailStatus.SKIPPED,
    "FAILED":           IncomingEmailStatus.FAILED,
}

# Incoming statüsü → display statüsü
_INCOMING_DISPLAY: dict[str, str] = {
    "PENDING_REVIEW": "PENDING_APPROVAL",
    "REPLIED":        "SENT",
    "SKIPPED":        "REJECTED",
}


@router.get("/unified", response_model=list[UnifiedEmailItem])
async def list_unified(
    status: Optional[str] = Query(None),
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """EmailDraft + IncomingEmail yanıtlarını birleşik döndür."""
    items: list[UnifiedEmailItem] = []

    # --- EmailDraft ---
    if not status or status in _DRAFT_FILTER:
        dq = select(EmailDraft).order_by(EmailDraft.created_at.desc()).limit(limit)
        if status:
            dq = dq.where(EmailDraft.status == _DRAFT_FILTER[status])
        for d in (await db.execute(dq)).scalars().all():
            items.append(UnifiedEmailItem(
                id=d.id,
                item_type="draft",
                status=d.status.value,
                subject=d.subject,
                recipient_display=d.recipient_email,
                sender_display=None,
                intent_type=d.intent_type,
                created_at=d.created_at,
                send_attempts=d.send_attempts,
                last_error=d.last_error,
            ))

    # --- IncomingEmail ---
    if not status or status in _INCOMING_FILTER:
        iq = (
            select(IncomingEmail)
            .where(IncomingEmail.deleted_at.is_(None))
            .order_by(IncomingEmail.received_at.desc())
            .limit(limit)
        )
        if status:
            iq = iq.where(IncomingEmail.status == _INCOMING_FILTER[status])
        else:
            # Tümü: sadece onay akışına giren statüsleri göster
            iq = iq.where(IncomingEmail.status.in_([
                IncomingEmailStatus.PENDING_REVIEW,
                IncomingEmailStatus.APPROVED,
                IncomingEmailStatus.REPLIED,
                IncomingEmailStatus.SKIPPED,
                IncomingEmailStatus.FAILED,
            ]))
        for ie in (await db.execute(iq)).scalars().all():
            display_status = _INCOMING_DISPLAY.get(ie.status.value, ie.status.value)
            items.append(UnifiedEmailItem(
                id=ie.id,
                item_type="incoming_reply",
                status=display_status,
                subject=ie.reply_subject or ie.subject,
                recipient_display=None,
                sender_display=ie.sender_name or f"#{ie.sender_email_hash[:8]}",
                intent_type=ie.intent_type,
                created_at=ie.received_at,
                send_attempts=ie.send_attempts,
                last_error=ie.last_error,
            ))

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items[:limit]


@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(
    status: Optional[str] = Query(None),
    intent_type: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """E-posta taslakları listesi. Status ve intent'e göre filtrele."""
    q = select(EmailDraft).order_by(EmailDraft.created_at.desc()).offset(skip).limit(limit)
    if status:
        try:
            q = q.where(EmailDraft.status == EmailDraftStatus(status))
        except ValueError:
            raise HTTPException(400, f"Geçersiz status: {status}")
    if intent_type:
        q = q.where(EmailDraft.intent_type == intent_type)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    draft = await _get_draft_or_404(db, draft_id)
    return draft


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
async def update_draft(
    draft_id: str,
    body: DraftUpdate,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin taslak içeriğini düzenler (PENDING_APPROVAL veya DRAFT_CREATED)."""
    draft = await _get_draft_or_404(db, draft_id)
    editable = {EmailDraftStatus.PENDING_APPROVAL, EmailDraftStatus.DRAFT_CREATED}
    if draft.status not in editable:
        raise HTTPException(400, "Bu durumda taslak düzenlenemez.")

    if body.subject is not None:
        draft.subject = body.subject
    if body.body is not None:
        draft.body = body.body
    if body.recipient_email is not None:
        draft.recipient_email = body.recipient_email
    if body.recipient_name is not None:
        draft.recipient_name = body.recipient_name
    if body.admin_notes is not None:
        draft.admin_notes = body.admin_notes

    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/drafts/{draft_id}/approve")
async def approve(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin onayı — PENDING_APPROVAL → APPROVED ve email kuyruğuna ekle."""
    draft = await _get_draft_or_404(db, draft_id)
    if draft.status != EmailDraftStatus.PENDING_APPROVAL:
        raise HTTPException(400, f"Sadece PENDING_APPROVAL taslaklar onaylanabilir (mevcut: {draft.status}).")
    await approve_draft(db, draft, admin)
    return {"detail": "Taslak onaylandı, gönderim kuyruğuna eklendi.", "draft_id": draft_id}


@router.post("/drafts/{draft_id}/reject")
async def reject(
    draft_id: str,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Admin reddi."""
    draft = await _get_draft_or_404(db, draft_id)
    if draft.status != EmailDraftStatus.PENDING_APPROVAL:
        raise HTTPException(400, f"Sadece PENDING_APPROVAL taslaklar reddedilebilir (mevcut: {draft.status}).")
    await reject_draft(db, draft, admin, body.reason)
    return {"detail": "Taslak reddedildi.", "draft_id": draft_id}


@router.post("/drafts/{draft_id}/retry")
async def retry(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """FAILED taslağı yeniden kuyruğa ekle."""
    draft = await _get_draft_or_404(db, draft_id)
    if draft.status != EmailDraftStatus.FAILED:
        raise HTTPException(400, "Sadece FAILED taslaklar yeniden denenebilir.")

    from app.db.models.email_draft import VALID_TRANSITIONS, EmailDraftStatus
    draft.status = EmailDraftStatus.APPROVED
    draft.last_error = None
    await db.commit()

    from app.tasks.queue import email_queue
    await email_queue.put(draft.id)
    return {"detail": "Taslak yeniden kuyruğa eklendi.", "draft_id": draft_id}


async def _get_draft_or_404(db: AsyncSession, draft_id: str) -> EmailDraft:
    result = await db.execute(select(EmailDraft).where(EmailDraft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(404, "Taslak bulunamadı.")
    return draft
