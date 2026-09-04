"""Sorgu oluşturma — saf birim testleri + uzun e-posta ölçümü.

Bugüne kadar HİÇBİR ölçüm production'daki gelen e-posta yolunu temsil
etmiyordu: tüm evaller kısa, temiz, elle yazılmış sorularla çalışıyordu.
Gerçek e-postalar selamlama, imza ve alıntılanmış thread taşıyor ve bunlar
embedding'i ele geçiriyor.
"""
from __future__ import annotations

import json

import pytest

from app.services.rag_query import (
    ASGARI_ANLAMLI,
    GOVDE_AZAMI,
    alintiyi_kirp,
    build_query,
    kalip_temizle,
)
from tests.conftest import fixture_path
from tests.rag.metrics import Ölçüm, paired_diff, tablo


# --------------------------------------------------------------------------- #
# Alıntı ve imza kırpma (saf)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "ayrac",
    [
        "-----Original Message-----",
        "From: ogrenci.isleri@gazi.edu.tr",
        "Gönderen: Ali Veli",
        "12 Haziran 2026 tarihinde biri@x.com yazdı:",
        "On Mon, Jun 12, 2026 at 10:00 AM someone wrote:",
        "________________________________",
    ],
)
def test_alintilanmis_thread_kirpilir(ayrac: str) -> None:
    gövde = f"Transkript belgemi nasıl alabilirim?\n\n{ayrac}\nEski mesaj içeriği burada."
    sonuç = alintiyi_kirp(gövde)
    assert "Transkript belgemi" in sonuç
    assert "Eski mesaj içeriği" not in sonuç


def test_imza_ayraci_kirpilir() -> None:
    sonuç = alintiyi_kirp("Sorum şu.\n\n-- \nAhmet Yılmaz\nTel: 0532 111 22 33")
    assert "Sorum şu." in sonuç
    assert "0532" not in sonuç


def test_alinti_satirlari_kirpilir() -> None:
    sonuç = alintiyi_kirp("Yeni sorum.\n> eski satır\n> bir eski satır daha")
    assert "Yeni sorum." in sonuç
    assert "eski satır" not in sonuç


@pytest.mark.parametrize(
    "kalıp",
    ["Sayın Yetkili,", "Merhaba,", "Saygılarımla,", "İyi çalışmalar dilerim.",
     "Teşekkür ederim.", "Gereğini rica ederim."],
)
def test_kalip_selamlama_ve_kapanis_kirpilir(kalıp: str) -> None:
    sonuç = kalip_temizle(f"{kalıp}\nKayıt dondurma şartları neler?\n{kalıp}")
    assert "Kayıt dondurma şartları" in sonuç
    assert kalıp.rstrip(",.") not in sonuç


def test_imza_satirlari_kirpilir() -> None:
    gövde = (
        "Yaz okulu ücretli mi?\n"
        "Tel: 0532 111 22 33\n"
        "ahmet@ogrenci.gazi.edu.tr\n"
        "https://linkedin.com/in/ahmet"
    )
    sonuç = kalip_temizle(gövde)
    assert "Yaz okulu ücretli mi?" in sonuç
    for sızıntı in ("0532", "@ogrenci", "linkedin"):
        assert sızıntı not in sonuç


# --------------------------------------------------------------------------- #
# build_query davranışı
# --------------------------------------------------------------------------- #

def test_govde_sinirlaniyor() -> None:
    spec = build_query(raw_text="Kayıt dondurma. " * 500)
    assert len(spec.metin) <= GOVDE_AZAMI


def test_konu_ayri_sorgu_olarak_tasiniyor() -> None:
    spec = build_query(raw_text="Şartları neler acaba?", subject="Kayıt dondurma talebi")
    assert len(spec.sorgular) == 2
    assert "Kayıt dondurma talebi" in spec.sorgular


def test_konu_govdede_zaten_varsa_tekrarlanmaz() -> None:
    spec = build_query(raw_text="Kayıt dondurma talebi hakkında bilgi istiyorum.",
                       subject="Kayıt dondurma talebi")
    assert len(spec.sorgular) == 1


