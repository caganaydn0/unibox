import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.db.models.email_draft import EmailDraft, EmailDraftStatus
from app.db.session import AsyncSessionLocal, engine
from app.db.base import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: başlangıç ve kapanış işlemleri."""
    # ---- STARTUP --------------------------------------------------------
    logger.info("UniBox başlatılıyor...")

    # 1. DB tablolarını oluştur (Alembic migrations yoksa fallback)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Worker'ları başlat
    from app.tasks.queue import email_queue, index_queue, incoming_analysis_queue, incoming_reply_queue
    from app.tasks.workers import (
        email_worker, index_worker,
        imap_poll_worker, incoming_analysis_worker, incoming_reply_worker,
    )

    app.state.email_queue = email_queue
    app.state.index_queue = index_queue
    app.state.incoming_analysis_queue = incoming_analysis_queue
    app.state.incoming_reply_queue = incoming_reply_queue

    from app.tasks.retention import retention_worker

    worker_tasks = [
        asyncio.create_task(email_worker(email_queue)),
        asyncio.create_task(index_worker(index_queue)),
        asyncio.create_task(retention_worker()),  # KVKK günlük temizlik
        # Gelen e-posta worker'ları
        asyncio.create_task(imap_poll_worker()),
        asyncio.create_task(incoming_analysis_worker(incoming_analysis_queue)),
        asyncio.create_task(incoming_reply_worker(incoming_reply_queue)),
    ]

    # 3. Crash recovery: bekleyen işleri yeniden kuyruğa ekle
    await _requeue_approved_drafts(email_queue)
    await _requeue_approved_incoming(incoming_reply_queue)
    await _requeue_received_incoming(incoming_analysis_queue)

    logger.info("UniBox hazır.")

    yield  # Uygulama çalışıyor

    # ---- SHUTDOWN -------------------------------------------------------
    logger.info("UniBox kapatılıyor...")
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)
    await engine.dispose()
    logger.info("UniBox kapatıldı.")


async def _requeue_approved_drafts(queue: asyncio.Queue) -> None:
    """Sunucu yeniden başladığında APPROVED statüsündeki draft'ları kuyruğa ekler."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailDraft).where(EmailDraft.status == EmailDraftStatus.APPROVED)
        )
        drafts = result.scalars().all()
        for draft in drafts:
            await queue.put(draft.id)
            logger.info("Crash recovery: Draft %s yeniden kuyruğa eklendi.", draft.id)


async def _requeue_received_incoming(queue: asyncio.Queue) -> None:
    """Sunucu yeniden başladığında RECEIVED statüsündeki gelen emailleri analiz kuyruğuna ekler."""
    from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(IncomingEmail).where(
                IncomingEmail.status == IncomingEmailStatus.RECEIVED
            )
        )
        for ie in result.scalars():
            await queue.put(ie.id)
            logger.info("Crash recovery: Incoming email %s analiz kuyruğuna eklendi.", ie.id)


async def _requeue_approved_incoming(queue: asyncio.Queue) -> None:
    """Sunucu yeniden başladığında APPROVED statüsündeki gelen email yanıtlarını kuyruğa ekler."""
    from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(IncomingEmail).where(
                IncomingEmail.status == IncomingEmailStatus.APPROVED
            )
        )
        for ie in result.scalars():
            await queue.put(ie.id)
            logger.info("Crash recovery: Incoming email %s yeniden kuyruğa eklendi.", ie.id)
