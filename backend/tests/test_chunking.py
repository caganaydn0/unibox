"""Madde-farkındalıklı bölme — gerçek yönetmelik PDF'lerine karşı.

Servis gerektirmez, her commit'te koşar. Üç fixture PDF'i birlikte tüm tire
varyantlarını (- – —), harf ekli numaraları (41/A), GEÇİCİ MADDE ayrı
numaralandırmasını ve title-case "Madde 1 -" biçimini kapsıyor.
"""
from __future__ import annotations

import re

import pytest

from app.services.chunking import (
    MADDE_RE,
    _baslik_cikar,
    _madde_eslesmeleri,
    madde_bazli_bol,
    mevzuat_mi,
    normalize,
)
from app.services.rag_engine import RagEngine
from tests.conftest import fixture_path

PDF_LER = {
    "gazi": ("gazi_lisansustu_yonetmelik.pdf", 47),
    "devam": ("lisans_ogrenimine_devam_yonetmelik.pdf", 15),
    "yabanci_dil": ("yabanci_dil_hazirlik_yonetmelik.pdf", 13),
}


def _metin(dosya: str) -> str:
    ham = fixture_path("mevzuat", dosya).read_bytes()
    return RagEngine().extract_text_from_pdf(ham)


@pytest.fixture(scope="module")
def gazi_metni() -> str:
    return _metin(PDF_LER["gazi"][0])


# --------------------------------------------------------------------------- #
# Desen doğruluğu
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("anahtar", list(PDF_LER))
def test_tum_maddeler_bulunur(anahtar: str) -> None:
    dosya, beklenen = PDF_LER[anahtar]
    eşleşmeler = _madde_eslesmeleri(normalize(_metin(dosya)))
    assert len(eşleşmeler) == beklenen, (
        f"{dosya}: {len(eşleşmeler)} madde bulundu, {beklenen} bekleniyordu"
    )


@pytest.mark.parametrize(
    "satır",
    [
        "MADDE 1 – (1) Bu Yönetmeliğin amacı",
        "MADDE 10 \n– \n(1) Kredi transferi",     # numara ile ayraç arasında \n
        "MADDE 41/A – (Ek:RG-29/9/2020)",          # harf ekli numara
        "GEÇİCİ MADDE 1 – (1) Geçiş hükümleri",
        "Madde 2 - Bu yönetmelik dayanağı",        # title case + ASCII tire
        "MADDE 6- Yürürlük",                       # tireden önce boşluk yok
        "GEÇİCİ MADDE 1 —(Ek:RG-8/1/2006)",        # em dash
    ],
)
def test_tum_madde_varyantlari_eslesir(satır: str) -> None:
    assert MADDE_RE.search(satır), f"eşleşmedi: {satır!r}"


@pytest.mark.parametrize(
    "metin",
    [
        "2547 sayılı Kanunun 14 üncü ve 44 üncü maddelerine dayanılarak",
        "ilgili maddede belirtilen şartlar",
        "bu madde kapsamında değerlendirilir",
    ],
)
def test_metin_ici_atiflar_eslesmez(metin: str) -> None:
    """Satır başı çapası, düzyazı içindeki 'madde' atıflarını elemeli."""
    assert not MADDE_RE.search(metin)


def test_geriye_giden_numaralar_elenir() -> None:
    """Yanlış pozitif koruması: numaralar monoton artmalı."""
    sahte = "MADDE 1 – içerik\nMADDE 2 – içerik\nMADDE 1 – sahte eşleşme\n"
    assert len(_madde_eslesmeleri(normalize(sahte))) == 2


def test_gecici_madde_ayri_numaralandirilir() -> None:
    """GEÇİCİ MADDE 1, normal MADDE 1'den bağımsız bir seridir."""
    metin = "MADDE 1 – a\nMADDE 2 – b\nGEÇİCİ MADDE 1 – c\nMADDE 3 – d\n"
    eşleşmeler = _madde_eslesmeleri(normalize(metin))
    assert len(eşleşmeler) == 4


# --------------------------------------------------------------------------- #
# Başlık çıkarımı
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "önceki, beklenen",
    [
        # Önceki maddenin kuyruğu aynı satıra karışmış
        ("...ilişkin hükümleri kapsar. Dayanak", "Dayanak"),
        ("...kabul edilirler. İzinli sayılma", "İzinli sayılma"),
        # Başlık satıra sığmayıp bölünmüş (devam satırı küçük harfle başlar)
        ("Kredi transferi\nve intibak", "Kredi transferi ve intibak"),
        ("Ek\nsüre", "Ek süre"),
        # Temiz başlık
        ("Doktora yeterlik sınavı", "Doktora yeterlik sınavı"),
        # Bölüm adı ayrı satırda — yalnızca son satır alınmalı
        ("Tezli Yüksek Lisans Programı\nKapsam", "Kapsam"),
    ],
)
def test_baslik_cikarimi(önceki: str, beklenen: str) -> None:
    assert _baslik_cikar(önceki) == beklenen


# --------------------------------------------------------------------------- #
# Bölme sonucu
# --------------------------------------------------------------------------- #

