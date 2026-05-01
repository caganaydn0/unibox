"""Chat API — WebSocket ve REST fallback

Öğrenci ↔ Bot iletişim katmanı.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from pydantic import BaseModel
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


def _now_utc() -> datetime:
    return datetime.utcnow()


async def _get_or_create_conversation(
    session: AsyncSession, session_token: str
) -> Conversation:
    """Session token'a göre konuşma getir veya oluştur."""
    result = await session.execute(
        select(Conversation).where(
            Conversation.session_token == session_token,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        now = _now_utc()
        conv = Conversation(
            session_token=session_token,
            started_at=now,
            last_active_at=now,
            retention_expires_at=now + timedelta(days=settings.CONVERSATION_RETENTION_DAYS),
        )
        session.add(conv)
        await session.commit()
    return conv


async def _append_message(
    session: AsyncSession, conv: Conversation, role: str, content: str
) -> None:
    """Konuşma geçmişine mesaj ekle (PII maskelenerek)."""
    messages: list[dict] = json.loads(conv.messages_json)
    messages.append({
        "role": role,
        # KVKK: PII yazım anında maskelenir
        "content": mask_pii(content),
        "ts": _now_utc().isoformat(),
    })
    # 64KB sanity cap
    conv.messages_json = json.dumps(messages, ensure_ascii=False)[:65536]
    conv.last_active_at = _now_utc()
    await session.commit()


# ---- WebSocket -------------------------------------------------------

@router.websocket("/ws/{session_token}")
async def chat_websocket(session_token: str, ws: WebSocket):
    """Öğrenci WebSocket bağlantısı.

    Frame formatları:
    → {"type": "message", "content": "..."}
    ← {"type": "message"|"state_change"|"draft_preview"|"error", ...}
    """
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
        conv = await _get_or_create_conversation(session, session_token)
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
    session_token: str
    content: str


@router.post("/message")
async def send_message(req: MessageRequest):
    """REST fallback — WebSocket kullanamayan istemciler için."""
    return await _process_message(req.session_token, req.content.strip())


@router.get("/history/{session_token}")
async def get_history(session_token: str, db: AsyncSession = Depends(get_db)):
    """Anonim konuşma geçmişi (öğrenci için)."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.session_token == session_token,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return {"messages": []}
    return {"messages": json.loads(conv.messages_json)}


@router.delete("/session/{session_token}")
async def delete_session(session_token: str, db: AsyncSession = Depends(get_db)):
    """KVKK silme hakkı — öğrenci oturumunu sil."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.session_token == session_token,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()
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
