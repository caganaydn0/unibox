"""KVKK Anonymizer — PII Maskeleme

Bu modül, veritabanına yazılmadan önce tüm metin içeriğindeki
kişisel verileri maskeler. Yazım anında çağrılır, sonradan temizleme yapılmaz.

Maskelenen örüntüler:
- TCKN (11 haneli Türk kimlik numarası)
- Türk telefon numaraları
- E-posta adresleri (serbest metindeki)
- Ad/soyad (basit heuristik)
"""
import re

# ---- Regex desenleri --------------------------------------------------------

# TCKN: 11 haneli, birinci rakam 1-9
_TCKN_RE = re.compile(r"\b([1-9][0-9]{10})\b")

# Türk telefon numaraları: +90/0 ile başlayan, çeşitli formatlar
_PHONE_RE = re.compile(
    r"\b(\+90|0)[\s\-\.]?[0-9]{3}[\s\-\.]?[0-9]{3}[\s\-\.]?[0-9]{2}[\s\-\.]?[0-9]{2}\b"
)

# E-posta adresleri
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Ad/soyad heuristik: 2-3 ardışık baş harfli Türkçe kelime
# (False positive olabilir ama KVKK için güvenli taraf seçildi)
_NAME_RE = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]{2,}(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]{2,}){1,2})\b"
)

# Maskeleme etiketleri
_MASKS = {
    "tckn": "[TCKN_MASKED]",
    "phone": "[TEL_MASKED]",
    "email": "[EMAIL_MASKED]",
    "name": "[AD_SOYAD_MASKED]",
}


def mask_pii(text: str) -> str:
    """Metindeki tüm PII örüntülerini maskeler.

    Sıra önemlidir: önce spesifik (TCKN, tel, email) sonra genel (ad/soyad).
    """
    if not text:
        return text
    text = _TCKN_RE.sub(_MASKS["tckn"], text)
    text = _PHONE_RE.sub(_MASKS["phone"], text)
    text = _EMAIL_RE.sub(_MASKS["email"], text)
    text = _NAME_RE.sub(_MASKS["name"], text)
    return text


def mask_body_for_log(body: str) -> str:
    """E-posta gövdesini log için maskeler.

    email_logs.body_anonymized kolonuna yazılmadan önce çağrılır.
    """
    return mask_pii(body)


def has_pii(text: str) -> bool:
    """Metinde PII olup olmadığını kontrol eder (test/debug için)."""
    return bool(
        _TCKN_RE.search(text)
        or _PHONE_RE.search(text)
        or _EMAIL_RE.search(text)
        or _NAME_RE.search(text)
    )
