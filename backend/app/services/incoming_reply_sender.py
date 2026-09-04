"""Incoming Reply Sender — Gelen e-postaya AI yanıtı gönder

EmailSender pattern'ini takip eder: SMTP gönderim, audit log, KVKK PII temizliği.
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
from app.core.ws_manager import ws_manager
from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.db.models.email_log import EmailLog
from app.db.session import AsyncSessionLocal
from app.services.anonymizer import mask_body_for_log, mask_email_address

logger = logging.getLogger(__name__)


class IncomingReplySender:
    """Onaylanmış gelen e-posta yanıtlarını gönderir."""

    def _decrypt_email(self, enc: str) -> str:
        """Fernet şifreli e-posta adresini çöz."""
        from cryptography.fernet import Fernet

        f = Fernet(settings.FERNET_KEY.encode())
        return f.decrypt(enc.encode()).decode()

    async def send(self, incoming_email_id: str) -> None:
        """Yanıtı gönder, log oluştur, durum güncelle."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(IncomingEmail).where(IncomingEmail.id == incoming_email_id)
            )
            ie: IncomingEmail | None = result.scalar_one_or_none()

            if not ie:
                logger.error("IncomingEmail bulunamadı: %s", incoming_email_id)
                return

            if ie.status != IncomingEmailStatus.APPROVED:
                logger.warning(
                    "IncomingEmail %s gönderim için uygun değil (status=%s)",
                    incoming_email_id, ie.status,
                )
                return

            ie.send_attempts += 1

            try:
                # Alıcı adresini decrypt et
                to_email = self._decrypt_email(ie.sender_email_enc)

                # Admin notu varsa mailin sonuna NOT: önekiyle ekle
                body_to_send = ie.reply_body or ""
                if ie.admin_notes and ie.admin_notes.strip():
                    body_to_send = f"{body_to_send.rstrip()}\n\nNOT: {ie.admin_notes.strip()}"

                smtp_msg_id = await self._smtp_send(
                    to_email=to_email,
                    subject=ie.reply_subject or "Re: Yanıt",
                    body=body_to_send,
                    in_reply_to=ie.message_id,
                )

                # Başarılı — log oluştur
                log = EmailLog(
                    draft_id=None,  # Gelen email yanıtı, draft yok
                    incoming_email_id=ie.id,
                    recipient_email_hash=hashlib.sha256(to_email.encode()).hexdigest(),
                    # KVKK: email_log.py:35 "recipient_email kurumsal adres
                    # olduğu için saklanabilir" diyor. GİDEN akışta bu doğru
                    # (alıcı öğrenci işleri), ama BURADA alıcı öğrencinin
                    # KİŞİSEL adresi. Aşağıda sender_email_enc'i KVKK gereği
                    # siliyoruz; aynı adresi log tablosuna düz metin yazmak o
                    # silmeyi anlamsız kılardı. Maskelenmiş hâli saklanıyor,
                    # eşleştirme gerekirse recipient_email_hash var.
                    recipient_display=mask_email_address(to_email),
                    subject=ie.reply_subject or "",
                    body_anonymized=mask_body_for_log(ie.reply_body or ""),
                    retention_expires_at=datetime.utcnow()
                    + timedelta(days=settings.EMAIL_LOG_RETENTION_DAYS),
                )
                session.add(log)

                ie.status = IncomingEmailStatus.REPLIED
                ie.reply_sent_at = datetime.utcnow()
                ie.smtp_message_id = smtp_msg_id
                ie.last_error = None
                # KVKK: REPLIED sonrası PII temizle
                ie.sender_email_enc = ""
                await session.commit()

                logger.info("Yanıt gönderildi: incoming_email=%s", incoming_email_id)

                await ws_manager.broadcast_to_admins({
                    "type": "incoming_reply_sent",
                    "id": incoming_email_id,
                })

            except Exception as exc:
                logger.error(
                    "Yanıt gönderilemedi (id=%s, deneme=%d): %s",
                    incoming_email_id, ie.send_attempts, exc,
                )
                ie.last_error = str(exc)

                if ie.send_attempts >= settings.SMTP_MAX_RETRIES:
                    ie.status = IncomingEmailStatus.FAILED
                    logger.error("Max retry aşıldı, FAILED: %s", incoming_email_id)
                    await ws_manager.broadcast_to_admins({
                        "type": "incoming_reply_failed",
                        "id": incoming_email_id,
                        "error": str(exc),
                    })

                await session.commit()
                raise

    async def _smtp_send(
        self,
        to_email: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str | None:
        """SMTP ile yanıt gönder. In-Reply-To header ile thread'e bağla."""
        # KVKK: alıcı adresi Fernet ile şifrelenmiş hâlden ÇÖZÜLMÜŞ gerçek
        # öğrenci adresi. Maskelenmeden loglanırsa veritabanındaki şifreleme
        # anlamını yitirir. Bkz. email_sender._smtp_send'deki aynı not.
        if settings.SMTP_BACKEND == "console":
            logger.info("=" * 60)
            logger.info("REPLY EMAIL [CONSOLE MODE]")
            logger.info("To: %s", mask_email_address(to_email))
            logger.info("Subject: %s", subject)
            logger.info("In-Reply-To: %s", in_reply_to)
            logger.info("Body:\n%s", mask_body_for_log(body))
            logger.info("=" * 60)
            return None

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Thread bağlantısı
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

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
            response = await smtp.send_message(msg)
            return str(response) if response else None
