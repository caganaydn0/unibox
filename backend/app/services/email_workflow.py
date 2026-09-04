"""Email Workflow — State Machine

Bu modül, e-posta onay akışının tüm durum geçişlerini ve yan etkilerini yönetir.
Diğer servisler doğrudan EmailDraft.status'unu değiştirmemeli;
tüm geçişler bu modül üzerinden yapılmalıdır.

Durum geçişleri:
IDLE → COLLECTING_INFO → DRAFT_CREATED → PENDING_APPROVAL
→ APPROVED → SENT / FAILED
→ REJECTED (terminal)
→ CANCELLED (terminal, herhangi bir erken aşamadan)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ws_manager import ws_manager
from app.db.models.email_draft import EmailDraft, EmailDraftStatus, VALID_TRANSITIONS
from app.db.models.conversation import Conversation
from app.services.anonymizer import sanitize_draft_body
from app.services.llm_provider import llm
from app.services.rag_engine import RagEngine
from app.services.rag_query import build_query

logger = logging.getLogger(__name__)

# Taslak üretiminde LLM'e verilecek RAG bağlamının üst sınırı (karakter).
# Yerel donanımda uzun bağlam üretim süresini doğrusaldan hızlı büyütüyor.
DRAFT_CONTEXT_MAX_CHARS = 2500

# Bir öğrenciden toplanması gereken alanlar (intent tipine göre)
REQUIRED_FIELDS: dict[str, list[str]] = {
    "transcript_request": ["academic_year", "semester", "language"],
    "certificate_request": ["document_type", "purpose"],
    "enrollment_letter": ["purpose", "language"],
    "leave_of_absence": ["reason", "duration"],
    "grade_objection": ["course_code", "exam_type", "objection_reason"],
    "complaint": ["subject", "description"],
}

# Departman → e-posta eşleştirmesi (okul konfigürasyonuna göre güncellenir)
DEPARTMENT_EMAILS: dict[str, str] = {
    "ogrenci_isleri": "ometinbora@gmail.com",
}

# Intent → hedef departman
INTENT_DEPARTMENT: dict[str, str] = {
    "transcript_request": "ogrenci_isleri",
    "certificate_request": "ogrenci_isleri",
    "enrollment_letter": "ogrenci_isleri",
    "leave_of_absence": "ogrenci_isleri",
    "grade_objection": "ogrenci_isleri",
    "complaint": "ogrenci_isleri",
}

# Sistem promptları — her durum için ayrı (plan notuna göre)
SYSTEM_PROMPTS: dict[str, str] = {
    "collecting_info": """Sen bir üniversite asistanısın. Öğrencinin resmi talebini işlemek için
eksik bilgileri nazikçe soruyorsun. Tek seferde en fazla 1-2 soru sor.
Kişisel kimlik bilgisi (TCKN, öğrenci numarası) isteme.
Toplanacak alanlar: {required_fields}
Şimdiye kadar toplanan: {collected_fields}
Eksik olanları sor.""",

    "draft_created": """Sen bir üniversite asistanısın. Aşağıdaki e-posta taslağını
öğrenciye Türkçe olarak göster ve onay iste.
Taslak:
Konu: {subject}
İçerik: {body}

Öğrenciye bu taslağı gönderip göndermeyeceğini sor.""",

    # DİKKAT: Bu prompt uzun süre uydurma-karşıtı hiçbir kural içermiyordu.
    # Gelen e-posta yolunda (email_analyzer.REPLY_SYSTEM_PROMPT) titizlikle
    # kurulmuş savunma burada YOKTU ve sohbet yolu serbestçe uyduruyordu —
    # uçtan uca testte "doktora yeterlik şartları" sorusuna, mevzuatta hiç
    # geçmeyen 8 maddelik bir liste üretti.
    #
    # config.py'deki kalibrasyon notu "asıl savunma hattı eşik değil, prompt"
    # diyor; o tespit doğru ama prompt iki yoldan yalnızca birinde vardı.
    "general": """Sen UniBox, bir üniversite AI asistanısın.
