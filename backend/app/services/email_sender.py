"""Email Sender — SMTP gönderim + retry

KVKK: email_log oluştururken PII maskeleme uygulanır.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select

from app.config import settings
from app.db.models.email_draft import EmailDraft, EmailDraftStatus
from app.db.models.email_log import EmailLog
from app.db.session import AsyncSessionLocal
from app.services.anonymizer import mask_body_for_log

logger = logging.getLogger(__name__)


class EmailSender:
    async def send(self, draft_id: str) -> None:
        """Draft'ı gönder, log oluştur, durum güncelle."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EmailDraft).where(EmailDraft.id == draft_id)
            )
            draft: EmailDraft | None = result.scalar_one_or_none()

            if not draft:
                logger.error("Draft bulunamadı: %s", draft_id)
                return

            if draft.status != EmailDraftStatus.APPROVED:
                logger.warning(
                    "Draft %s gönderim için uygun değil (status=%s)", draft_id, draft.status
                )
                return

            draft.send_attempts += 1

            try:
                await self._smtp_send(
                    to_email=draft.recipient_email or settings.SMTP_FROM_EMAIL,
                    subject=draft.subject or "(konu yok)",
                    body=draft.body or "",
                )

                # Başarılı — log oluştur ve SENT işaretle
                log = EmailLog(
                    draft_id=draft.id,
                    recipient_email_hash=hashlib.sha256(
                        (draft.recipient_email or "").encode()
                    ).hexdigest(),
                    recipient_display=draft.recipient_email or "",
                    subject=draft.subject or "",
                    # KVKK: body PII maskelenerek kaydedilir
                    body_anonymized=mask_body_for_log(draft.body or ""),
                    retention_expires_at=datetime.utcnow()
                    + timedelta(days=settings.EMAIL_LOG_RETENTION_DAYS),
                )
                session.add(log)

                draft.status = EmailDraftStatus.SENT
                # KVKK: SENT sonrası PII temizle
                draft.collected_fields_enc = None
                draft.last_error = None
                await session.commit()

                logger.info("Email gönderildi: draft=%s", draft_id)

                # Öğrenciyi bildir
                from app.core.ws_manager import ws_manager
                await ws_manager.send_to_student(
                    draft.conversation_id,
                    {
                        "type": "email_sent",
                        "message": "E-postanız ilgili birime iletildi.",
                    },
                )

            except Exception as exc:
                logger.error(
                    "Email gönderilemedi (draft=%s, deneme=%d): %s",
                    draft_id, draft.send_attempts, exc,
                )
                draft.last_error = str(exc)

                if draft.send_attempts >= settings.SMTP_MAX_RETRIES:
                    draft.status = EmailDraftStatus.FAILED
                    logger.error("Max retry aşıldı, draft FAILED: %s", draft_id)
                    from app.core.ws_manager import ws_manager
                    await ws_manager.broadcast_to_admins({
                        "type": "email_failed",
                        "draft_id": draft_id,
                        "error": str(exc),
                    })
                else:
                    # Bir sonraki deneme için tekrar APPROVED bırak
                    # (worker döngüsü tekrar deneyecek — üstel geri çekilme yok,
                    # admin retry butonunu kullanabilir)
                    pass

                await session.commit()
                raise

    async def _smtp_send(self, to_email: str, subject: str, body: str) -> None:
        """SMTP üzerinden mail gönder (veya console modunda logla)."""
        # Console modu — Docker/SMTP gerektirmez
        if settings.SMTP_BACKEND == "console":
            logger.info("=" * 60)
            logger.info("EMAIL [CONSOLE MODE]")
            logger.info("To: %s", to_email)
            logger.info("Subject: %s", subject)
            logger.info("Body:\n%s", body)
            logger.info("=" * 60)
            return

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Port 465 → direkt TLS (SMTPS), Port 587 → STARTTLS
        _use_tls = settings.SMTP_USE_TLS and settings.SMTP_PORT == 465
        _start_tls = settings.SMTP_USE_TLS and settings.SMTP_PORT != 465

        smtp = aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            use_tls=_use_tls,
            start_tls=_start_tls,
        )
        async with smtp:
            if settings.SMTP_USERNAME:
                await smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            await smtp.send_message(msg)
