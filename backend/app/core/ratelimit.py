"""Hız sınırlama — kaba kuvvet ve kaynak tüketimine karşı.

Sistemde hiçbir hız sınırı yoktu. En açık iki hedef:

  POST /auth/login   — tek bir statik parolayı koruyor, sınırsız deneme
                       yapılabiliyordu.
  POST /chat/message — kimlik doğrulaması YOK ve her mesaj intent + yanıt
                       için LLM'e gidiyor (llm_provider timeout'u 300 sn).
                       Yerel GPU'yu doyurmanın en ucuz yolu buydu.

Depolama SÜREÇ-İÇİ (bellek). Bu bilinçli bir tercih: sistem tek bir kurum
içi sunucuda, tek uvicorn süreciyle çalışıyor. Birden fazla worker'a
geçilirse sınırlar süreç başına uygulanır — o noktada Redis'e taşınmalı.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)


def _istemci_anahtari(request: Request) -> str:
    """İstemciyi tanımlar. Ters vekil arkasında X-Forwarded-For kullanılır.

    DİKKAT: X-Forwarded-For istemci tarafından uydurulabilir. Yalnızca
    GÜVENDİĞİNİZ bir ters vekilin arkasındayken anlamlıdır; o vekil başlığı
    kendisi yazmalıdır. Doğrudan internete açık çalıştırmayın.
    """
    iletilen = request.headers.get("x-forwarded-for")
    if iletilen:
        return iletilen.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_istemci_anahtari,
    # Geliştirmede sınırları kapatmak testleri ve elle denemeyi kolaylaştırır.
    enabled=settings.APP_ENV != "development",
    default_limits=[],
)

# Sınırlar tek yerde toplandı ki uçlarda dağılmasın.
#
# LOGIN: dakikada 5. Meşru bir admin için fazlasıyla yeterli; sözlük
# saldırısını pratik olmaktan çıkarır.
LOGIN_LIMIT = "5/minute"

# CHAT: dakikada 20 mesaj. Hızlı yazan bir öğrenci için rahat, ama tek bir
# istemcinin LLM'i sürekli meşgul etmesini engeller.
CHAT_LIMIT = "20/minute"

# OTURUM AÇMA: saatte 30. Her çağrı bir DB satırı yaratıyor; sınırsız
# bırakmak konuşma tablosunu şişirmenin kolay yoluydu.
SESSION_LIMIT = "30/hour"

# YÜKLEME: saatte 20 doküman. Her yükleme indeksleme kuyruğuna iş ekliyor.
UPLOAD_LIMIT = "20/hour"


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 yanıtı — istemciye ne zaman tekrar deneyeceğini söyler."""
    logger.warning(
        "Hız sınırı aşıldı: %s %s (istemci=%s)",
        request.method, request.url.path, _istemci_anahtari(request),
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Çok fazla istek gönderildi. Lütfen biraz bekleyin."},
        headers={"Retry-After": "60"},
    )
