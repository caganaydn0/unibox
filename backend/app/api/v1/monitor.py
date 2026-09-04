"""Admin Monitor WebSocket — Read-only anonim event stream

KVKK: Bu kanal admin'e öğrenci konuşmalarının anonim özetini gösterir.
Öğrenci kanalından tamamen ayrıdır. Admin, öğrenciye mesaj gönderemez.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.core.ws_manager import ws_manager
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# İstemci bağlandıktan sonra auth çerçevesini göndermesi için tanınan süre.
AUTH_TIMEOUT_SECONDS = 10.0


@router.websocket("/ws")
async def monitor_websocket(websocket: WebSocket) -> None:
    """Admin izleme WebSocket.

    Bağlanmak için URL: ws://host/api/v1/monitor/ws (jeton URL'DE DEĞİL).
    Bağlantı kurulduktan sonra ilk çerçeve olarak
    {"type":"auth","token":"<access_token>"} beklenir.

    Eskiden jeton ?token= query string'inde taşınıyordu; bu, uvicorn access
    log'una ve araya giren her ters proxy'nin loguna JWT'yi düz metin
    yazıyordu. Tarayıcı WebSocket API'si el sıkışmaya özel bir HTTP header
    ekleyemediği için gerçek bir "header'a taşıma" mümkün değil — pratik
    eşdeğeri, jetonu URL'den tamamen çıkarıp bağlantı KURULDUKTAN SONRA ilk
    uygulama mesajıyla göndermek.

    Origin kontrolü: WS el sıkışması CORS'a tabi değil — tarayıcı çapraz-origin
    bir WS bağlantısını kendiliğinden engellemiyor, sunucu reddetmeli.
    `settings.cors_origin_listesi` (main.py'deki CORSMiddleware ile aynı
    liste) kullanılıyor; üretimde CORS_ORIGINS ayarlanmamışsa liste boş döner
    ve TÜM bağlantılar reddedilir (sessiz açık sistem yerine gürültülü hata).
    """
    origin = websocket.headers.get("origin")
    if origin not in settings.cors_origin_listesi:
        # accept() öncesi close — el sıkışma reddedilir.
        await websocket.close(code=4403, reason="Origin izinli değil")
        return

    await websocket.accept()

    token: str | None = None
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        frame = json.loads(raw)
        if frame.get("type") == "auth":
            token = frame.get("token")
    except Exception:
        token = None

    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.close(code=4001, reason="Yetkisiz")
        return

    await ws_manager.connect_admin(websocket)
    try:
        # Heartbeat
        async def heartbeat():
            while True:
                await asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL)
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

        hb_task = asyncio.create_task(heartbeat())

        try:
            # Admin mesaj göndermeye çalışırsa yoksay (read-only)
            while True:
                await asyncio.wait_for(websocket.receive_text(), timeout=300.0)
        except asyncio.TimeoutError:
            await websocket.close(code=1001, reason="Zaman aşımı")
        except WebSocketDisconnect:
            pass
        finally:
            hb_task.cancel()

    except Exception as exc:
        logger.error("Admin WS hatası: %s", exc, exc_info=True)
    finally:
        ws_manager.disconnect_admin(websocket)
