"""KVKK Veri Saklama Yönetimi

Periyodik olarak çalışır (günlük), süresi dolan kayıtları temizler.
FastAPI lifespan'de asyncio task olarak başlatılır.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.db.models.conversation import Conversation
from app.db.models.email_log import EmailLog
from app.db.models.incoming_email import IncomingEmail
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# 24 saat
RETENTION_CHECK_INTERVAL = 24 * 60 * 60


async def retention_worker() -> None:
    """Günlük KVKK temizlik görevi."""
    logger.info("Retention worker başlatıldı.")
    while True:
        await asyncio.sleep(RETENTION_CHECK_INTERVAL)
        try:
            await run_retention()
        except Exception as exc:
            logger.error("Retention hatası: %s", exc, exc_info=True)


async def run_retention() -> dict:
    """Süresi dolan kayıtları temizle. İstatistik sözlüğü döner."""
    now = datetime.utcnow()
    stats = {"conversations_deleted": 0, "logs_deleted": 0}

    async with AsyncSessionLocal() as session:
        # 1. Süresi dolan konuşmaları soft-delete
        expired_convs = await session.execute(
            select(Conversation).where(
                Conversation.retention_expires_at <= now,
                Conversation.deleted_at.is_(None),
            )
        )
        for conv in expired_convs.scalars():
            conv.deleted_at = now
            conv.messages_json = "[]"
            # Bağlı draft'lardaki PII'yi temizle
            for draft in conv.email_drafts:
                draft.collected_fields_enc = None
            stats["conversations_deleted"] += 1

        # 2. Süresi dolan email log'larını soft-delete
        expired_logs = await session.execute(
            select(EmailLog).where(
                EmailLog.retention_expires_at <= now,
                EmailLog.deleted_at.is_(None),
            )
        )
        for log in expired_logs.scalars():
            log.deleted_at = now
            stats["logs_deleted"] += 1

        # 3. Süresi dolan gelen e-postaları soft-delete + PII temizle
        expired_incoming = await session.execute(
            select(IncomingEmail).where(
                IncomingEmail.retention_expires_at <= now,
                IncomingEmail.deleted_at.is_(None),
            )
        )
        for ie in expired_incoming.scalars():
            ie.deleted_at = now
            ie.sender_email_enc = ""
            ie.body_text = None
            ie.body_html = None
            ie.reply_body = None
            stats["incoming_emails_deleted"] = stats.get("incoming_emails_deleted", 0) + 1

        await session.commit()

    logger.info("Retention tamamlandı: %s", stats)
    return stats
