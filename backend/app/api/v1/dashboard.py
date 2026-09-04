"""Dashboard Stats API"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ws_manager import ws_manager
from app.db.models.email_draft import EmailDraft, EmailDraftStatus
from app.db.models.email_log import EmailLog
from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
from app.db.models.request_intent import RequestIntent
from app.deps import get_current_admin, get_db

router = APIRouter()


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Genel istatistikler: aktif oturumlar, bekleyen emailler, günlük gönderim, KB belge sayısı."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Aktif oturumlar (WS üzerinden gerçek zamanlı)
    active_sessions = ws_manager.active_student_count

    # Bekleyen email
    pending_count = await db.scalar(
        select(func.count(EmailDraft.id)).where(
            EmailDraft.status == EmailDraftStatus.PENDING_APPROVAL
        )
    )

    # Bugün gönderilen
    sent_today = await db.scalar(
        select(func.count(EmailLog.id)).where(
            EmailLog.sent_at >= today_start,
            EmailLog.deleted_at.is_(None),
        )
    )

    # Toplam KB belgesi
    total_docs = await db.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status == ProcessingStatus.INDEXED,
        )
    )

    # Son 7 günde intent dağılımı
    week_ago = now - timedelta(days=7)
    intents_result = await db.execute(
        select(RequestIntent.intent_type, func.count(RequestIntent.id).label("count"))
        .where(RequestIntent.detected_at >= week_ago)
        .group_by(RequestIntent.intent_type)
        .order_by(func.count(RequestIntent.id).desc())
    )
    intents_breakdown = [
        {"intent_type": row.intent_type, "count": row.count}
        for row in intents_result
    ]

    # Gelen e-posta: inceleme bekleyen
    pending_incoming = await db.scalar(
        select(func.count(IncomingEmail.id)).where(
            IncomingEmail.status == IncomingEmailStatus.PENDING_REVIEW
        )
    )

    # Gelen e-posta: bugün yanıtlanan
    replied_today = await db.scalar(
        select(func.count(IncomingEmail.id)).where(
            IncomingEmail.reply_sent_at >= today_start,
            IncomingEmail.status == IncomingEmailStatus.REPLIED,
        )
    )

    return {
        "active_sessions": active_sessions,
        "pending_emails": pending_count or 0,
        "sent_today": sent_today or 0,
        "total_documents": total_docs or 0,
        "intents_breakdown": intents_breakdown,
        "pending_incoming": pending_incoming or 0,
        "replied_today": replied_today or 0,
    }


@router.get("/activity")
async def get_activity(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Son aktiviteler (intent tespitleri, durum değişiklikleri)."""
    result = await db.execute(
        select(RequestIntent)
        .order_by(RequestIntent.detected_at.desc())
        .limit(limit)
    )
    intents = result.scalars().all()

    activities = []
    for intent in intents:
        activities.append({
            "type": "intent_detected",
            "conversation_id": intent.conversation_id,
            "intent_type": intent.intent_type,
            "requires_email": intent.requires_email,
            "ts": intent.detected_at.isoformat(),
        })

    return {"activities": activities}
