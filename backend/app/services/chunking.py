"""Madde-farkındalıklı metin bölme (structure-aware chunking).

NEDEN: Sabit uzunlukta bölme, Türk mevzuat metninin yapısını görmüyordu.
Gerçek Gazi Lisansüstü Yönetmeliği üzerinde ölçüldü: 45 maddenin 7'si iki
chunk'a bölünüyor ve bir chunk hiç MADDE başlığı taşımıyordu. Bunun iki
somut sonucu var:

  1. Hedef madde, birkaç maddenin karışımı olan bir chunk'ın ortasına
     gömülü kalıyor ve geri getirimde öne çıkamıyor.
  2. email_analyzer'daki "madde numarasını YALNIZCA metinde gerçekten
     geçiyorsa yaz" kuralı, numarasız bir chunk geldiğinde modeli ya
     susmaya ya uydurmaya zorluyor.

BU MODÜL "1 chunk = 1 madde" değişmezini kurar. Çok uzun maddeler fıkra
sınırından alt parçalara ayrılır ve her parça üst bilgisini tekrarlar.

Mevzuat olmayan metinler (rehber, SSS, DOCX) için eski davranış korunur —
mod seçimi otomatiktir, çağıranın bir şey bilmesi gerekmez.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Desenler
# --------------------------------------------------------------------------- #

# pypdf çıktısında gözlemlenen varyantlar (dört gerçek PDF üzerinde ölçüldü):
#   'MADDE 1 – \n(1) ...'          normal
#   'MADDE 10 \n– \n(1) ...'       numara ile ayraç ARASINDA satır sonu
#   'MADDE 41/A – (Ek:RG-...)'     harf ekli numara
#   'GEÇİCİ MADDE 1 \n–  \n(1)'    ayrı numara alanı, 1'den başlar
#   'Madde 2 - Bu yönetmelik'      title case + ASCII tire
#   'GEÇİCİ MADDE 1 —(Ek:RG-...)'  em dash, ayraçtan sonra boşluk yok
#
# Üç farklı tire kullanılıyor: - (U+002D), – (U+2013), — (U+2014).
#
# Satır başı çapası (MULTILINE ^) kasıtlı: metin içi atıflar "14 üncü ve 44
# üncü maddelerine" biçiminde geçiyor ve satır ortasında kalıyor, dolayısıyla
# yanlış eşleşme üretmiyor.
MADDE_RE = re.compile(
    r"^[ \t]*"
    r"(?P<prefix>(?:GEÇİCİ|GEÇICI|GECICI|EK)\s+)?"
    r"MADDE"
    r"[ \t\r\n]*"
    r"(?P<no>\d{1,3}(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)"
    r"[ \t\r\n]*"
    r"(?:[-–—]|\()",
    re.MULTILINE | re.IGNORECASE,
)

# "BİRİNCİ BÖLÜM", "İKİNCİ BÖLÜM", "Amaç, Kapsam, Dayanak ve Tanımlar" gibi
# bölüm başlıkları
BOLUM_RE = re.compile(
    r"^[ \t]*(?P<ad>[A-ZÇĞİÖŞÜ\w]+)\s+BÖLÜM[ \t]*$",
    re.MULTILINE,
)

# Fıkra işareti: "(1)", "( 1)", satır başında veya boşluk sonrası
FIKRA_RE = re.compile(r"(?:^|(?<=\s))\(\s*(\d{1,2})\s*\)")

# Cümle sonu — başlık çıkarımında önceki maddenin kuyruğunu kesmek için
CUMLE_SONU_RE = re.compile(r"[.!?]\s+")

# Bu sayıdan az madde bulunursa metin mevzuat sayılmaz
MEVZUAT_ESIGI = 3

# Alt parçalara ayrılmadan önce bir maddenin ulaşabileceği azami uzunluk
MADDE_AZAMI_KARAKTER = 2500
# Alt parça hedefi — üst bilgi tekrarı için pay bırakır
PARCA_HEDEF_KARAKTER = 1800

CHUNKER_SURUMU = 3


@dataclass
class Parca:
    """Tek bir chunk ve meta verisi."""

    icerik: str
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Normalizasyon
# --------------------------------------------------------------------------- #

def normalize(metin: str) -> str:
    """Metni bölmeye hazırlar — SATIR SONLARINI KORUYARAK.

    Satır sonlarını ezmek cazip görünüyor ama MADDE_RE satır başı çapasına
    dayanıyor; onları kaybetmek deseni işlevsiz bırakır.
    """
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")
    metin = metin.replace("\xa0", " ").replace("​", "")
    # Satır sonunda tireleme: "yönet-\nmelik" -> "yönetmelik"
    metin = re.sub(r"(\w)-\n(?=[a-zçğıöşü])", r"\1", metin)
    metin = re.sub(r"[ \t]+", " ", metin)
    metin = re.sub(r" *\n *", "\n", metin)
    metin = re.sub(r"\n{3,}", "\n\n", metin)
    return metin.strip()


# --------------------------------------------------------------------------- #
# Madde tespiti
# --------------------------------------------------------------------------- #

def _madde_eslesmeleri(metin: str) -> list[re.Match]:
    """Geçerli madde başlangıçlarını döner.

    YANLIŞ POZİTİF KORUMASI: numaralar monoton artmalı. Bir paragrafın satır
    başına denk gelmesiyle oluşan sahte eşleşmeler bu kuralla elenir.
    Numaralandırma her önek için ayrı ilerler ("GEÇİCİ MADDE 1", normal
    "MADDE 1"den bağımsızdır).
    """
    kabul: list[re.Match] = []
    son_no: dict[str, float] = {}

    for m in MADDE_RE.finditer(metin):
        önek = (m.group("prefix") or "").strip().upper()
        ham_no = m.group("no").replace(" ", "")
        # "41/A" -> 41.5 gibi bir sıra değeri; harf eki maddeyi bir sonraki
        # tam sayının önüne değil, ait olduğu maddenin hemen ardına koyar
        temel = int(re.match(r"\d+", ham_no).group())
        sıra = temel + (0.5 if "/" in ham_no else 0.0)

        if önek in son_no and sıra <= son_no[önek]:
            continue  # geriye giden numara — sahte eşleşme
        son_no[önek] = sıra
        kabul.append(m)

    return kabul


def _baslik_cikar(onceki_metin: str) -> str:
    """Madde başlığını, eşleşmeden önceki metinden çıkarır.

    pypdf çıktısında başlık iki şekilde bozulabiliyor:

      a) Önceki maddenin kuyruğu aynı satıra karışıyor:
         "...hükümleri kapsar. Dayanak"  ->  "Dayanak"
      b) Başlığın kendisi satıra sığmayıp bölünüyor:
         "Kredi transferi \nve intibak"  ->  "Kredi transferi ve intibak"

    (b) için ipucu: devam satırı küçük harfle başlar.
    """
    satırlar = [s.strip() for s in onceki_metin.split("\n") if s.strip()]
    if not satırlar:
        return ""

    başlık = satırlar[-1]

    # (b) Sarmalanmış başlık: son satır küçük harfle başlıyorsa önceki satır
    # aynı başlığın devamıdır
    if len(satırlar) >= 2 and başlık[:1].islower():
        başlık = f"{satırlar[-2]} {başlık}"

    # (a) Önceki maddenin kuyruğunu kes — son cümle sonundan SONRASINI al
    parçalar = CUMLE_SONU_RE.split(başlık)
    if len(parçalar) > 1 and parçalar[-1].strip():
        başlık = parçalar[-1]

    başlık = başlık.strip(" -–—:;,")
    # Aşırı uzun bir sonuç, başlık değil düzyazı yakalandığını gösterir
    return başlık if 0 < len(başlık) <= 90 else ""


def _bolum_haritasi(metin: str) -> list[tuple[int, str]]:
    """(konum, bölüm adı) listesi — her maddeye en yakın öncekini atamak için."""
    harita: list[tuple[int, str]] = []
    for m in BOLUM_RE.finditer(metin):
        # Bölüm adının açıklaması genelde BİR SONRAKİ satırda
        sonrası = metin[m.end():m.end() + 120].split("\n")
        açıklama = next((s.strip() for s in sonrası if s.strip()), "")
        ad = f"{m.group('ad')} BÖLÜM"
        if açıklama and len(açıklama) <= 80 and not MADDE_RE.match(açıklama):
            ad = f"{ad} — {açıklama}"
        harita.append((m.start(), ad))
    return harita


def _bolum_bul(harita: list[tuple[int, str]], konum: int) -> str:
    ad = ""
    for başlangıç, bölüm in harita:
        if başlangıç < konum:
            ad = bölüm
        else:
            break
    return ad


# --------------------------------------------------------------------------- #
# Uzun maddeleri alt parçalara ayırma
# --------------------------------------------------------------------------- #

def _fikra_sinirlari(govde: str) -> list[int]:
    """Fıkra başlangıç konumları — monoton artan numaralara göre."""
    konumlar: list[int] = []
    beklenen = 1
    for m in FIKRA_RE.finditer(govde):
        if int(m.group(1)) == beklenen:
            konumlar.append(m.start())
            beklenen += 1
    return konumlar


def _govdeyi_bol(govde: str) -> list[str]:
    """Uzun madde gövdesini fıkra sınırından parçalara ayırır."""
    if len(govde) <= MADDE_AZAMI_KARAKTER:
        return [govde]

    sınırlar = _fikra_sinirlari(govde)
    if len(sınırlar) < 2:
        # Fıkra yapısı yok — karakter bazlı geri düşüş
        return [
            govde[i:i + PARCA_HEDEF_KARAKTER]
            for i in range(0, len(govde), PARCA_HEDEF_KARAKTER)
        ]

    parçalar: list[str] = []
    tampon = ""
    for i, başlangıç in enumerate(sınırlar):
        bitiş = sınırlar[i + 1] if i + 1 < len(sınırlar) else len(govde)
        fıkra = govde[başlangıç:bitiş]
        if tampon and len(tampon) + len(fıkra) > PARCA_HEDEF_KARAKTER:
            parçalar.append(tampon)
            tampon = fıkra
        else:
            tampon += fıkra
    if tampon.strip():
        parçalar.append(tampon)

    # İlk fıkradan önceki giriş metni varsa ilk parçaya ekle
    if sınırlar[0] > 0 and parçalar:
        parçalar[0] = govde[:sınırlar[0]] + parçalar[0]
    return parçalar


# --------------------------------------------------------------------------- #
# Ana giriş noktası
# --------------------------------------------------------------------------- #

def mevzuat_mi(metin: str) -> bool:
    return len(_madde_eslesmeleri(normalize(metin))) >= MEVZUAT_ESIGI


def madde_bazli_bol(metin: str) -> list[Parca]:
    """Mevzuat metnini madde bazlı chunk'lara ayırır."""
    metin = normalize(metin)
    eşleşmeler = _madde_eslesmeleri(metin)
    if not eşleşmeler:
        return []

    bölümler = _bolum_haritasi(metin)
    parçalar: list[Parca] = []

    # Önsöz: ilk maddeden önceki metin (yönetmelik adı, yayım bilgisi)
    önsöz = metin[: eşleşmeler[0].start()].strip()
    if len(önsöz) > 40:
        parçalar.append(Parca(
            icerik=önsöz,
            meta={"v": CHUNKER_SURUMU, "kind": "preamble"},
        ))

    for i, m in enumerate(eşleşmeler):
        son = eşleşmeler[i + 1].start() if i + 1 < len(eşleşmeler) else len(metin)
        tam_madde = metin[m.start():son].strip()

        önek = (m.group("prefix") or "").strip().upper() or None
        no = m.group("no").replace(" ", "")
        başlık = _baslik_cikar(metin[max(0, m.start() - 200):m.start()])
        bölüm = _bolum_bul(bölümler, m.start())

        alt_parçalar = _govdeyi_bol(tam_madde)
        toplam = len(alt_parçalar)

        for j, gövde in enumerate(alt_parçalar):
            # ÜST BİLGİ: bölüm + başlık her parçaya eklenir.
            # Üç kazancı var: (a) embedding konu bağlamı kazanır, (b) tam
            # metin araması başlık kelimelerini indeksler, (c) her chunk
            # kendi madde numarasını taşır, böylece atıf kuralı sağlanır.
            #
            # DOKÜMAN ADI KASTEN EKLENMİYOR: eklenirse o dokümanın TÜM
            # chunk'ları başlık kelimeleriyle eşleşir ve aday havuzunu tek
            # başına doldurur. Doküman adı zaten bağlam metnine
            # "[Kaynak N — ...]" olarak ekleniyor.
            # BÖLÜM ADI KASTEN EKLENMİYOR — ölçümle elendi.
            #
            # İlk sürümde bölüm adı da ekleniyordu ve rehber dokümanlarının
            # 1. sıra oranını %68'den %56'ya düşürdü. Sebep: bölüm açıklaması
            # PDF'te çok satıra yayıldığı için yalnızca ilk kelimesi
            # yakalanıyor ve üst bilgi "YEDİNCİ BÖLÜM — Çeşitli Ek süre",
            # "İKİNCİ BÖLÜM — Genel Yarıyıl kaydı" gibi bozuk çıkıyordu.
            # "Çeşitli", "Genel", "Tezsiz" gibi anlamsız kelimeler o bölümdeki
            # HER chunk'a bulaşıp alakasız eşleşme üretiyordu (ör. "bankaya
            # verecek belge" sorusunu "Dönem projesi ve yeterlik sınavı"
            # maddesi kazanıyordu).
            #
            # Bölüm bilgisi meta_json'da duruyor: filtreleme/gösterim için
            # değerli, geri getirim metnine karışması zararlı.
            üst: list[str] = []
            if başlık:
                üst.append(başlık)
            if j > 0:
                etiket = f"{önek} MADDE {no}" if önek else f"MADDE {no}"
                üst.append(f"{etiket} (devam {j + 1}/{toplam})")

            içerik = ("\n".join(üst) + "\n" + gövde).strip() if üst else gövde
            parçalar.append(Parca(
                icerik=içerik,
                meta={
                    "v": CHUNKER_SURUMU,
                    "kind": "madde",
                    "madde_no": no,
                    "madde_prefix": önek,
                    "baslik": başlık or None,
                    "bolum": bölüm or None,
                    "part": j,
                    "part_count": toplam,
                },
            ))

    return parçalar
