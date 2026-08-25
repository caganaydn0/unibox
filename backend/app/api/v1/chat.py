"""Chat API — WebSocket ve REST fallback

Öğrenci ↔ Bot iletişim katmanı.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ws_manager import ws_manager
from app.db.models.conversation import Conversation
from app.db.session import AsyncSessionLocal
from app.deps import get_db
from app.services.anonymizer import mask_pii
from app.services.intent_detector import detect_intent
from app.services.email_workflow import handle_message

router = APIRouter()
logger = logging.getLogger(__name__)

# Oturum jetonu: secrets.token_urlsafe(32) → 43 karakter [A-Za-z0-9_-]
SESSION_TOKEN_BYTES = 32
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")

# Konuşma geçmişi üst sınırı — bkz. _append_message
MAX_MESSAGES = 200
MAX_MESSAGES_JSON = 65536

# Tek mesaj uzunluk sınırı. Her mesaj intent tespiti + yanıt için LLM'e
# gidiyor ve llm_provider timeout'u 300 sn; sınırsız uzunluk kimlik
# doğrulamasız bir uçtan GPU tüketmenin en kolay yolu.
MAX_MESSAGE_LEN = 4000


def _now_utc() -> datetime:
    return datetime.utcnow()


def yeni_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def _token_gecerli_mi(token: str) -> bool:
    """Jeton SUNUCU tarafından üretilmiş olabilir mi?

    Format doğrulaması iki işe yarıyor:
      - "1", "test", "admin" gibi tahmin edilebilir jetonları eler
      - conversations.session_token String(64); daha uzun bir değer
        asyncpg'de StringDataRightTruncation ile 500 üretiyordu
    """
    return bool(token and _TOKEN_RE.match(token))


async def _get_conversation(
    session: AsyncSession, session_token: str
) -> Conversation | None:
    """Jetona karşılık gelen konuşmayı getirir. OLUŞTURMAZ.

    GÜVENLİK — eski davranış: bu fonksiyon jetonu istemciden alıp yoksa
    konuşma YARATIYORDU. Yani jeton sunucu tarafından üretilmiyor,
    doğrulanmıyordu; "1" göndermek geçerli bir oturum açıyordu. Sonuç olarak
    jetonu bilen/tahmin eden herkes GET /history ile başkasının konuşmasını
    okuyabiliyor, DELETE /session ile silebiliyordu.

    Oturum artık yalnızca POST /chat/session ile açılır.
    """
    if not _token_gecerli_mi(session_token):
        return None
    result = await session.execute(
        select(Conversation).where(
            Conversation.session_token == session_token,
            Conversation.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _append_message(
    session: AsyncSession, conv: Conversation, role: str, content: str
) -> None:
    """Konuşma geçmişine mesaj ekle (PII maskelenerek).

    Sınırlama ESKİ MESAJLARI BUDAYARAK yapılıyor, JSON metnini keserek değil.

    Eski kod `json.dumps(messages)[:65536]` yazıyordu; bu, sınıra ulaşan bir
    konuşmada JSON'u ORTASINDAN kesiyor ve geçersiz hâle getiriyordu. Bir
    sonraki mesajda json.loads kalıcı olarak patlıyor, GET /history de kalıcı
    500 dönüyordu — konuşma bir daha asla kullanılamıyordu.
    """
    try:
        messages: list[dict] = json.loads(conv.messages_json)
        if not isinstance(messages, list):
            raise ValueError("liste bekleniyordu")
    except Exception:
        logger.warning(
            "Konuşma geçmişi okunamadı (session=%s…), sıfırlanıyor.",
            conv.session_token[:8],
        )
        messages = []

    messages.append({
        "role": role,
        # KVKK: PII yazım anında maskelenir
        "content": mask_pii(content),
        "ts": _now_utc().isoformat(),
    })

    # Önce mesaj sayısı, sonra bayt boyutu — ikisi de en eskiden budanır
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    kodlanmış = json.dumps(messages, ensure_ascii=False)
    while len(kodlanmış) > MAX_MESSAGES_JSON and len(messages) > 1:
        messages = messages[1:]
        kodlanmış = json.dumps(messages, ensure_ascii=False)

    conv.messages_json = kodlanmış
    conv.last_active_at = _now_utc()
    await session.commit()


# ---- Oturum açma -----------------------------------------------------

class SessionResponse(BaseModel):
    session_token: str
    expires_in_days: int


@router.post("/session", response_model=SessionResponse, status_code=201)
async def create_session(db: AsyncSession = Depends(get_db)) -> SessionResponse:
    """Yeni öğrenci sohbet oturumu açar ve jetonu BİR KEZ döner.

    Jeton kriptografik olarak güvenli üretilir (secrets.token_urlsafe).
    Eskiden jeton istemciden geliyordu ve doğrulanmıyordu.
    """
    now = _now_utc()
    conv = Conversation(
        session_token=yeni_session_token(),
        started_at=now,
        last_active_at=now,
        retention_expires_at=now + timedelta(days=settings.CONVERSATION_RETENTION_DAYS),
    )
    db.add(conv)
    await db.commit()
    logger.info("Yeni sohbet oturumu açıldı: %s…", conv.session_token[:8])
    return SessionResponse(
        session_token=conv.session_token,
        expires_in_days=settings.CONVERSATION_RETENTION_DAYS,
    )


# ---- WebSocket -------------------------------------------------------

@router.websocket("/ws/{session_token}")
async def chat_websocket(session_token: str, ws: WebSocket):
    """Öğrenci WebSocket bağlantısı.

    Frame formatları:
    → {"type": "message", "content": "..."}
    ← {"type": "message"|"state_change"|"draft_preview"|"error", ...}
    """
    # Jeton geçerli bir oturuma ait değilse bağlantıyı hiç kabul etme.
    # Eskiden bilinmeyen bir jeton sessizce YENİ oturum yaratıyordu.
    async with AsyncSessionLocal() as session:
        if await _get_conversation(session, session_token) is None:
            await ws.accept()
            await ws.close(code=4401, reason="Geçersiz veya süresi dolmuş oturum")
            return

    await ws_manager.connect_student(session_token, ws)
    try:
        # Heartbeat task
        async def heartbeat():
            while True:
                await asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL)
                try:
                    await ws.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300.0)
                frame = json.loads(raw)

                if frame.get("type") == "pong":
                    continue

                if frame.get("type") != "message":
                    continue

                user_content = frame.get("content", "").strip()
                if not user_content:
                    continue
                if len(user_content) > MAX_MESSAGE_LEN:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": f"Mesaj çok uzun (en fazla {MAX_MESSAGE_LEN} karakter).",
                    }, ensure_ascii=False))
                    continue

                response_data = await _process_message(session_token, user_content)
                await ws.send_text(json.dumps(response_data, ensure_ascii=False))

        except asyncio.TimeoutError:
            await ws.close(code=1001, reason="Zaman aşımı")
        finally:
            hb_task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS hatası (%s): %s", session_token[:8], exc, exc_info=True)
    finally:
        ws_manager.disconnect_student(session_token)


async def _process_message(session_token: str, user_content: str) -> dict:
    """Mesajı işle, yanıt döndür."""
    async with AsyncSessionLocal() as session:
        conv = await _get_conversation(session, session_token)
        if conv is None:
            raise HTTPException(401, "Geçersiz veya süresi dolmuş oturum.")
        await _append_message(session, conv, "user", user_content)

        # Intent tespiti
        intent_result = await detect_intent(user_content)

        # Intent kaydet
        from app.db.models.request_intent import RequestIntent
        intent_row = RequestIntent(
            conversation_id=conv.id,
            intent_type=intent_result.intent_type,
            confidence_score=intent_result.confidence,
            requires_email=intent_result.requires_email,
            raw_classifier_output=intent_result.raw_output,
        )
        session.add(intent_row)
        await session.commit()

        # Admin'e intent eventi gönder
        await ws_manager.broadcast_to_admins({
            "type": "intent_detected",
            "conversation_id": conv.id,
            "session_token_prefix": session_token[:8],
            "intent_type": intent_result.intent_type,
            "requires_email": intent_result.requires_email,
        })

        # Workflow
        result = await handle_message(
            session=session,
            conversation=conv,
            user_message=user_content,
            intent_type=intent_result.intent_type,
            requires_email=intent_result.requires_email,
        )

        # Asistan yanıtını kaydet
        await _append_message(session, conv, "assistant", result["response"])

        # Admin'e mesaj eventi gönder (anonim)
        await ws_manager.broadcast_to_admins({
            "type": "message",
            "conversation_id": conv.id,
            "session_token_prefix": session_token[:8],
            "role": "assistant",
            "content_preview": result["response"][:100],
            "state": result.get("state"),
        })

        return {
            "type": "message",
            "content": result["response"],
            "state": result.get("state"),
            "draft_id": result.get("draft_id"),
            **({"draft_preview": result["draft_preview"]} if "draft_preview" in result else {}),
        }


# ---- REST Fallback ---------------------------------------------------

class MessageRequest(BaseModel):
    # Uzunluk sınırları Pydantic seviyesinde: sınırsız gövde, kimlik
    # doğrulamasız bir uçtan LLM'i (300 sn timeout) meşgul etmenin en kolay yolu.
    session_token: str = Field(min_length=32, max_length=64)
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)


@router.post("/message")
async def send_message(req: MessageRequest):
    """REST fallback — WebSocket kullanamayan istemciler için."""
    içerik = req.content.strip()
    if not içerik:
        raise HTTPException(422, "Mesaj boş olamaz.")
    return await _process_message(req.session_token, içerik)


@router.get("/history/{session_token}")
async def get_history(session_token: str, db: AsyncSession = Depends(get_db)):
    """Konuşma geçmişi — yalnızca jetonu elinde tutan öğrenci için."""
    conv = await _get_conversation(db, session_token)
    if not conv:
        # Var olmayan ile erişilemeyen oturumu ayırt ETMİYORUZ: aksi hâlde
        # yanıt farkı, geçerli jetonları taramak için kullanılabilirdi.
        raise HTTPException(404, "Oturum bulunamadı.")
    try:
        mesajlar = json.loads(conv.messages_json)
    except Exception:
        logger.warning("Bozuk geçmiş (session=%s…)", session_token[:8])
        mesajlar = []
    return {"messages": mesajlar}


@router.delete("/session/{session_token}")
async def delete_session(session_token: str, db: AsyncSession = Depends(get_db)):
    """KVKK silme hakkı — öğrenci oturumunu sil."""
    conv = await _get_conversation(db, session_token)
    if not conv:
        raise HTTPException(404, "Oturum bulunamadı.")

    # KVKK: İçerikleri temizle
    conv.deleted_at = _now_utc()
    conv.messages_json = "[]"

    # Bağlantılı draft'lardaki PII'yi temizle
    from sqlalchemy import select as sa_select
    from app.db.models.email_draft import EmailDraft
    drafts_result = await db.execute(
        sa_select(EmailDraft).where(EmailDraft.conversation_id == conv.id)
    )
    for draft in drafts_result.scalars():
        draft.collected_fields_enc = None

    await db.commit()
    return {"detail": "Oturum silindi. Kurumsal e-posta kayıtları saklanmaya devam eder."}