Öğrencilere üniversite süreçleri ve yönetmelikler konusunda yardım ediyorsun.
Kısa, net ve kibar yanıtlar ver. Türkçe konuş.

KURALLAR:
1. YALNIZCA sana "İlgili bilgi" başlığı altında verilen metne dayanarak cevap ver.
2. O metinde BULUNMAYAN hiçbir şeyi yazma: ücret, tutar, tarih, süre, kontenjan,
   not ortalaması, telefon, prosedür adımı, sistem menüsü, madde numarası.
   Genel bilginden veya başka üniversitelerin uygulamasından cevap ÜRETME.
3. Madde numarası atıfını yalnızca verilen metinde gerçekten "MADDE N" ibaresi
   geçiyorsa yap. ASLA madde numarası uydurma.
4. Sana hiç bilgi verilmediyse, verilen bilgi soruyla ilgisizse veya soruya net
   cevap bulunamadıysa şunu yaz: "Bu konuda elimde kesin bilgi yok. Daha detaylı
   bilgi için öğrenci işlerine danışabilirsiniz." Tahmin yürütme, olasılık
   belirtme, örnek değer verme.
5. Kişisel bilgi (TCKN, öğrenci numarası) isteme veya paylaşma.""",
}

# Bağlam bulunamadığında prompt'a eklenen not. Boş bırakmak, modelin
# "bilgi verilmedi" durumunu fark etmemesine ve serbestçe uydurmasına yol
# açıyordu.
GENERAL_NO_CONTEXT = (
    "\n\nİlgili bilgi: (bilgi tabanında bu soruyla ilgili kayıt BULUNAMADI)\n"
    "4. kuraldaki cümleyi yaz; kendi genel bilginden cevap üretme."
)


def _encrypt_fields(data: dict) -> str:
    """Toplanan alanları Fernet ile şifrele."""
    from cryptography.fernet import Fernet
    from app.config import settings

    f = Fernet(settings.FERNET_KEY.encode())
    return f.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()


def _decrypt_fields(enc: str) -> dict:
    """Fernet şifreli alanları çöz."""
    from cryptography.fernet import Fernet
    from app.config import settings

    f = Fernet(settings.FERNET_KEY.encode())
    return json.loads(f.decrypt(enc.encode()).decode())


async def _transition(
    draft: EmailDraft,
    new_status: EmailDraftStatus,
    session: AsyncSession,
    **extra_fields: Any,
) -> None:
    """Durum geçişini doğrula ve uygula."""
    current = draft.status
    allowed = VALID_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise ValueError(
            f"Geçersiz geçiş: {current} → {new_status}. "
            f"İzin verilenler: {allowed}"
        )
    draft.status = new_status
    for key, value in extra_fields.items():
        setattr(draft, key, value)
    await session.commit()
    logger.info("Draft %s: %s → %s", draft.id, current, new_status)


async def handle_message(
    session: AsyncSession,
    conversation: Conversation,
    user_message: str,
    intent_type: str,
    requires_email: bool,
) -> dict[str, Any]:
    """
    Bir öğrenci mesajını işle, state machine'i ilerlet, yanıt döndür.

    Returns:
        {
            "response": str,         # Asistan yanıtı (kullanıcıya gösterilecek)
            "state": str,            # Yeni EmailDraftStatus (veya "IDLE")
            "draft_id": str | None,  # Varsa aktif draft ID'si
        }
    """
    # Aktif draft var mı?
    result = await session.execute(
        select(EmailDraft).where(
            EmailDraft.conversation_id == conversation.id,
            EmailDraft.status.notin_([
                EmailDraftStatus.SENT,
                EmailDraftStatus.REJECTED,
                EmailDraftStatus.CANCELLED,
                EmailDraftStatus.FAILED,
            ]),
        )
    )
    draft: EmailDraft | None = result.scalar_one_or_none()

    # --- Durum: Aktif draft yok, yeni intent değerlendirmesi ---
    if draft is None:
        if not requires_email:
            # Genel soru — RAG ile yanıtla
            rag = RagEngine()
            rag_context = await rag.query_spec(
                build_query(raw_text=user_message, intent_type=intent_type)
            )
            system = SYSTEM_PROMPTS["general"]
            if rag_context:
                system += f"\n\nİlgili bilgi:\n{rag_context}"
            else:
                # Bağlam yokken sessiz kalmak, modelin durumu fark etmemesine
                # ve genel bilgisinden cevap uydurmasına yol açıyordu.
                system += GENERAL_NO_CONTEXT
            response = await llm().generate(user_message, system=system)
            return {"response": response, "state": "IDLE", "draft_id": None}

        # E-posta gerektiren yeni intent — COLLECTING_INFO başlat
        draft = EmailDraft(
            conversation_id=conversation.id,
            intent_type=intent_type,
            status=EmailDraftStatus.COLLECTING_INFO,
            collected_fields_enc=_encrypt_fields({}),
            recipient_department=INTENT_DEPARTMENT.get(intent_type),
            recipient_email=DEPARTMENT_EMAILS.get(
                INTENT_DEPARTMENT.get(intent_type, ""), None
            ),
        )
        session.add(draft)
        await session.commit()

        # İlk soruyu sor
        response = await _ask_next_field(draft, user_message)
        await ws_manager.broadcast_to_admins({
            "type": "draft_created",
            "draft_id": draft.id,
            "conversation_id": conversation.id,
            "intent_type": intent_type,
            "status": EmailDraftStatus.COLLECTING_INFO,
        })
        return {"response": response, "state": EmailDraftStatus.COLLECTING_INFO, "draft_id": draft.id}

    # --- Durum: COLLECTING_INFO ---
    if draft.status == EmailDraftStatus.COLLECTING_INFO:
        return await _handle_collecting(session, draft, user_message)

    # --- Durum: DRAFT_CREATED (öğrenci onay/ret bekleniyor) ---
    if draft.status == EmailDraftStatus.DRAFT_CREATED:
        return await _handle_draft_review(session, draft, user_message)

    # Diğer durumlar (PENDING_APPROVAL, APPROVED vb.) — sadece bilgi ver
    return {
        "response": f"Talebiniz '{draft.status}' durumunda. Lütfen bekleyin.",
        "state": draft.status,
        "draft_id": draft.id,
    }


async def _ask_next_field(draft: EmailDraft, user_message: str) -> str:
    """Bir sonraki eksik alanı soran LLM yanıtı üret."""
    collected = _decrypt_fields(draft.collected_fields_enc) if draft.collected_fields_enc else {}
    required = REQUIRED_FIELDS.get(draft.intent_type, [])
    missing = [f for f in required if f not in collected]

    if not missing:
        return "Tüm bilgiler toplandı."

    system = SYSTEM_PROMPTS["collecting_info"].format(
        required_fields=", ".join(required),
        collected_fields=json.dumps(collected, ensure_ascii=False),
    )
    return await llm().generate(user_message, system=system)


async def _handle_collecting(
    session: AsyncSession, draft: EmailDraft, user_message: str
) -> dict[str, Any]:
    """COLLECTING_INFO durumunda öğrenci mesajını işle."""
    # Mevcut toplanan alanları çöz
    collected = _decrypt_fields(draft.collected_fields_enc) if draft.collected_fields_enc else {}
    required = REQUIRED_FIELDS.get(draft.intent_type, [])

    # İptal kontrolü
    cancel_keywords = ["iptal", "vazgeç", "istemiyorum", "cancel"]
    if any(kw in user_message.lower() for kw in cancel_keywords):
        await _transition(draft, EmailDraftStatus.CANCELLED, session)
        return {
            "response": "Talebiniz iptal edildi. Başka bir konuda yardımcı olabilir miyim?",
            "state": EmailDraftStatus.CANCELLED,
            "draft_id": draft.id,
        }

    # LLM'den bilgi çıkar ve güncelle.
    #
    # Yalnızca HENÜZ TOPLANMAMIŞ alanları soruyoruz. Sebep: küçük modeller
    # aradıkları bilgiyi mesajda bulamayınca prompt'taki örneği birebir
    # kopyalıyor. Örnekte somut değer bulunursa ("semester": "bahar") bu değer
    # doğru toplanmış veriyi eziyordu. Bu yüzden hem somut örnek vermiyoruz,
    # hem de aşağıda yalnızca eksik alanları kabul ediyoruz.
    henüz_eksik = [f for f in required if f not in collected]
    extract_system = f"""Öğrenci mesajından bilgi çıkar ve JSON döndür.

