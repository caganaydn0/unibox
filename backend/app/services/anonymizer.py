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


# ---- Giden taslak temizliği -------------------------------------------------
#
# Sistem promptu "TCKN, ad-soyad isteme" dediği halde küçük modeller bu talimatı
# düzenli olarak çiğniyor ve e-posta gövdesine "T.C. Kimlik Numaranız:" gibi
# satırlar ekliyor. Prompt'a güvenmek KVKK açısından yeterli değil; çıktıyı
# deterministik olarak da temizliyoruz.

# PII talep eden satırları yakalayan terimler
_PII_TERIMLERI = (
    r"t\.?\s*c\.?\s*kimlik",
    r"tckn",
    r"kimlik\s*numara",
    r"öğrenci\s*numara",
    r"ogrenci\s*numara",
    r"ad(?:ınız)?\s*(?:ve)?\s*soyad",
    r"doğum\s*tarih",
)
_PII_TALEP_RE = re.compile(
    r"^.*(?:" + "|".join(_PII_TERIMLERI) + r").*$",
    re.IGNORECASE | re.MULTILINE,
)

# [Adınız Soyadınız], [İsim], [academic_year] gibi doldurulmamış yer tutucular
_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{1,60}\]")


def strip_pii_requests(text: str) -> str:
    """PII isteyen/paylaşan satırları tamamen kaldırır."""
    if not text:
        return text
    return _PII_TALEP_RE.sub("", text)


def strip_placeholders(text: str) -> str:
    """Doldurulmamış [yer tutucu] etiketlerini kaldırır.

    Satır yalnızca yer tutucudan ibaretse satırın tamamı gider; cümle içindeyse
    sadece etiket silinip cümle korunur.
    """
    if not text:
        return text
    satırlar = []
    for satır in text.splitlines():
        temiz = _PLACEHOLDER_RE.sub("", satır)
        # Etiket çıkınca geriye anlamlı bir şey kalmadıysa satırı at
        if _PLACEHOLDER_RE.search(satır) and len(temiz.strip(" -•\t:,.")) < 3:
            continue
        satırlar.append(temiz)
    return "\n".join(satırlar)


def dedupe_lines(text: str) -> str:
    """Aynı satırın tekrarını kaldırır (ilk geçtiği yer korunur).

    Küçük modeller aynı cümleyi gövdenin farklı yerlerinde tekrarlayabiliyor.
    Kısa satırlar (imza, selamlama, madde işareti) tekrar sayılmaz.
    """
    if not text:
        return text
    görülen: set[str] = set()
    çıktı: list[str] = []
    for satır in text.splitlines():
        anahtar = " ".join(satır.split()).lower()
        if len(anahtar) > 25:
            if anahtar in görülen:
                continue
            görülen.add(anahtar)
        çıktı.append(satır)
    return "\n".join(çıktı)


def drop_orphan_intros(text: str) -> str:
    """Altındaki maddeler silinmiş "giriş" satırlarını kaldırır.

    "Lütfen aşağıdaki bilgileri sağlayın:" satırı, altındaki TCKN/ad-soyad
    maddeleri temizlendikten sonra öksüz kalıyor ve okuyucuya eksik bir
    talep gibi görünüyor. İki nokta ile biten ve ardından madde gelmeyen
    satırları atıyoruz.
    """
    if not text:
        return text
    satırlar = text.splitlines()
    tut: list[str] = []
    for i, satır in enumerate(satırlar):
        if satır.rstrip().endswith(":"):
            sonraki = next((s for s in satırlar[i + 1:] if s.strip()), "")
            # Ardından madde işareti veya "Anahtar: değer" gelmiyorsa öksüzdür
            if not re.match(r"^\s*(?:[-•*]|\d+[.)]|\w[^:\n]{0,40}:)", sonraki):
                continue
        tut.append(satır)
    return "\n".join(tut)


def sanitize_draft_body(text: str) -> str:
    """Giden e-posta taslağı için tam temizlik zinciri."""
    text = strip_pii_requests(text)
    text = strip_placeholders(text)
    text = drop_orphan_intros(text)
    text = dedupe_lines(text)
    # Temizlik sonrası oluşan boşlukları toparla. Yer tutucu cümle ortasından
    # silindiğinde çift boşluk ve sarkan noktalama kalıyor ("lütfen  veya  ...").
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,;.!?])", r"\1", text)
    text = re.sub(r"([,;])\s*([,;.])", r"\2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
