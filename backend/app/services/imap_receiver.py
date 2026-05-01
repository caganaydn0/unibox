"""IMAP Receiver — Gelen e-posta alma ve parse etme

Gmail IMAP üzerinden öğrenci e-postalarını çeker,
MIME parse eder, dedup yapar, DB'ye kaydeder.
"""
from __future__ import annotations

import asyncio
import email
import hashlib
import imaplib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Otomatik yanıt / bounce algılama
_AUTO_REPLY_HEADERS = {"auto-submitted", "x-autorespond", "x-auto-response-suppress"}


@dataclass
class ParsedEmail:
    message_id: str
    imap_uid: int | None
    sender_email: str
    sender_name: str | None
    subject: str | None
    body_text: str | None
    body_html: str | None
    received_at: datetime
    has_attachments: bool
    attachment_names: list[str] = field(default_factory=list)
    is_auto_reply: bool = False


class ImapReceiver:
    """IMAP e-posta alıcı — poll(), parse, dedup, store."""

    def _encrypt_email(self, email_addr: str) -> str:
        """E-posta adresini Fernet ile şifrele."""
        from cryptography.fernet import Fernet

        f = Fernet(settings.FERNET_KEY.encode())
        return f.encrypt(email_addr.encode()).decode()

    def _hash_email(self, email_addr: str) -> str:
        """E-posta adresinin SHA-256 hash'ini döndür."""
        return hashlib.sha256(email_addr.lower().strip().encode()).hexdigest()

    async def poll(self) -> list[str]:
        """IMAP'a bağlan, UNSEEN mailler al, parse et, DB'ye kaydet.

        Returns:
            Yeni kaydedilen incoming_email id'lerinin listesi.
        """
        loop = asyncio.get_event_loop()
        raw_messages = await loop.run_in_executor(None, self._fetch_unseen)
        if not raw_messages:
            return []

        new_ids: list[str] = []
        for uid, raw_bytes in raw_messages:
            parsed = self._parse_mime(raw_bytes, uid)
            if parsed.is_auto_reply:
                logger.info("Otomatik yanıt atlanıyor: %s", parsed.message_id)
                # IMAP'ta seen olarak işaretle
                await loop.run_in_executor(None, self._mark_seen_on_server, uid)
                continue

            stored_id = await self._store_email(parsed)
            if stored_id:
                new_ids.append(stored_id)
                await loop.run_in_executor(None, self._mark_seen_on_server, uid)

        return new_ids

    def _fetch_unseen(self) -> list[tuple[int, bytes]]:
        """IMAP sunucusundan yeni mailleri al (sync).

        Önce UNSEEN, yoksa son 1 günlük mailleri tarar.
        Dedup _store_email'de message_id ile yapılır, bu yüzden
        okunmuş mailler de güvenle alınabilir.
        """
        results: list[tuple[int, bytes]] = []
        try:
            if settings.IMAP_USE_SSL:
                conn = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
            else:
                conn = imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT)

            conn.login(settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
            conn.select(settings.IMAP_MAILBOX)

            # Önce UNSEEN dene
            status, data = conn.search(None, "UNSEEN")
            uids = data[0].split() if status == "OK" and data[0] else []

            # UNSEEN yoksa son 1 günlük mailler arasında da bak
            if not uids:
                since_date = (datetime.utcnow() - timedelta(days=1)).strftime("%d-%b-%Y")
                status, data = conn.search(None, f"SINCE {since_date}")
                uids = data[0].split() if status == "OK" and data[0] else []

            # Limit
            uids = uids[: settings.IMAP_MAX_FETCH_PER_POLL]

            for uid_bytes in uids:
                uid = int(uid_bytes)
                # Fetch ama SEEN işaretleme (PEEK)
                status, msg_data = conn.fetch(uid_bytes, "(BODY.PEEK[])")
                if status == "OK" and msg_data and msg_data[0]:
                    raw = msg_data[0]
                    if isinstance(raw, tuple) and len(raw) >= 2:
                        results.append((uid, raw[1]))

            conn.logout()
        except Exception as exc:
            logger.error("IMAP fetch hatası: %s", exc, exc_info=True)

        return results

    def _mark_seen_on_server(self, uid: int) -> None:
        """IMAP'ta mesajı okundu olarak işaretle."""
        try:
            if settings.IMAP_USE_SSL:
                conn = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
            else:
                conn = imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT)

            conn.login(settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
            conn.select(settings.IMAP_MAILBOX)
            conn.store(str(uid).encode(), "+FLAGS", "\\Seen")
            conn.logout()
        except Exception as exc:
            logger.error("IMAP mark seen hatası (uid=%s): %s", uid, exc)

    def _parse_mime(self, raw_bytes: bytes, uid: int | None = None) -> ParsedEmail:
        """Raw MIME verisini parse et."""
        msg = email.message_from_bytes(raw_bytes)

        # Message-ID
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            message_id = f"<generated-{hashlib.md5(raw_bytes[:500]).hexdigest()}@unibox>"

        # Gönderen
        sender_name_raw, sender_email = parseaddr(msg.get("From", ""))
        sender_name = self._decode_header_value(sender_name_raw) if sender_name_raw else None

        # Konu
        subject = self._decode_header_value(msg.get("Subject", ""))

        # Tarih — DB naive UTC bekliyor, timezone-aware ise UTC'ye çevir ve strip et
        try:
            received_at = parsedate_to_datetime(msg.get("Date", ""))
            if received_at.tzinfo is not None:
                from datetime import timezone
                received_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        # Otomatik yanıt kontrolü
        is_auto_reply = False
        for header in _AUTO_REPLY_HEADERS:
            if msg.get(header):
                is_auto_reply = True
                break
        # Precedence: bulk/junk/list
        precedence = (msg.get("Precedence") or "").lower()
        if precedence in ("bulk", "junk", "list"):
            is_auto_reply = True
        # noreply / no-reply adreslerini atla
        if sender_email and re.match(r"^(noreply|no-reply|mailer-daemon)", sender_email.lower()):
            is_auto_reply = True

        # Body çıkarma
        body_text: str | None = None
        body_html: str | None = None
        attachment_names: list[str] = []
        has_attachments = False

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition") or "")

                if "attachment" in disposition:
                    has_attachments = True
                    filename = part.get_filename()
                    if filename:
                        attachment_names.append(self._decode_header_value(filename))
                    continue

                if content_type == "text/plain" and not body_text:
                    body_text = self._decode_payload(part)
                elif content_type == "text/html" and not body_html:
                    body_html = self._decode_payload(part)
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                body_text = self._decode_payload(msg)
            elif content_type == "text/html":
                body_html = self._decode_payload(msg)

        # HTML-only email → basit text çıkarma
        if not body_text and body_html:
            body_text = self._html_to_text(body_html)

        return ParsedEmail(
            message_id=message_id,
            imap_uid=uid,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            has_attachments=has_attachments,
            attachment_names=attachment_names,
            is_auto_reply=is_auto_reply,
        )

    def _decode_header_value(self, value: str) -> str:
        """RFC 2047 encoded header değerini decode et."""
        if not value:
            return ""
        parts = decode_header(value)
        decoded_parts = []
        for data, charset in parts:
            if isinstance(data, bytes):
                encoding = charset or "utf-8"
                try:
                    decoded_parts.append(data.decode(encoding))
                except (UnicodeDecodeError, LookupError):
                    # windows-1254 / iso-8859-9 fallback
                    for fallback in ("utf-8", "windows-1254", "iso-8859-9", "latin-1"):
                        try:
                            decoded_parts.append(data.decode(fallback))
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        decoded_parts.append(data.decode("latin-1", errors="replace"))
            else:
                decoded_parts.append(data)
        return "".join(decoded_parts)

    def _decode_payload(self, part: email.message.Message) -> str | None:
        """Email part payload'ını decode et."""
        payload = part.get_payload(decode=True)
        if not payload:
            return None
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset)
        except (UnicodeDecodeError, LookupError):
            for fallback in ("utf-8", "windows-1254", "iso-8859-9", "latin-1"):
                try:
                    return payload.decode(fallback)
                except (UnicodeDecodeError, LookupError):
                    continue
        return payload.decode("latin-1", errors="replace")

    def _html_to_text(self, html: str) -> str:
        """Basit HTML → text dönüşümü."""
        # Script/style tag'lerini kaldır
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # <br> → newline
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        # <p> → double newline
        text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Tüm tag'leri kaldır
        text = re.sub(r"<[^>]+>", "", text)
        # HTML entities
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        # Fazla boşlukları temizle
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def _store_email(self, parsed: ParsedEmail) -> str | None:
        """Parse edilmiş e-postayı DB'ye kaydet. Duplicate ise None döndür."""
        async with AsyncSessionLocal() as session:
            # Dedup kontrolü
            existing = await session.execute(
                select(IncomingEmail.id).where(
                    IncomingEmail.message_id == parsed.message_id
                )
            )
            if existing.scalar_one_or_none():
                logger.debug("Duplicate email atlanıyor: %s", parsed.message_id)
                return None

            incoming = IncomingEmail(
                message_id=parsed.message_id,
                imap_uid=parsed.imap_uid,
                sender_email_enc=self._encrypt_email(parsed.sender_email),
                sender_email_hash=self._hash_email(parsed.sender_email),
                sender_name=parsed.sender_name,
                subject=parsed.subject,
                body_text=parsed.body_text,
                body_html=parsed.body_html,
                has_attachments=parsed.has_attachments,
                attachment_names_json=json.dumps(parsed.attachment_names, ensure_ascii=False),
                status=IncomingEmailStatus.RECEIVED,
                received_at=parsed.received_at,
                retention_expires_at=datetime.utcnow()
                + timedelta(days=settings.INCOMING_EMAIL_RETENTION_DAYS),
            )
            session.add(incoming)
            try:
                await session.commit()
                logger.info(
                    "Gelen e-posta kaydedildi: id=%s, from_hash=%s, subject=%s",
                    incoming.id,
                    incoming.sender_email_hash[:12],
                    parsed.subject,
                )
                return incoming.id
            except IntegrityError:
                await session.rollback()
                logger.debug("Duplicate email (IntegrityError): %s", parsed.message_id)
                return None
