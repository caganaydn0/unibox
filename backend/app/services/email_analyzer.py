"""Email Analyzer — Gelen e-postayı RAG + LLM ile analiz edip yanıt üret

Mevcut RagEngine, detect_intent ve llm() bileşenlerini kullanır.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from datetime import datetime

from app.core.ws_manager import ws_manager
from app.db.models.incoming_email import IncomingEmail, IncomingEmailStatus
from app.db.models.system_settings import SystemMode
from app.db.session import AsyncSessionLocal
from app.services import system_settings_service
from app.services.intent_detector import detect_intent
from app.services.llm_provider import llm
from app.services.rag_engine import RagEngine
from app.services.rag_query import build_query

logger = logging.getLogger(__name__)


def _fix_json_control_chars(s: str) -> str:
    """JSON string değerleri içindeki kaçırılmamış kontrol karakterlerini düzeltir.
    LLM'ler bazen JSON body alanına literal newline koyar; bu json.loads'u bozar.
    """
    result: list[str] = []
    in_string = False
    skip_next = False
    for c in s:
        if skip_next:
            result.append(c)
            skip_next = False
            continue
        if c == "\\" and in_string:
            result.append(c)
            skip_next = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            else:
                result.append(c)
        else:
            result.append(c)
    return "".join(result)

REPLY_SYSTEM_PROMPT = """Sen bir üniversitenin resmi e-posta yanıt asistanısın.
Görevin: Sana verilen YÖNETMELİK BİLGİSİ'ni okuyup öğrencinin sorusuna DOĞRUDAN ve SOMUT yanıt vermek.

KURALLAR:
1. Yanıtı Türkçe yaz, resmi ve nazik bir dil kullan.
2. Sana verilen TÜM mevzuat maddelerini dikkatlice tara ve soruyla bağlantılı kısımları bul.
3. Bulduğun maddeleri aktarırken hangi yönetmelikten geldiğini belirt (örn: "Transkript Yönetmeliği Madde 5'e göre..."). Kaynak adını [Kaynak N — belge_adı] etiketinden çıkar; öğrenciye `[Kaynak N]`, `dosya.pdf` gibi teknik etiket veya dosya uzantısı GÖSTERME.
4. Mevzuatta ilgili bilgi varsa MUTLAKA onu kullan ve somut olarak aktar. Genel yönlendirme yapma.
   Madde numarası atıfını YALNIZCA sana verilen metinde gerçekten "MADDE N" ibaresi geçiyorsa yap.
   Metinde madde numarası yoksa belge adıyla atıf yap ("Transkript Belgesi Rehberi'ne göre...").
   ASLA madde numarası UYDURMA.
5. RAG bağlamında BULUNMAYAN hiçbir bilgiyi yazma: ücret, tutar, tarih, süre, kontenjan,
   telefon, prosedür adımı, sistem menüsü. Bu tür bir bilgi sorulmuş ama metinde yoksa
   uydurmak yerine 6. kuraldaki cümleyi yaz.
6. Sana hiç mevzuat verilmediyse, verilen metin soruyla ilgisizse veya soruya net bir cevap
   bulunamadıysa SADECE şunu yaz: "Daha detaylı bilgi için öğrenci işlerine danışınız."
   Bu durumda tahmin yürütme, olasılık belirtme, örnek değer verme.
7. Kişisel bilgi (TCKN, öğrenci numarası) isteme veya paylaşma.
8. Yanıtı JSON olarak döndür: {{"subject": "Re: ...", "body": "..."}}
9. body selamlaması: Öğrencinin adı verilmişse DOĞRUDAN o isimle başla (örn: "Sayın Ahmet Yılmaz,"). İsim yoksa "Sayın Öğrenci," yaz. ASLA "[isim]", "[İsim]", "[ad]" gibi köşeli parantezli yer tutucular veya {{name}} gibi şablon değişkenleri kullanma.
10. body kapanışı: "Saygılarımızla,\\nÖğrenci İşleri" ile bitir.
11. body en az 3 anlamlı cümle içersin; sadece selamlama/kapanış yazma.
12. Yanıt body'sine KESİNLİKLE şunları YAZMA: "Konu:", "Gönderen:", "Talep tipi:", "YÖNETMELİK BİLGİSİ", "rag_context" — bunlar sistem meta verisidir, yanıt metnine dahil edilemez.

İLGİLİ MEVZUAT:
{rag_context}