def test_asiri_kirpmada_ham_metne_donulur() -> None:
    """GÜVENLİK AĞI: öğrenci talebini alıntının ALTINA yazmış olabilir.

    Temizlik metni yiyip bitirirse elimizde hiç sorgu kalmaz; ham metne
    dönmek boş aramadan iyidir.
    """
    # Neredeyse tamamı kalıp — temizlik sonrası anlamlı içerik kalmıyor
    gövde = "Sayın Yetkili,\nSaygılarımla,\nAhmet Yılmaz"
    spec = build_query(raw_text=gövde)
    assert len(spec.metin) >= min(len(gövde), ASGARI_ANLAMLI) or spec.metin == gövde.strip()
    assert spec.metin, "sorgu tamamen boşaltılmamalı"


def test_dusuk_guvenli_intent_dusurulur() -> None:
    """LLM sınıflandırıcısı yanılabilir; yanlış intent etiketli chunk'lara
    haksız bonus verir."""
    yüksek = build_query(raw_text="Transkript istiyorum", intent_type="transcript_request",
                         intent_confidence=0.9)
    düşük = build_query(raw_text="Transkript istiyorum", intent_type="transcript_request",
                        intent_confidence=0.4)
    assert yüksek.intent_type == "transcript_request"
    assert düşük.intent_type is None


def test_guven_verilmezse_intent_korunur() -> None:
    """Sohbet yolunda güven skoru yok; intent düşürülmemeli."""
    spec = build_query(raw_text="Transkript istiyorum", intent_type="transcript_request")
    assert spec.intent_type == "transcript_request"


def test_bos_girdi_patlamaz() -> None:
    for girdi in ("", "   ", None):
        spec = build_query(raw_text=girdi)
        assert isinstance(spec.sorgular, list)


# --------------------------------------------------------------------------- #
# Uzun e-posta ölçümü (canlı)
# --------------------------------------------------------------------------- #

pytestmark_eval = pytest.mark.rag_eval


def _emailleri_oku() -> list[dict]:
    yol = fixture_path("queries", "long_email.jsonl")
    return [json.loads(s) for s in yol.read_text(encoding="utf-8").splitlines() if s.strip()]


def _eslesti(kayıt: dict, içerik: str, etiket: str) -> bool:
    from tests.rag.test_retrieval import _madde_içeriyor

    if "madde" in kayıt:
        return _madde_içeriyor(içerik, kayıt["madde"])
    return etiket == kayıt["belge"]


@pytest.mark.rag_eval
async def test_uzun_eposta_geri_getirimi(korpus) -> None:
    """Gerçekçi e-posta gövdelerinde hedef bulunuyor mu?

    HAM gövde ile TEMİZLENMİŞ sorguyu aynı sette karşılaştırır; fark
    doğrudan build_query'nin katkısıdır.
    """
    from app.services.rag_engine import RagEngine

    rag = RagEngine()
    kayıtlar = _emailleri_oku()
    assert len(kayıtlar) >= 15

    ham_ölçüm = Ölçüm("uzun_eposta_ham")
    temiz_ölçüm = Ölçüm("uzun_eposta")

    for kayıt in kayıtlar:
        anahtar = kayıt["konu"]

        # (a) ESKİ davranış: konu + tüm gövde tek sorgu, intent yok
        ham_sorgu = f"{kayıt['konu']} {kayıt['govde']}"
        ham = await rag.search(ham_sorgu, None)
        ham_ölçüm.ekle(anahtar, next(
            (i for i, (iç, et, _) in enumerate(ham) if _eslesti(kayıt, iç, et)), None
        ))

        # (b) YENİ davranış: temizlenmiş gövde + konu ayrı sorgu
        spec = build_query(raw_text=kayıt["govde"], subject=kayıt["konu"])
        temiz = await rag.search_many(spec.sorgular, spec.intent_type)
        temiz_ölçüm.ekle(anahtar, next(
            (i for i, (iç, et, _) in enumerate(temiz) if _eslesti(kayıt, iç, et)), None
        ))

    print("\n--- ESKİ (ham gövde, tek sorgu) ---")
    print(tablo(ham_ölçüm))
    print("\n--- YENİ (temizlenmiş + konu çoklu sorgu) ---")
    print(tablo(temiz_ölçüm))

    fark = paired_diff({s.soru: s.konum for s in ham_ölçüm.sonuçlar}, temiz_ölçüm, k=3)
    print(f"\n  ham -> temiz  {fark}")
    if fark.düzelen:
        print(f"    düzelen: {fark.düzelen}")
    if fark.bozulan:
        print(f"    BOZULAN: {fark.bozulan}")

    # Temizlik en azından zarar vermemeli
    assert temiz_ölçüm.recall(3) >= ham_ölçüm.recall(3) - 0.05, (
        "sorgu temizliği geri getirimi düşürdü"
    )
