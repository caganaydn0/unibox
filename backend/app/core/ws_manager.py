import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket bağlantı yöneticisi.

    KVKK: İki tamamen ayrı kanal:
    - student_connections: öğrenci ↔ bot (bidirectional)
    - admin_connections: admin izleme (server-push only, read-only)

    Kanallar asla birleştirilmez — admin eventi öğrenciye sızmaz.
    """

    def __init__(self) -> None:
        # session_token → WebSocket (bir oturum = bir bağlantı)
        self._student: dict[str, WebSocket] = {}
        # Admin bağlantıları kümesi
        self._admins: set[WebSocket] = set()

    # ---- Öğrenci kanalı ------------------------------------------------

    async def connect_student(self, session_token: str, ws: WebSocket) -> None:
        await ws.accept()
        # Aynı token'dan önceki bağlantı varsa kapat
        old = self._student.get(session_token)
        if old:
            try:
                await old.close(code=1001)
            except Exception:
                pass
        self._student[session_token] = ws
        logger.info("Öğrenci bağlandı: %s", session_token[:8])

    def disconnect_student(self, session_token: str) -> None:
        self._student.pop(session_token, None)
        logger.info("Öğrenci ayrıldı: %s", session_token[:8])

    async def send_to_student(self, session_token: str, data: dict[str, Any]) -> None:
        ws = self._student.get(session_token)
        if ws:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception as exc:
                logger.warning("Öğrenciye mesaj gönderilemedi (%s): %s", session_token[:8], exc)
                self.disconnect_student(session_token)

    # ---- Admin kanalı --------------------------------------------------

    async def connect_admin(self, ws: WebSocket) -> None:
        await ws.accept()
        self._admins.add(ws)
        logger.info("Admin bağlandı. Toplam admin: %d", len(self._admins))

    def disconnect_admin(self, ws: WebSocket) -> None:
        self._admins.discard(ws)
        logger.info("Admin ayrıldı. Toplam admin: %d", len(self._admins))

    async def broadcast_to_admins(self, event: dict[str, Any]) -> None:
        """Tüm admin bağlantılarına anonim event gönder."""
        if not self._admins:
            return
        payload = json.dumps(event, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in self._admins:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("Admin'e broadcast başarısız: %s", exc)
                dead.add(ws)
        self._admins -= dead

    # ---- Durum bilgisi -------------------------------------------------

    @property
    def active_student_count(self) -> int:
        return len(self._student)

    @property
    def active_admin_count(self) -> int:
        return len(self._admins)


# Uygulama genelinde tek örnek (singleton)
ws_manager = ConnectionManager()