ÖNEMLİ: Mevzuat bilgisi varsa öğrenciyi başka yere yönlendirmek yerine o bilgiyi kullan ve açıkla.
Yukarıdaki "İLGİLİ MEVZUAT" bölümü BOŞ ise veya soruyla ilgisizse, hiçbir şey uydurma —
yalnızca "Daha detaylı bilgi için öğrenci işlerine danışınız." yaz."""


_PLACEHOLDER_NAME_PATTERNS = [
    r"\[\s*isim\s*\]",
    r"\[\s*İsim\s*\]",
    r"\[\s*ad\s*\]",
    r"\[\s*Ad\s*\]",
    r"\[\s*adı\s*\]",
    r"\[\s*öğrenci\s*(?:adı|ad)\s*\]",
    r"\[\s*Öğrenci\s*(?:Adı|Ad)\s*\]",
    r"\[\s*name\s*\]",
    r"\{\s*name\s*\}",
    r"\{\{\s*name\s*\}\}",
    r"\{\s*isim\s*\}",
]


def _replace_name_placeholders(body: str, sender_name: str | None) -> str:
    """LLM yer tutucu bıraktıysa (Sayın [isim] vb.) gerçek isimle değiştir.
    sender_name yoksa 'Öğrenci' kullan.
    """
    import re

    replacement = (sender_name or "").strip() or "Öğrenci"
    for pattern in _PLACEHOLDER_NAME_PATTERNS:
        body = re.sub(pattern, replacement, body, flags=re.IGNORECASE)
    return body


def _sanitize_reply_body(body: str, sender_name: str | None) -> str:
    """LLM çıktısındaki tutarsızlıkları temizle:
    1. JSON kaçakları ({"subject":..., "body": ... "}) — küçük modeller bazen
       tüm JSON'u body alanına da yerleştiriyor
    2. Teknik kaynak etiketleri ([Kaynak N — dosya.pdf]) — prompt'a rağmen
       çıktıya sızabiliyor
    3. Placeholder isim kalıpları ([isim] vb.)
    4. Greeting'i sender_name ile güvenceye al — llama3.1:8b prompt talimatını
       tutarsız uyguladığı için "Sayın Öğrenci" yerine gerçek ismi zorla koy
    """
    import re

    text = body or ""

    # 1. JSON kaçağı — body başında veya sonunda JSON anahtarı fragmanı
    text = re.sub(r'^\s*\{\s*"subject"\s*:\s*"[^"]*"\s*,\s*"body"\s*:\s*"?', "", text)
    # Model bazen gövdeyi rastgele bir anahtarın altına sarıyor
    # (ölçüldü: '{ "Sayın Test Öğrenci,": "Bu yılki taban puanı ...').
    # Baştaki { ve ilk "anahtar": kalıbını kırp.
    text = re.sub(r'^\s*\{\s*"[^"]{1,80}"\s*:\s*"?', "", text)
    text = re.sub(r'"\s*\}\s*$', "", text.rstrip())

    # 2a. Teknik kaynak etiketleri — "[Kaynak N — dosya.pdf]" / "[Kaynak N]"
    text = re.sub(r"\s*\[Kaynak\s*(?:\d+|N)(?:\s*[—–-]\s*[^\]]+)?\]\s*", " ", text)

    # 2b. Sistem terimleri — LLM'nin body'ye sızdırdığı metadata etiketleri
    text = re.sub(r"\bYÖNETMEL[İI]K\s+B[İI]LG[İI]S[İI]\b\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\brag_context\b\s*", "", text, flags=re.IGNORECASE)

    # 2c. Prompt'tan kopyalanan metadata satırları — LLM küçük modeller bu satırları
    # body'ye dahil edebilir; her birini satır bazında temizle
    _META_LINE_RE = re.compile(
        r"^\s*(?:Konu|Gönderen|Talep\s*tipi|E-posta\s*içeri[gğ]i|Subject|From|Intent)\s*:\s*.*$",
        re.IGNORECASE | re.MULTILINE,
    )
    text = _META_LINE_RE.sub("", text)
    # Temizleme sonrası üst üste boş satırları 1'e indir
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 3. Placeholder isimleri
    text = _replace_name_placeholders(text, sender_name)

    # 4. Greeting'i sender_name ile zorla
    name = (sender_name or "").strip() or "Öğrenci"
    expected_greeting = f"Sayın {name},"
    lines = text.lstrip().splitlines()
    # Baştaki boş satırları atla
    first_idx = 0
    while first_idx < len(lines) and not lines[first_idx].strip():
        first_idx += 1
    if first_idx < len(lines):
        first = lines[first_idx]
        # "Sayın <ad>,?" prefix'ini yakala; virgülden sonra içerik varsa onu koru
        m = re.match(
            r"^\s*Sayın\s+[^,\n]{1,60},?\s*(.*)$",
            first,
            flags=re.IGNORECASE,
        )
        if m:
            rest = m.group(1).strip()
            if rest:
                # Greeting + aynı satırda kalan içerik → iki satıra böl
                lines[first_idx:first_idx + 1] = [expected_greeting, rest]
            else:
                lines[first_idx] = expected_greeting
        else:
            # Greeting yoksa başa ekle
            lines.insert(first_idx, expected_greeting)
    else:
        lines = [expected_greeting]

    # Fazla ardışık boş satırları 1'e indir
    out: list[str] = []
    for ln in lines:
        if not ln.strip() and out and not out[-1].strip():
            continue
        out.append(ln)
    return "\n".join(out).strip()


class EmailAnalyzer:
    """Gelen öğrenci e-postalarını RAG + LLM ile analiz eder."""

    def __init__(self) -> None:
        self._rag = RagEngine()

    async def analyze(self, incoming_email_id: str) -> None:
        """Tam analiz pipeline'ı: intent tespit → RAG → LLM yanıt üretimi."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(IncomingEmail).where(IncomingEmail.id == incoming_email_id)
            )
            ie: IncomingEmail | None = result.scalar_one_or_none()

            if not ie:
                logger.error("IncomingEmail bulunamadı: %s", incoming_email_id)
                return

            if ie.status != IncomingEmailStatus.RECEIVED:
                logger.warning(
                    "IncomingEmail %s analiz için uygun değil (status=%s)",
                    incoming_email_id, ie.status,
                )
                return

            # RECEIVED → ANALYZING
            ie.status = IncomingEmailStatus.ANALYZING
            await session.commit()

            try:
                # 1. Intent tespiti
                email_content = ie.body_text or ie.subject or ""
                intent_result = await detect_intent(email_content)
                ie.intent_type = intent_result.intent_type
                ie.intent_confidence = intent_result.confidence

                # 2. RAG
                #
                # Eskiden sorgu `f"{subject} {body}"` idi ve intent=None
                # geçiliyordu. İki sorun vardı:
                #
                #  a) Selamlama, imza ve alıntılanmış thread dahil TÜM gövde
                #     embedding'e giriyordu. Uzun bir e-postanın vektörü çok
                #     konulu bir ağırlık merkezine dönüşüp hiçbir şeye iyi
                #     eşleşmiyordu. Aynı metin tam metin aramasına da gidiyor,
                #     yüzlerce lexeme OR'lanınca ts_rank gürültüye dönüşüyordu.
                #
                #  b) intent=None: ":235'teki eski yorum intent'in FİLTRE
                #     olduğu dönemden kalma. Artık bonus semantiği var ve
                #     None geçmek sıralama sinyalini çöpe atmak demek.
                #     Güvene bağlı geçiriyoruz: LLM sınıflandırıcısı
                #     yanılabilir ve yanlış intent etiketli chunk'ları
                #     haksız yere öne çeker.
                spec = build_query(
                    raw_text=email_content,
                    subject=ie.subject,
                    intent_type=ie.intent_type,
                    intent_confidence=ie.intent_confidence,
                )
                rag_context = await self._rag.query_spec(spec)
                rag_source_count = rag_context.count("[Kaynak") if rag_context else 0
                ie.rag_context_preview = (rag_context[:1000] + "...") if rag_context and len(rag_context) > 1000 else rag_context
                ie.rag_source_count = rag_source_count

                # 3. LLM ile yanıt üret
                reply_subject, reply_body = await self._generate_reply(
                    email_body=email_content,
                    email_subject=ie.subject,
                    intent_type=intent_result.intent_type,
                    rag_context=rag_context or "Yönetmelik bilgisi bulunamadı.",
                    sender_name=ie.sender_name,
                )

                ie.reply_subject = reply_subject
                ie.reply_body = reply_body

                mode = await system_settings_service.get_mode(session)

                if mode == SystemMode.PILOT:
                    # Pilot Modu: insan onayı olmadan direkt gönderim kuyruğuna
                    ie.status = IncomingEmailStatus.APPROVED
                    ie.auto_approved = True
                    ie.reviewed_by = None
                    ie.reviewed_at = datetime.utcnow()
                    await session.commit()

                    logger.info(
                        "Email analiz tamamlandı (Pilot Modu — otomatik onay): id=%s, intent=%s, confidence=%.2f",
                        incoming_email_id, intent_result.intent_type, intent_result.confidence,
                    )

                    from app.tasks.queue import incoming_reply_queue
                    await incoming_reply_queue.put(incoming_email_id)

                    await ws_manager.broadcast_to_admins({
                        "type": "incoming_email_auto_replied",
                        "id": incoming_email_id,
                        "subject": ie.subject,
                        "intent_type": ie.intent_type,
                        "reply_subject": ie.reply_subject,
                    })
                else:
                    # Co-Pilot Modu: admin incelemesi bekler
                    ie.status = IncomingEmailStatus.PENDING_REVIEW
                    await session.commit()

                    logger.info(
                        "Email analiz tamamlandı: id=%s, intent=%s, confidence=%.2f",
                        incoming_email_id, intent_result.intent_type, intent_result.confidence,
                    )

                    await ws_manager.broadcast_to_admins({
                        "type": "incoming_reply_ready",
                        "id": incoming_email_id,
                        "subject": ie.subject,
                        "intent_type": ie.intent_type,
                        "reply_subject": ie.reply_subject,
                    })

            except Exception as exc:
                logger.error(
                    "Email analiz hatası (id=%s): %s",
                    incoming_email_id, exc, exc_info=True,
                )
                ie.status = IncomingEmailStatus.ANALYSIS_FAILED
                ie.last_error = str(exc)
                await session.commit()

                await ws_manager.broadcast_to_admins({
                    "type": "incoming_analysis_failed",
                    "id": incoming_email_id,
                    "error": str(exc),
                })

    async def _generate_reply(
        self,
        email_body: str,
        email_subject: str | None,
        intent_type: str,
        rag_context: str,
        sender_name: str | None,
    ) -> tuple[str, str]:
        """LLM ile yanıt subject ve body üret."""
        system = REPLY_SYSTEM_PROMPT.format(rag_context=rag_context)

        greeting_name = (sender_name or "").strip() or "Öğrenci"
        user_prompt = f"""Aşağıdaki öğrenci e-postasına resmi yanıt oluştur. Yanıt, "Sayın {greeting_name}," ile başlamalıdır.

{email_body}"""

        raw = await llm().generate(user_prompt, system=system, format="json")
        logger.debug("LLM raw (len=%d, intent=%s): %s", len(raw), intent_type, raw[:2000])

        try:
            # JSON parse — LLM çeşitli formatlarda dönebilir
            clean = raw.strip()
            # Markdown code block temizle
            if "```" in clean:
                if "```json" in clean:
                    clean = clean.split("```json", 1)[1]
                    clean = clean.split("```", 1)[0]
                elif clean.count("```") >= 2:
                    clean = clean.split("```")[1]
            clean = clean.strip()
            # İlk { ... } bloğunu bul
            brace_start = clean.find('{')
            brace_end = clean.rfind('}')
            if brace_start != -1 and brace_end > brace_start:
                clean = clean[brace_start:brace_end + 1]
            # JSON string içindeki kaçırılmamış kontrol karakterlerini düzelt
            clean = _fix_json_control_chars(clean)
            reply_data = json.loads(clean)
            subject = reply_data.get("subject", f"Re: {email_subject or 'Yanıt'}")
            body = reply_data.get("body", raw)
        except Exception as exc:
            logger.warning(
                "Yanıt JSON'u parse edilemedi (%s) — ham çıktı gövde olarak kullanılıyor. Ham: %.200s",
                exc, raw,
            )
            subject = f"Re: {email_subject or 'Yanıt'}"
            body = raw

        # Küçük modellerin tutarsızlıklarını temizle: JSON kaçağı, teknik etiket,
        # placeholder isim, greeting'i sender_name ile zorla
        pre_sanitize_len = len(body)
        body = _sanitize_reply_body(body, sender_name)
        logger.debug(
            "LLM post-sanitize (pre=%d, post=%d): %s",
            pre_sanitize_len, len(body), body[:500],
        )

        return subject, body
