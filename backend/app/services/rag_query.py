"""Geri getirim sorgusu oluşturma — tek, deterministik, LLM'siz.

SORUN: Sistemde dört ayrı sorgu stratejisi vardı ve ikisi açıkça yanlıştı:

  email_workflow:160  ham chat mesajı                       (kabul edilebilir)
  email_workflow:311  YALNIZCA intent'in Türkçe karşılığı   (yanlış)
  email_analyzer:237  TÜM e-posta gövdesi, intent=None      (yanlış)

İkinci durumda sorgu 6 sabit dizeden biri olduğu için her transkript talebi
için HEP AYNI chunk'lar geliyordu. Üçüncüsünde ise selamlama, imza ve
alıntılanmış thread dahil her şey embedding'e giriyor; uzun bir e-postanın
vektörü çok konulu bir ağırlık merkezine dönüşüyor ve hiçbir şeye iyi
eşleşmiyor. Aynı metin tam metin aramasına da gidiyor: yüzlerce lexeme
OR'lanınca neredeyse her chunk eşleşiyor ve ts_rank sıralaması gürültüye
dönüşüyor.

BURADA LLM KULLANILMIYOR. Sorguyu LLM'e yeniden yazdırmak +1 tur demek
(llama3.1:8b'de saniyeler) ve bu, kullanıcının BEKLEDİĞİ sohbet yolunda
kabul edilemez. Deterministik temizlik kazancın çoğunu ~0 ms'ye alıyor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Alıntılanmış thread başlangıçları. Gelen e-postalar yanıtlandıkça birikir
# ve alıntı, asıl talepten kat kat uzun olabilir.
_ALINTI_DESENLERI = [
    r"^-{2,}\s*Original Message\s*-{2,}",
    r"^_{5,}",
    r"^-{5,}",
    r"^From:\s",
    r"^Gönderen:\s",
    r"^Kimden:\s",
    r"^\s*\d{1,2}\s+\w+\s+\d{4}\s+.*(?:yazdı|wrote)\s*:",
    r"^On\s.+wrote:",
    r"^.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\byazdı\s*:",
]
_ALINTI_RE = re.compile("|".join(_ALINTI_DESENLERI), re.IGNORECASE | re.MULTILINE)

# İmza ayracı (RFC 3676): tek başına "-- " satırı
_IMZA_AYRACI_RE = re.compile(r"^--\s*$", re.MULTILINE)

# Kalıp selamlama ve kapanış — hiçbir bilgi taşımaz, her e-postada aynıdır
_KALIP_RE = re.compile(
    r"^\s*(?:"
    r"sayın[^\n]{0,60}|merhaba[^\n]{0,30}|iyi günler[^\n]{0,30}|"
    r"selam[^\n]{0,30}|dear\s+[^\n]{0,40}|"
    r"saygılar[^\n]{0,40}|saygılarımla[^\n]{0,20}|iyi çalışmalar[^\n]{0,30}|"
    r"teşekkür(?:ler)?[^\n]{0,40}|teşekkür ederim[^\n]{0,20}|"
    r"gereğini[^\n]{0,40}|bilgilerinize[^\n]{0,40}|"
    r"şimdiden teşekkür[^\n]{0,40}|best regards[^\n]{0,30}|kind regards[^\n]{0,30}"
    r")\s*[,.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# İmza bloğu satırları: telefon, e-posta, unvan, URL
_IMZA_SATIRI_RE = re.compile(
    r"^\s*(?:"
    r"(?:tel|gsm|cep|telefon|phone)\s*[:.]?\s*[+\d].*|"
    r"[\w.+-]+@[\w.-]+\.\w+\s*|"
    r"https?://\S+\s*|"
    r"(?:prof|doç|dr|arş\.?\s*gör|öğr\.?\s*gör)\.?\s.*"
    r")$",
    re.IGNORECASE | re.MULTILINE,
)

# Gövde üst sınırı. bge-m3 8192 token alabiliyor ama uzun metnin embedding'i
# çok konulu bir ağırlık merkezidir; talep neredeyse her zaman ilk paragrafta.
GOVDE_AZAMI = 1200

# Temizlik bu kadarın altına indiyse fazla agresif davranmışız demektir;
# ham metne dönüyoruz (öğrenci talebini alıntının ALTINA yazmış olabilir).
ASGARI_ANLAMLI = 80


@dataclass(frozen=True)
class QuerySpec:
    """Aramaya verilecek sorgular.

    `konu` ayrı tutuluyor: gövdeyle birleştirmek yerine İKİ AYRI arama
    çalıştırıp sonuçları zaten var olan RRF ile birleştiriyoruz. Konu
    satırını tekrarlayarak ağırlık vermekten daha ilkeli ve mevcut makineyi
    kullanıyor.
    """

    metin: str
    konu: str | None = None
    intent_type: str | None = None

    @property
    def sorgular(self) -> list[str]:
        çıktı = [self.metin]
        if self.konu and self.konu.strip() and self.konu.strip() not in self.metin:
            çıktı.append(self.konu.strip())
        return çıktı


def alintiyi_kirp(metin: str) -> str:
    """Alıntılanmış thread'i ve imza bloğunu keser."""
    if not metin:
        return ""

    # İlk alıntı işaretinden sonrasını at
    m = _ALINTI_RE.search(metin)
    if m:
        metin = metin[: m.start()]

    # RFC 3676 imza ayracı
    m = _IMZA_AYRACI_RE.search(metin)
    if m:
        metin = metin[: m.start()]

    # ">" ile başlayan alıntı satırları
    metin = "\n".join(s for s in metin.split("\n") if not s.lstrip().startswith(">"))
    return metin.strip()


def kalip_temizle(metin: str) -> str:
    """Selamlama, kapanış ve imza satırlarını kaldırır."""
    if not metin:
        return ""
    metin = _KALIP_RE.sub("", metin)
    metin = _IMZA_SATIRI_RE.sub("", metin)
    # Yalnız isimden ibaret kısa satırlar (imza kalıntısı)
    satırlar = [
        s for s in metin.split("\n")
        if not (0 < len(s.strip()) < 30 and s.strip().replace(" ", "").isalpha()
                and s.strip()[:1].isupper() and " " in s.strip() and "?" not in s)
    ]
    metin = "\n".join(satırlar)
    return re.sub(r"\n{2,}", "\n", metin).strip()


def build_query(
    *,
    raw_text: str,
    subject: str | None = None,
    intent_type: str | None = None,
    intent_confidence: float | None = None,
) -> QuerySpec:
    """Ham kullanıcı metninden arama sorgusu üretir.

    intent_confidence verilmişse intent YALNIZCA yeterince güvenilirken
    geçirilir. Gelen e-postada intent bir LLM sınıflandırıcısından geliyor ve
    yanılabilir; yanlış bir intent, etiketli chunk'lara bonus vererek zarar
    verir. Eşiğin altındaysa intent düşürülür, sorgu metni korunur.
    """
    temiz = kalip_temizle(alintiyi_kirp(raw_text or ""))

    # GÜVENLİK AĞI: temizlik metni yiyip bitirdiyse ham hâle dön.
    if len(temiz) < ASGARI_ANLAMLI:
        temiz = (raw_text or "").strip()

    if len(temiz) > GOVDE_AZAMI:
        temiz = temiz[:GOVDE_AZAMI]

    kullanılacak_intent = intent_type
    if intent_type and intent_confidence is not None and intent_confidence < 0.7:
        kullanılacak_intent = None

    return QuerySpec(metin=temiz, konu=subject, intent_type=kullanılacak_intent)