Çıkarılacak alanlar: {", ".join(henüz_eksik)}

Kurallar:
- Yalnızca yukarıdaki alan adlarını anahtar olarak kullan.
- Bir alan öğrencinin mesajında geçmiyorsa o anahtarı hiç ekleme.
- Hiçbir alan bulamazsan boş JSON nesnesi döndür.
- Örnek değer uydurma; sadece mesajda geçen bilgiyi yaz."""

    raw_extract = await llm().generate(user_message, system=extract_system, format="json")
    try:
        clean = raw_extract.strip().strip("```json").strip("```")
        extracted = json.loads(clean)
        if not isinstance(extracted, dict):
            raise ValueError(f"dict bekleniyordu, {type(extracted).__name__} geldi")

        # Sadece eksik alanları kabul et. Zaten toplanmış bir alanı asla
        # ezmeyiz — model örnek kopyaladığında doğru veri bozulmasın.
        kabul = {k: v for k, v in extracted.items() if k in henüz_eksik and v}
        reddedilen = set(extracted) - set(kabul)
        if reddedilen:
            logger.info(
                "Draft %s: yok sayılan anahtarlar %s (eksik alanlar: %s)",
                draft.id, reddedilen, henüz_eksik,
            )
        collected.update(kabul)
    except Exception as exc:
        # Sessizce yutmak akışı görünmez şekilde kilitliyordu — en azından logla.
        logger.warning(
            "Draft %s: alan çıkarma başarısız (%s). Ham çıktı: %.200s",
            draft.id, exc, raw_extract,
        )

    # Güncelle
    draft.collected_fields_enc = _encrypt_fields(collected)
    await session.commit()

    missing = [f for f in required if f not in collected]

    if not missing:
        # Tüm alanlar tamam — taslak oluştur
        return await _generate_draft(session, draft, collected)
    else:
        # Devam et
        response = await _ask_next_field(draft, user_message)
        return {"response": response, "state": EmailDraftStatus.COLLECTING_INFO, "draft_id": draft.id}


async def _generate_draft(
    session: AsyncSession, draft: EmailDraft, collected: dict
) -> dict[str, Any]:
    """Toplanan alanlardan e-posta taslağı oluştur."""
    # RAG ile şablon çek.
    # Sorguyu intent'in Türkçe karşılığıyla kuruyoruz: "transcript_request"
    # gibi İngilizce anahtar Türkçe bir bilgi tabanında zayıf eşleşme veriyor.
    from app.services.intent_detector import INTENT_DESCRIPTIONS

    konu = INTENT_DESCRIPTIONS.get(draft.intent_type, draft.intent_type)
    rag = RagEngine()
    # Sorgu YALNIZCA intent'in Türkçe karşılığı olamaz: o 6 sabit dizeden
    # biri olduğu için her transkript talebi HEP AYNI chunk'ları getiriyordu.
    # Öğrencinin verdiği somut bilgiler (dönem, ders, dil) sorguya girmeli.
    #
    # KVKK: collected çözülmüş alanları içeriyor. LLM'e zaten gidiyor ve her
    # şey kurum içinde, ama sorgu ham hâliyle INFO seviyesinde LOGLANMAMALI.
    toplanan_metin = " ".join(str(d) for d in collected.values() if d)
    rag_context = await rag.query_spec(
        build_query(
            raw_text=toplanan_metin or konu,
            subject=konu,
            intent_type=draft.intent_type,
        ),
        azami_karakter=DRAFT_CONTEXT_MAX_CHARS,
    )

    # NOT: Bağlam sınırı artık YUKARIDA, query_spec(azami_karakter=...) ile
    # uygulanıyor — chunk BÜTÜNLÜĞÜ korunarak. Eskiden burada
    # `rag_context[:2500]` vardı ve son maddeyi cümle ortasından kesip modele
    # yarım hüküm veriyordu. Belge sırasına dizmeden sonra "baştaki chunk en
    # alakalı" varsayımı da geçersizleştiği için körlemesine kesmek büsbütün
    # yanlış hâle geldi.
    #
    # Sınırın sebebi değişmedi: ölçüm sırasında sınırsız bağlam ~11.000
    # karaktere ulaşıyor ve 4 GB VRAM'e tam sığmayan bir modelde taslak
    # üretimi 300 sn'lik istemci zaman aşımını aşıyordu.

    draft_system = f"""Sen bir üniversite asistanısın. Aşağıdaki bilgilerle resmi bir e-posta taslağı oluştur.
