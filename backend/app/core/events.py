import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.config import settings
from app.db.models.email_draft import EmailDraft, EmailDraftStatus
from app.db.session import AsyncSessionLocal, engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: başlangıç ve kapanış işlemleri."""
    # ---- STARTUP --------------------------------------------------------
    logger.info("UniBox başlatılıyor...")

    # 1. Şema kontrolü — tablo OLUŞTURMUYORUZ, yalnızca doğruluyoruz.
    #
    # Eskiden burada Base.metadata.create_all vardı ve iki sorun yaratıyordu:
    #
    #  a) Alembic ile çakışıyordu. Boş bir üretim veritabanında uygulama önce
    #     açılırsa tablolar ORM'den yaratılıyor, alembic_version boş kalıyor ve
    #     sonraki "alembic upgrade head" "already exists" ile patlıyordu.
    #
    #  b) Ham SQL migration'ları SESSİZCE atlanıyordu: 0002 (pgvector
    #     eklentisi), 0005 (Türkçe FTS GIN indeksi), 0006 (1024 boyut + HNSW).
    #     create_all bunları bilmiyor. Sonuç: şema "çalışıyor" ama hibrit
    #     arama indekssiz kalıyor ve neden yavaş olduğu anlaşılmıyordu.
    #
    # Şema artık yalnızca "alembic upgrade head" ile kurulur.
    await _verify_schema()

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

    # Yalnızca ÇALIŞMASI GEREKEN worker'lar başlatılır. Bu ayrım önemli:
    # görev listesi aynı zamanda /ready canlılık kontrolünün referansı, yani
    # "listede olup bitmiş" = arıza demek. IMAP kapalıyken worker'ı başlatıp
    # hemen dönmesine izin vermek kalıcı bir yanlış alarm üretiyordu.
    _worker_tanımları = [
        ("email_worker", email_worker(email_queue)),
        ("index_worker", index_worker(index_queue)),
        ("retention_worker", retention_worker()),  # KVKK günlük temizlik
        ("incoming_analysis_worker", incoming_analysis_worker(incoming_analysis_queue)),
        ("incoming_reply_worker", incoming_reply_worker(incoming_reply_queue)),
    ]
    if settings.IMAP_BACKEND != "disabled":
        _worker_tanımları.append(("imap_poll_worker", imap_poll_worker()))
    else:
        logger.info("IMAP_BACKEND=disabled — gelen e-posta çekme worker'ı başlatılmıyor.")
    worker_tasks = []
    for ad, coro in _worker_tanımları:
        task = asyncio.create_task(coro, name=ad)
        _worker_gozetimi(task, ad)   # sessizce ölmesinler
        worker_tasks.append(task)
    app.state.worker_tasks = worker_tasks   # /health canlılık kontrolü için

    # 3. Crash recovery: bekleyen işleri yeniden kuyruğa ekle
    await _requeue_approved_drafts(email_queue)
    await _requeue_approved_incoming(incoming_reply_queue)
    await _requeue_received_incoming(incoming_analysis_queue)
    await _requeue_pending_documents(index_queue)

    logger.info("UniBox hazır.")

    yield  # Uygulama çalışıyor

    # ---- SHUTDOWN -------------------------------------------------------
    logger.info("UniBox kapatılıyor...")
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)
    await engine.dispose()
    logger.info("UniBox kapatıldı.")


async def _verify_schema() -> None:
    """Migration'ların uygulandığını doğrular; eksikse net bir hata verir.

    Amaç, "tablo yok" hatasını ilk isteğe kadar saklamak yerine açılışta
    söylemek. Hibrit aramanın dayandığı iki indeks de kontrol ediliyor —
    onlar olmadan sistem çalışır görünür ama sessizce bozuktur.
    """
    from sqlalchemy import text

    beklenen_indeksler = {
        "ix_document_chunks_content_fts_tr": "0005 (Türkçe tam metin arama)",
        "ix_document_chunks_embedding_cosine": "0006 (pgvector HNSW)",
    }

    async with engine.connect() as conn:
        sürüm = (await conn.execute(
            text("SELECT version_num FROM alembic_version")
        )).scalar_one_or_none() if await _tablo_var(conn, "alembic_version") else None

        if sürüm is None:
            raise RuntimeError(
                "Veritabanı şeması kurulmamış (alembic_version tablosu yok).\n"
                "Çözüm:  cd backend && uv run alembic upgrade head"
            )

        mevcut = set((await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'document_chunks'"
        ))).scalars())

    eksik = [f"{ad} — {açıklama}" for ad, açıklama in beklenen_indeksler.items()
             if ad not in mevcut]
    if eksik:
        logger.error(
            "Hibrit arama indeksleri eksik:\n  - %s\n"
            "Arama çalışır görünecek ama yavaş ve yanlış sıralanmış olacak. "
            "Çözüm: uv run alembic upgrade head",
            "\n  - ".join(eksik),
        )
    else:
        logger.info("Şema doğrulandı (alembic %s, hibrit arama indeksleri yerinde).", sürüm)


async def _tablo_var(conn, ad: str) -> bool:
    from sqlalchemy import text

    return bool((await conn.execute(
        text("SELECT to_regclass(:ad)"), {"ad": f"public.{ad}"}
    )).scalar())


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


async def _requeue_pending_documents(queue: asyncio.Queue) -> None:
    """İndekslenmeyi bekleyen dokümanları yeniden kuyruğa ekler.

    Bu kurtarma eksikti ve dokümanı ARAYÜZDEN KURTARILAMAZ hâle getiriyordu:
    kuyruk süreç-içi asyncio.Queue olduğu için yeniden başlatmada kayboluyor,
    doküman sonsuza dek PENDING kalıyor, reindex ucu ise (knowledge.py) yalnızca
    INDEXED ve FAILED durumlarını kabul ettiği için PENDING'de takılı dokümanı
    reddediyordu.

    PROCESSING da alınıyor: o durumdaki bir doküman, süreç indeksleme
    ortasında öldüğü için orada kalmıştır ve kendiliğinden ilerlemez.
    """
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status.in_([
                    ProcessingStatus.PENDING,
                    ProcessingStatus.PROCESSING,
                ]),
            )
        )
        for doc in result.scalars():
            await queue.put(doc.id)
            logger.info(
                "Crash recovery: Doküman %s (%s) indeksleme kuyruğuna eklendi.",
                doc.id, doc.status,
            )


def _worker_gozetimi(task: asyncio.Task, ad: str) -> None:
    """Worker beklenmedik şekilde biterse gürültülü şekilde logla.

    Worker'lar `except Exception` ile korunuyor ama BaseException türevleri
    (MemoryError gibi) döngüyü sonlandırıyor ve task sessizce bitiyordu.
    Sonuç: e-posta gönderimi tamamen durmuşken /health hâlâ 200 dönüyor ve
    kimse fark etmiyor.
    """
    def _bitti(t: asyncio.Task) -> None:
        if t.cancelled():
            return  # normal kapanış
        exc = t.exception()
        if exc is not None:
            logger.critical(
                "WORKER ÖLDÜ: %s — bu worker'ın işlediği kuyruk artık "
                "işlenmiyor. Uygulamanın yeniden başlatılması gerekiyor.",
                ad, exc_info=exc,
            )
        else:
            logger.critical("WORKER BEKLENMEDİK ŞEKİLDE BİTTİ: %s", ad)

    task.add_done_callback(_bitti)
