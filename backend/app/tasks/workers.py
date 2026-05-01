import asyncio
import logging

logger = logging.getLogger(__name__)


async def email_worker(queue: asyncio.Queue) -> None:
    """E-posta gönderim worker'ı.

    queue'dan draft_id alır, email_sender.send() çağırır.
    Başarısız olursa retry sayısına bakar, max'a ulaşınca FAILED işaretler.
    """
    from app.services.email_sender import EmailSender

    sender = EmailSender()
    logger.info("Email worker başlatıldı.")

    while True:
        draft_id: str = await queue.get()
        try:
            logger.info("Email gönderiliyor: draft=%s", draft_id)
            await sender.send(draft_id)
        except Exception as exc:
            logger.error("Email worker hatası (draft=%s): %s", draft_id, exc, exc_info=True)
        finally:
            queue.task_done()


async def index_worker(queue: asyncio.Queue) -> None:
    """Doküman indeksleme worker'ı.

    queue'dan document_id alır, rag_engine.index_document() çağırır.
    """
    from app.services.rag_engine import RagEngine

    rag = RagEngine()
    logger.info("Index worker başlatıldı.")

    while True:
        doc_id: str = await queue.get()
        try:
            logger.info("Doküman indeksleniyor: doc=%s", doc_id)
            await rag.index_document(doc_id)
        except Exception as exc:
            logger.error("Index worker hatası (doc=%s): %s", doc_id, exc, exc_info=True)
        finally:
            queue.task_done()


async def imap_poll_worker() -> None:
    """Periyodik IMAP polling worker'ı.

    IMAP_POLL_INTERVAL_SECONDS aralıklarla inbox'ı kontrol eder.
    IMAP_BACKEND == "disabled" ise çalışmaz.
    """
    from app.config import settings

    if settings.IMAP_BACKEND == "disabled":
        logger.info("IMAP backend devre dışı, poll worker çalışmayacak.")
        return

    from app.services.imap_receiver import ImapReceiver
    from app.tasks.queue import incoming_analysis_queue

    receiver = ImapReceiver()
    logger.info(
        "IMAP poll worker başlatıldı (interval=%ds).",
        settings.IMAP_POLL_INTERVAL_SECONDS,
    )

    while True:
        try:
            new_ids = await receiver.poll()
            for email_id in new_ids:
                await incoming_analysis_queue.put(email_id)
                logger.info("Gelen email analiz kuyruğuna eklendi: %s", email_id)
                from app.core.ws_manager import ws_manager
                await ws_manager.broadcast_to_admins({
                    "type": "incoming_email_received",
                    "id": email_id,
                })
        except Exception as exc:
            logger.error("IMAP poll hatası: %s", exc, exc_info=True)
        await asyncio.sleep(settings.IMAP_POLL_INTERVAL_SECONDS)


async def incoming_analysis_worker(queue: asyncio.Queue) -> None:
    """Gelen e-posta analiz worker'ı.

    queue'dan incoming_email_id alır, RAG + LLM ile analiz eder.
    """
    from app.services.email_analyzer import EmailAnalyzer

    analyzer = EmailAnalyzer()
    logger.info("Incoming analysis worker başlatıldı.")

    while True:
        incoming_id: str = await queue.get()
        try:
            logger.info("Gelen email analiz ediliyor: %s", incoming_id)
            await analyzer.analyze(incoming_id)
        except Exception as exc:
            logger.error(
                "Analysis worker hatası (id=%s): %s", incoming_id, exc, exc_info=True
            )
        finally:
            queue.task_done()


async def incoming_reply_worker(queue: asyncio.Queue) -> None:
    """Gelen e-posta yanıt gönderim worker'ı.

    queue'dan incoming_email_id alır, onaylanmış yanıtı gönderir.
    """
    from app.services.incoming_reply_sender import IncomingReplySender

    sender = IncomingReplySender()
    logger.info("Incoming reply worker başlatıldı.")

    while True:
        incoming_id: str = await queue.get()
        try:
            logger.info("Gelen email yanıtı gönderiliyor: %s", incoming_id)
            await sender.send(incoming_id)
        except Exception as exc:
            logger.error(
                "Reply worker hatası (id=%s): %s", incoming_id, exc, exc_info=True
            )
        finally:
            queue.task_done()
