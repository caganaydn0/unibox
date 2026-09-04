"""Geri getirim ölçümü — sabit fixture korpusuna karşı.

İki ayrı soru:

1. MADDE DÜZEYİ (test_yonetmelik_*): Gerçek bir üniversite yönetmeliğinde,
   öğrencinin sorusuna karşılık gelen MADDE bulunabiliyor mu? Faz 3'teki
   madde-farkındalıklı chunking'in asıl hedef metriği bu.

2. DOKÜMAN DÜZEYİ (test_rehber_*): Kısa, konuya özel rehber metinlerinde
   doğru doküman geliyor mu? Bu bir GERİLEME KORUMASIDIR: chunk sayısını
   artıran her değişiklik (madde bazlı bölme gibi) aday havuzunu büyük
   dokümanla doldurup kısa dokümanları dışarı itebilir. config.py:40-44'te
   belgelenen felaket tam olarak buydu (@3 %70 -> %50).

Sorular kasten madde/doküman başlığındaki kelimeleri tekrarlamıyor; aksi
halde ölçüm sözcüksel aramanın lehine hile yapmış olurdu.

Baseline dondurma:
    UNIBOX_WRITE_BASELINE=1 uv run pytest tests/rag/test_retrieval.py -s
Baseline varsa testler ona karşı GERİLEME kontrolü yapar.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from tests.conftest import fixture_path
from tests.rag.metrics import Ölçüm, paired_diff, tablo

pytestmark = pytest.mark.rag_eval

# Bir soruluk tolerans: n=52'de tek soru ~2 puan. Gerçek gerilemeyi yakalar,
# beraberlik kaymasından kaynaklanan gürültüde patlamaz.
TOLERANS = 1


def _madde_deseni(madde: str) -> re.Pattern:
    """'12', '41/A', 'GEÇİCİ 1' hedefleri için eşleştirici.

    Dikkat: düz 'MADDE 1' deseni 'GEÇİCİ MADDE 1' ile de eşleşir; ikisi
    farklı maddelerdir. Bu yüzden GEÇİCİ önekini yakalayıp ayırt ediyoruz.
    """
    geçici = madde.startswith("GEÇİCİ")
    no = madde.split()[-1] if geçici else madde
    return re.compile(rf"(GEÇİCİ\s+)?MADDE\s*{re.escape(no)}\b")


def _madde_içeriyor(içerik: str, madde: str) -> bool:
    düz = " ".join(içerik.split())
    geçici_isteniyor = madde.startswith("GEÇİCİ")
    for m in _madde_deseni(madde).finditer(düz):
        if bool(m.group(1)) == geçici_isteniyor:
            return True
    return False


def _soruları_oku(dosya: str) -> list[dict]:
    yol = fixture_path("queries", dosya)
    return [
        json.loads(s) for s in yol.read_text(encoding="utf-8").splitlines() if s.strip()
    ]


async def _ölç(ad: str, sorular: list[dict], eşleşti) -> Ölçüm:
    from app.services.rag_engine import RagEngine

    rag = RagEngine()
    ölçüm = Ölçüm(ad)
    for kayıt in sorular:
        parçalar = await rag.search(kayıt["soru"], None)
        konum = next(
            (i for i, (içerik, etiket, _) in enumerate(parçalar) if eşleşti(kayıt, içerik, etiket)),
            None,
        )
        ölçüm.ekle(kayıt["soru"], konum)
    return ölçüm


def _raporla_ve_doğrula(ölçüm: Ölçüm, korpus, k: int) -> None:
    print("\n" + tablo(ölçüm))

    kaçan = ölçüm.kaçırılanlar(3)
    if kaçan:
        print(f"\n  ilk 3'te bulunamayan ({len(kaçan)}):")
        for soru in kaçan[:12]:
            print(f"    - {soru}")

    if os.environ.get("UNIBOX_WRITE_BASELINE"):
        yol = ölçüm.baseline_yaz(korpus.damga)
        print(f"\n  baseline yazıldı: {yol.name}")
        return

    baseline = ölçüm.baseline_oku()
    if baseline is None:
        pytest.skip(
            f"'{ölçüm.ad}' için baseline yok. Dondurmak için: "
            "UNIBOX_WRITE_BASELINE=1 uv run pytest tests/rag -s"
        )

    if baseline["korpus_damgası"] != korpus.damga:
        pytest.skip(
            f"Korpus değişti (baseline {baseline['korpus_damgası']}, "
            f"şimdi {korpus.damga}). Baseline yeniden dondurulmalı."
        )

    fark = paired_diff(baseline["konumlar"], ölçüm, k)
    print(f"\n  baseline'a göre {fark}")
    if fark.düzelen:
        print(f"    düzelen: {fark.düzelen[:5]}")
    if fark.bozulan:
        print(f"    BOZULAN: {fark.bozulan}")

    # Yüzde değil, soru sayısı üzerinden gerileme kontrolü — n küçükken
    # yüzde farkları anlamsız (bkz. metrics.py docstring).
    assert len(fark.bozulan) <= TOLERANS + len(fark.düzelen), (
        f"@{k} geriledi: {len(fark.bozulan)} soru bozuldu, "
        f"{len(fark.düzelen)} soru düzeldi. Bozulanlar: {fark.bozulan}"
    )


# --------------------------------------------------------------------------- #
# 1. Madde düzeyi — gerçek yönetmelik
# --------------------------------------------------------------------------- #

async def test_yonetmelik_madde_geri_getirimi(korpus) -> None:
    sorular = _soruları_oku("regulation_madde.jsonl")
    assert len(sorular) >= 50, "soru seti küçüldü; n=16'da farklar ölçülemez"

    ölçüm = await _ölç(
        "yonetmelik_madde",
        sorular,
        lambda kayıt, içerik, _etiket: _madde_içeriyor(içerik, kayıt["madde"]),
    )
    _raporla_ve_doğrula(ölçüm, korpus, k=3)


# --------------------------------------------------------------------------- #
# 2. Doküman düzeyi — kısa rehber metinleri (gerileme koruması)
# --------------------------------------------------------------------------- #

async def test_rehber_dokuman_geri_getirimi(korpus) -> None:
    """Kısa dokümanlar büyük yönetmeliklerin altında ezilmemeli."""
    sorular = _soruları_oku("guide_docs.jsonl")

    ölçüm = await _ölç(
        "rehber_dokuman",
        sorular,
        lambda kayıt, _içerik, etiket: etiket == kayıt["belge"],
    )
    _raporla_ve_doğrula(ölçüm, korpus, k=3)


# --------------------------------------------------------------------------- #
# 3. Sağlamlık — arama hiçbir girdide patlamamalı
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "girdi",
    [
        "http://obs.gazi.edu.tr/oibs/ogrenci ders kaydı nasıl yapılır",
        "Bilgi için ogrenci.isleri@gazi.edu.tr adresine yazdım",
        "transkript & belge",
        "!!! acil !!!",
        "Gazi'nin yönetmeliğinde ne yazıyor?",
        "MADDE 5/A neyi düzenliyor?",
        "ve ile de mi",          # yalnızca stopword
        "",                       # boş
        "a" * 5000,               # çok uzun
        "(((",                    # dengesiz parantez
        "ders:1 | not:2",         # tsquery operatör karakterleri
    ],
)
async def test_arama_dusmanca_girdide_patlamaz(korpus, girdi: str) -> None:
    """search() hiçbir kullanıcı metninde istisna fırlatmamalı.

    Bu sadece teorik değil: _turkish_tsquery lexeme'leri tırnaklamadan
    TSQUERY'ye cast ediyor. URL'ler tek bir lexeme olarak ':' içerdiği için
    PostgreSQL 'syntax error in tsquery' fırlatabiliyor ve search()'te
    try/except yok. En açık hedef email_analyzer: sorgu metni olarak TÜM
    e-posta gövdesini veriyor ve öğrenci e-postalarında link çok yaygın.

    Boş liste dönmek kabul; istisna kabul DEĞİL.
    """
    from app.services.rag_engine import RagEngine

    sonuç = await RagEngine().search(girdi, None)
    assert isinstance(sonuç, list)


# --------------------------------------------------------------------------- #
# 4. Kısmi arıza toleransı — iki geri getirim bağımsız olmalı
# --------------------------------------------------------------------------- #

async def test_ollama_kapaliyken_sozcuksel_arama_devam_eder(korpus, monkeypatch) -> None:
    """Anlamsal arama çökerse sözcüksel arama tek başına iş görmeli.

    Eskiden vektör arama ikisinin de ön koşuluydu: embed_text istisnası
    doğrudan sohbet isteğini 500'e çeviriyordu. Oysa PostgreSQL tam metin
    araması Ollama'ya hiç ihtiyaç duymuyor — bilgi tabanı erişilebilirken
    öğrenciye hata döndürmek gereksiz.
    """
    from app.services.rag_engine import RagEngine

    async def ollama_kapali(self, text: str):
        raise ConnectionError("Ollama erişilemiyor (simüle edilmiş)")

    monkeypatch.setattr(RagEngine, "embed_text", ollama_kapali)

    # Anahtar kelimesi bilgi tabanında birebir geçen bir sorgu
    sonuç = await RagEngine().search("transkript belgesi", None)
    assert sonuç, "Ollama kapalıyken sözcüksel arama sonuç döndürmeliydi"


async def test_sozcuksel_arama_cokerse_anlamsal_devam_eder(korpus, monkeypatch) -> None:
    """Simetrik durum: FTS bozulursa vektör araması tek başına iş görmeli."""
    import app.services.rag_engine as motor

    def bozuk_tsquery(soru: str):
        raise RuntimeError("tsquery ayrıştırma hatası (simüle edilmiş)")

    monkeypatch.setattr(motor, "_turkish_tsquery", bozuk_tsquery)

    sonuç = await motor.RagEngine().search("Doktora yeterlik sınavı şartları", None)
    assert sonuç, "FTS bozukken anlamsal arama sonuç döndürmeliydi"


async def test_her_ikisi_de_cokerse_bos_doner(korpus, monkeypatch) -> None:
    """Hiçbir durumda istisna sızmamalı — LLM bağlamsız kalıp geri çekilir."""
    import app.services.rag_engine as motor

    async def ollama_kapali(self, text: str):
        raise ConnectionError("Ollama erişilemiyor")

    def bozuk_tsquery(soru: str):
        raise RuntimeError("tsquery hatası")

    monkeypatch.setattr(motor.RagEngine, "embed_text", ollama_kapali)
    monkeypatch.setattr(motor, "_turkish_tsquery", bozuk_tsquery)

    assert await motor.RagEngine().search("transkript", None) == []
