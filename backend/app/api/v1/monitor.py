"""Admin Monitor WebSocket — Read-only anonim event stream

KVKK: Bu kanal admin'e öğrenci konuşmalarının anonim özetini gösterir.
Öğrenci kanalından tamamen ayrıdır. Admin, öğrenciye mesaj gönderemez.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from app.core.security import decode_access_token
from app.core.ws_manager import ws_manager
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def monitor_websocket(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Admin izleme WebSocket.

    Bağlanmak için URL: ws://host/api/v1/monitor/ws?token=<access_token>
    Server-push only: admin sadece alır, gönderemez.
    """
    # JWT doğrulama
    payload = decode_access_token(token)
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