def test_her_chunk_kendi_madde_numarasini_tasir(gazi_metni: str) -> None:
    """ASIL KAZANÇ.

    Eski bölmede bir chunk hiç MADDE başlığı taşımıyordu (2491 karakterlik,
    MADDE 3'ün ortası). email_analyzer'daki "madde numarasını yalnızca
    metinde gerçekten geçiyorsa yaz" kuralı o chunk geldiğinde modeli ya
    susmaya ya uydurmaya zorluyordu.
    """
    parçalar = madde_bazli_bol(gazi_metni)
    madde_parçaları = [p for p in parçalar if p.meta["kind"] == "madde"]
    assert madde_parçaları

    for p in madde_parçaları:
        düz = " ".join(p.icerik.split())
        no = p.meta["madde_no"]
        assert re.search(rf"MADDE\s*{re.escape(no)}\b", düz, re.IGNORECASE), (
            f"chunk kendi madde numarasını taşımıyor: {düz[:90]}"
        )


def test_bir_chunk_bir_madde(gazi_metni: str) -> None:
    """Bir chunk birden fazla maddenin GÖVDESİNİ karıştırmamalı.

    Not: üst bilgi satırındaki "(devam N/M)" etiketi hariç, gövdede yalnızca
    kendi madde başlığı bulunmalı.
    """
    for p in madde_bazli_bol(gazi_metni):
        if p.meta["kind"] != "madde":
            continue
        başlangıçlar = _madde_eslesmeleri(p.icerik)
        assert len(başlangıçlar) <= 1, (
            f"chunk {len(başlangıçlar)} madde başlangıcı içeriyor: "
            f"{' '.join(p.icerik.split())[:120]}"
        )


def test_metadata_eksiksiz(gazi_metni: str) -> None:
    for p in madde_bazli_bol(gazi_metni):
        assert p.meta["v"] == 3
        assert p.meta["kind"] in {"madde", "preamble"}
        if p.meta["kind"] == "madde":
            assert p.meta["madde_no"]
            assert isinstance(p.meta["part"], int)
            assert p.meta["part_count"] >= 1


def test_harf_ekli_madde_dogru_etiketlenir(gazi_metni: str) -> None:
    numaralar = {
        p.meta.get("madde_no") for p in madde_bazli_bol(gazi_metni)
    }
    assert "41/A" in numaralar


def test_gecici_madde_oneki_korunur(gazi_metni: str) -> None:
    geçici = [
        p for p in madde_bazli_bol(gazi_metni)
        if p.meta.get("madde_prefix") == "GEÇİCİ"
    ]
    assert geçici, "GEÇİCİ MADDE bulunamadı"
    assert geçici[0].meta["madde_no"] == "1"


def test_uzun_maddeler_parcalanir_ve_isaretlenir(gazi_metni: str) -> None:
    """MADDE 34 (3033 karakter) gibi uzun maddeler bölünmeli."""
    parçalar = madde_bazli_bol(gazi_metni)
    çok_parçalı = [p for p in parçalar if p.meta.get("part_count", 1) > 1]
    assert çok_parçalı, "hiçbir uzun madde parçalanmadı"

    for p in çok_parçalı:
        if p.meta["part"] > 0:
            assert "devam" in p.icerik, "devam parçası işaretlenmemiş"


def test_chunk_boyutlari_makul(gazi_metni: str) -> None:
    parçalar = madde_bazli_bol(gazi_metni)
    uzunluklar = [len(p.icerik) for p in parçalar]
    # Hiçbir chunk aşırı büyük olmamalı (üst bilgi payı dahil)
    assert max(uzunluklar) < 3200, f"en uzun chunk {max(uzunluklar)} karakter"
    # Ortalama, eski ~2330 karakterden belirgin şekilde küçülmeli
    ortalama = sum(uzunluklar) / len(uzunluklar)
    assert ortalama < 1500, f"ortalama chunk {ortalama:.0f} karakter"


def test_dokuman_adi_chunklara_eklenmez(gazi_metni: str) -> None:
    """Doküman adı eklenirse o dokümanın TÜM chunk'ları başlık kelimeleriyle
    eşleşir ve aday havuzunu tek başına doldurur."""
    for p in madde_bazli_bol(gazi_metni):
        assert "gazi_lisansustu_yonetmelik" not in p.icerik.lower()


# --------------------------------------------------------------------------- #
# Mod seçimi — geri uyumluluk
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("anahtar", list(PDF_LER))
def test_yonetmelikler_mevzuat_sayilir(anahtar: str) -> None:
    assert mevzuat_mi(_metin(PDF_LER[anahtar][0]))


@pytest.mark.parametrize(
    "metin",
    [
        "Transkript belgesi öğrencinin tüm derslerini ve notlarını gösterir. "
        "Aktif veya mezun tüm öğrenciler talep edebilir.",
        "Yaz okulu isteğe bağlıdır ve ücretlidir.",
        "",
        "Tek bir MADDE 1 – geçen kısa metin.",   # eşikten az
    ],
)
def test_rehber_metinleri_mevzuat_sayilmaz(metin: str) -> None:
    """Kısa rehber metinleri eski bölücüye düşmeli — geri uyumluluk bedava."""
    assert not mevzuat_mi(metin)


def test_normalize_satir_sonlarini_korur() -> None:
    """MADDE_RE satır başı çapasına dayanıyor; satır sonları kaybolmamalı."""
    çıktı = normalize("Başlık\nMADDE 1 – içerik\n\n\nMADDE 2 – içerik")
    assert "\n" in çıktı
    assert len(_madde_eslesmeleri(çıktı)) == 2


def test_normalize_satir_sonu_tirelemesini_birlestirir() -> None:
    assert "yönetmelik" in normalize("yönet-\nmelik hükümleri")