E-posta, öğrencinin "{konu}" talebini ilgili birime ileten resmi bir başvuru yazısıdır.
Konu satırı ve e-posta gövdesi ayrı ayrı JSON olarak döndür.
Format: {{"subject": "...", "body": "..."}}

Toplanan bilgiler: {json.dumps(collected, ensure_ascii=False)}
İlgili yönetmelik bilgisi: {rag_context}

ZORUNLU KURALLAR:
- Yalnızca yukarıdaki "Toplanan bilgiler"i kullan. Başka bilgi İSTEME.
- TCKN, öğrenci numarası, ad-soyad, doğum tarihi YAZMA ve TALEP ETME.
- Köşeli parantezli yer tutucu ([Adınız] gibi) KULLANMA; bilgi eksikse o cümleyi hiç yazma.
- Aynı cümleyi tekrarlama."""

    raw = await llm().generate("E-posta taslağı oluştur", system=draft_system, format="json")
    try:
        clean = raw.strip().strip("```json").strip("```")
        draft_data = json.loads(clean)
        subject = draft_data.get("subject", f"{draft.intent_type} Talebi")
        body = draft_data.get("body", raw)
    except Exception as exc:
        logger.warning(
            "Draft %s: taslak JSON'u parse edilemedi (%s) — ham çıktı gövde olarak kullanılıyor.",
            draft.id, exc,
        )
        subject = f"{draft.intent_type.replace('_', ' ').title()} Talebi"
        body = raw

    # KVKK güvenlik ağı: prompt'taki yasağa rağmen model TCKN / ad-soyad
    # isteyen satırlar üretebiliyor. Prompt'a güvenmiyoruz, çıktıyı da
    # deterministik olarak temizliyoruz.
    temiz_body = sanitize_draft_body(body)
    if temiz_body != body:
        logger.info("Draft %s: gövde temizlendi (%d -> %d karakter).",
                    draft.id, len(body), len(temiz_body))
    body = temiz_body
    subject = sanitize_draft_body(subject).replace("\n", " ").strip()

    # Taslağa yaz
    draft.subject = subject
    draft.body = body
    await _transition(draft, EmailDraftStatus.DRAFT_CREATED, session)

    # Öğrenciye önizleme göster
    preview_system = SYSTEM_PROMPTS["draft_created"].format(
        subject=subject, body=body
    )
    response = await llm().generate("Taslağı göster", system=preview_system)

    return {
        "response": response,
        "state": EmailDraftStatus.DRAFT_CREATED,
        "draft_id": draft.id,
        "draft_preview": {"subject": subject, "body": body},
    }


async def _handle_draft_review(
    session: AsyncSession, draft: EmailDraft, user_message: str
) -> dict[str, Any]:
    """DRAFT_CREATED durumunda öğrenci onay/ret mesajını işle."""
    approve_keywords = ["evet", "tamam", "gönder", "onaylıyorum", "ok", "uygun"]
    cancel_keywords = ["hayır", "iptal", "değiştir", "istemiyorum", "vazgeç"]

    msg_lower = user_message.lower()

    if any(kw in msg_lower for kw in approve_keywords):
        await _transition(draft, EmailDraftStatus.PENDING_APPROVAL, session)
        # Admin'e bildir
        await ws_manager.broadcast_to_admins({
            "type": "email_pending_approval",
            "draft_id": draft.id,
            "conversation_id": draft.conversation_id,
            "intent_type": draft.intent_type,
            "subject": draft.subject,
            "recipient_email": draft.recipient_email,
        })
        # Kuyruğa ekle — admin onaylayınca worker alacak
        # Not: email_queue'ya APPROVED sonrası eklenir, şimdi değil
        return {
            "response": "Talebiniz admin onayına gönderildi. En kısa sürede işleme alınacak.",
            "state": EmailDraftStatus.PENDING_APPROVAL,
            "draft_id": draft.id,
        }
    elif any(kw in msg_lower for kw in cancel_keywords):
        await _transition(draft, EmailDraftStatus.CANCELLED, session)
        return {
            "response": "Taslak iptal edildi. Yeniden başlamak ister misiniz?",
            "state": EmailDraftStatus.CANCELLED,
            "draft_id": draft.id,
        }
    else:
        # Belirsiz yanıt — yeniden sor
        return {
            "response": "Taslağı göndermek istiyor musunuz? (Evet / Hayır)",
            "state": EmailDraftStatus.DRAFT_CREATED,
            "draft_id": draft.id,
        }


async def approve_draft(
    session: AsyncSession, draft: EmailDraft, admin_username: str
) -> None:
    """Admin onayı — PENDING_APPROVAL → APPROVED ve email kuyruğuna ekle."""
    await _transition(
        draft,
        EmailDraftStatus.APPROVED,
        session,
        reviewed_by=admin_username,
        reviewed_at=datetime.utcnow(),
    )
    from app.tasks.queue import email_queue
    await email_queue.put(draft.id)
    logger.info("Draft %s onaylandı, kuyruğa eklendi.", draft.id)
    # Diğer admin sekmelerinin bekleyen taslak sayacını anında güncellemesi
    # için — eskiden bu event hiç yayınlanmıyordu, sayaç yalnızca sonraki
    # manuel yenilemede güncelleniyordu.
    await ws_manager.broadcast_to_admins({
        "type": "email_approved",
        "draft_id": draft.id,
        "conversation_id": draft.conversation_id,
    })


async def reject_draft(
    session: AsyncSession,
    draft: EmailDraft,
    admin_username: str,
    reason: str,
) -> None:
    """Admin reddi — PENDING_APPROVAL → REJECTED, collected_fields temizle."""
    await _transition(
        draft,
        EmailDraftStatus.REJECTED,
        session,
        reviewed_by=admin_username,
        reviewed_at=datetime.utcnow(),
        rejection_reason=reason,
        # KVKK: REJECTED sonrası PII temizle
        collected_fields_enc=None,
    )
    # Öğrenciye bildir
    await ws_manager.send_to_student(
        draft.conversation_id,  # conversation_id == session_token bağlantısı chat.py'de
        {"type": "draft_rejected", "reason": reason},
    )
    # Diğer admin sekmelerinin bekleyen taslak sayacını anında güncellemesi
    # için — eskiden bu event hiç yayınlanmıyordu, sayaç yalnızca sonraki
    # manuel yenilemede güncelleniyordu.
    await ws_manager.broadcast_to_admins({
        "type": "email_rejected",
        "draft_id": draft.id,
        "conversation_id": draft.conversation_id,
        "reason": reason,
    })
