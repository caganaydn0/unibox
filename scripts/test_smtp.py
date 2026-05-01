#!/usr/bin/env python3
"""SMTP bağlantı testi — MailHog veya gerçek SMTP sunucu.

Kullanım:
    cd backend
    python ../scripts/test_smtp.py
"""
import asyncio
import sys
import os

# backend dizinini path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import settings


async def main():
    print(f"SMTP Sunucu: {settings.SMTP_HOST}:{settings.SMTP_PORT}")
    print(f"Gönderen: {settings.SMTP_FROM_EMAIL}")
    print(f"TLS: {settings.SMTP_USE_TLS}")
    print()

    import aiosmtplib
    from email.mime.text import MIMEText

    msg = MIMEText("UniBox SMTP test maili.", "plain", "utf-8")
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = settings.SMTP_FROM_EMAIL
    msg["Subject"] = "UniBox SMTP Test"

    try:
        smtp = aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            use_tls=settings.SMTP_USE_TLS,
        )
        async with smtp:
            if settings.SMTP_USERNAME:
                await smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            await smtp.send_message(msg)
        print("✓ Test maili başarıyla gönderildi!")
        print("  MailHog kullanıyorsanız: http://localhost:8025")
    except Exception as e:
        print(f"✗ SMTP hatası: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
