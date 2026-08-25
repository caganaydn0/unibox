"""KVKK maskeleme ve taslak temizliği — bağımsız doğrulama.

NEDEN BAĞIMSIZ: scripts/eval_draft.py bu modülün kendi regex'lerini
(_PII_TALEP_RE, _PLACEHOLDER_RE) modeli puanlamak için hakem olarak kullanıyor.
Regex bir ihlali kaçırırsa hem üretim kaçırır hem ölçüm kaçırır ve tabloda
"pii_ihlal %0" yazar. Buradaki testler o döngüyü kırar: beklenen çıktı elle
yazılmış sabit metinlerdir, üretim regex'i hakem olarak kullanılmaz.

Bu testler ağ/DB gerektirmez ve her commit'te koşmalıdır.
"""
from __future__ import annotations

import pytest

from app.services.anonymizer import (
    dedupe_lines,
    drop_orphan_intros,
    has_pii,
    mask_pii,
    sanitize_draft_body,
    strip_pii_requests,
    strip_placeholders,
)

# --------------------------------------------------------------------------- #
# mask_pii — yakalanması ZORUNLU olanlar
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "metin, görünmemeli",
    [
        ("TC kimlik numaram 12345678901 şeklindedir.", "12345678901"),
        ("Kimlik: 98765432109", "98765432109"),
        ("Telefonum 0532 123 45 67", "0532"),
        ("Cep: +90 532 123 45 67", "+90"),
        ("Tel: 0532-123-45-67", "0532-123-45-67"),
        ("Bana ahmet.yilmaz@gazi.edu.tr adresinden ulaşabilirsiniz.",
         "ahmet.yilmaz@gazi.edu.tr"),
        ("Adım Ahmet Yılmaz, öğrencinizim.", "Ahmet Yılmaz"),
    ],
)
def test_mask_pii_hassas_veriyi_kaldırır(metin: str, görünmemeli: str) -> None:
    sonuç = mask_pii(metin)
    assert görünmemeli not in sonuç, f"maskelenmedi: {sonuç!r}"
    assert "_MASKED]" in sonuç


def test_mask_pii_birden_fazla_türü_aynı_anda_yakalar() -> None:
    metin = "Ben Ayşe Demir, TCKN 12345678901, tel 0532 111 22 33, ayse@gazi.edu.tr"
    sonuç = mask_pii(metin)
    for sızıntı in ("12345678901", "0532", "ayse@gazi.edu.tr", "Ayşe Demir"):
        assert sızıntı not in sonuç, f"{sızıntı!r} sızdı: {sonuç!r}"


@pytest.mark.parametrize("boş", ["", None])
def test_mask_pii_boş_girdide_patlamaz(boş) -> None:
    assert mask_pii(boş) == boş


def test_mask_pii_pii_olmayan_metni_bozmaz() -> None:
    # Kurumsal terimler ve sayılar maskelenmemeli
    metin = "Yaz okulu ücreti kredi başına belirlenir ve 2024-2025 döneminde geçerlidir."
    assert mask_pii(metin) == metin


def test_tckn_uzunluk_sınırı() -> None:
    """10 veya 12 haneli sayı TCKN değildir; öğrenci numarasını yakalamamalı."""
    assert "1234567890" in mask_pii("Öğrenci no 1234567890")
    assert "123456789012" in mask_pii("Kod 123456789012")


def test_has_pii_tutarlı() -> None:
    assert has_pii("TCKN 12345678901")
    assert not has_pii("yaz okulu kayıt tarihleri")


# --------------------------------------------------------------------------- #
# strip_pii_requests — modelin PII İSTEMESİNİ engelleme
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "satır",
    [
        "T.C. Kimlik Numaranız:",
        "TC Kimlik Numarası: ",
        "TCKN:",
        "Kimlik numaranızı belirtiniz.",
        "Öğrenci numaranız:",
        "Ogrenci numaraniz:",
        "Adınız Soyadınız:",
        "Ad ve Soyad:",
        "Doğum tarihiniz:",
    ],
)
def test_pii_talep_eden_satırlar_kaldırılır(satır: str) -> None:
    gövde = f"Sayın Yetkili,\n\n{satır}\n\nSaygılarımızla."
    sonuç = strip_pii_requests(gövde)
    assert satır.strip() not in sonuç, f"PII talebi kaldı: {sonuç!r}"
    # Gövdenin geri kalanı korunmalı
    assert "Sayın Yetkili," in sonuç
    assert "Saygılarımızla." in sonuç


def test_pii_talebi_olmayan_satır_korunur() -> None:
    gövde = "Transkript belgesi talebimi iletiyorum.\nDers kaydı yaptırdım."
    assert strip_pii_requests(gövde) == gövde


# --------------------------------------------------------------------------- #
# strip_placeholders — doldurulmamış [yer tutucu]
# --------------------------------------------------------------------------- #

def test_yalnız_yer_tutucudan_ibaret_satır_silinir() -> None:
    gövde = "Sayın Yetkili,\n[Adınız Soyadınız]\nTalebim şudur."
    sonuç = strip_placeholders(gövde)
    assert "[Adınız Soyadınız]" not in sonuç
    assert "Talebim şudur." in sonuç


def test_cümle_içi_yer_tutucu_silinir_cümle_korunur() -> None:
    gövde = "Ben [isim], 2024-2025 bahar döneminde kayıtlıyım."
    sonuç = strip_placeholders(gövde)
    assert "[isim]" not in sonuç
    assert "2024-2025 bahar döneminde kayıtlıyım." in sonuç


def test_yer_tutucusuz_metin_değişmez() -> None:
    gövde = "Transkript belgemi talep ediyorum."
    assert strip_placeholders(gövde) == gövde


# --------------------------------------------------------------------------- #
# dedupe_lines / drop_orphan_intros
# --------------------------------------------------------------------------- #

def test_tekrarlanan_uzun_satır_bir_kez_kalır() -> None:
    cümle = "Transkript belgemin tarafıma iletilmesini saygılarımla arz ederim."
    sonuç = dedupe_lines(f"{cümle}\nBaşka bir satır.\n{cümle}")
    assert sonuç.count(cümle) == 1


def test_kısa_satırlar_tekrar_sayılmaz() -> None:
    """İmza, selamlama, madde işareti gibi kısa satırlar tekrarlanabilir."""
    sonuç = dedupe_lines("Merhaba,\n- ders\n- ders\nMerhaba,")
    assert sonuç.count("Merhaba,") == 2


def test_öksüz_giriş_satırı_kaldırılır() -> None:
    """Altındaki maddeler PII temizliğinde silinince giriş satırı öksüz kalır."""
    sonuç = drop_orphan_intros("Lütfen aşağıdaki bilgileri sağlayın:\n\nSaygılarımızla.")
    assert "aşağıdaki bilgileri" not in sonuç


def test_maddesi_olan_giriş_satırı_korunur() -> None:
    gövde = "Lütfen aşağıdaki bilgileri sağlayın:\n- Ders kodu\n- Dönem"
    sonuç = drop_orphan_intros(gövde)
    assert "aşağıdaki bilgileri" in sonuç
    assert "- Ders kodu" in sonuç


# --------------------------------------------------------------------------- #
# sanitize_draft_body — uçtan uca zincir
# --------------------------------------------------------------------------- #

def test_gerçekçi_ihlalli_taslak_temizlenir() -> None:
    """Küçük modellerin ürettiği tipik ihlal kalıbı."""
    ham = """Sayın Öğrenci İşleri,

[Adınız Soyadınız] adına transkript belgesi talep ediyorum.

Lütfen aşağıdaki bilgileri sağlayın:
T.C. Kimlik Numaranız:
Öğrenci Numaranız:

Talebimin değerlendirilmesini arz ederim.
Talebimin değerlendirilmesini arz ederim.

Saygılarımızla."""
    sonuç = sanitize_draft_body(ham)

    # PII talebi gitmeli
    assert "Kimlik" not in sonuç
    assert "Öğrenci Numaranız" not in sonuç
    # Yer tutucu gitmeli
    assert "[" not in sonuç and "]" not in sonuç
    # Öksüz giriş gitmeli
    assert "aşağıdaki bilgileri" not in sonuç
    # Tekrar tekilleşmeli
    assert sonuç.count("Talebimin değerlendirilmesini arz ederim.") == 1
    # Anlamlı içerik korunmalı
    assert "Sayın Öğrenci İşleri," in sonuç
    assert "Saygılarımızla." in sonuç
    assert "transkript belgesi talep ediyorum" in sonuç
    # Üç veya daha fazla ardışık boş satır kalmamalı
    assert "\n\n\n" not in sonuç


def test_temiz_taslak_bozulmaz() -> None:
    """En önemli regresyon koruması: temizlik meşru metni yiyip bitirmemeli."""
    temiz = """Sayın Öğrenci İşleri Daire Başkanlığı,

2024-2025 eğitim öğretim yılı bahar dönemine ait transkript belgemin
tarafıma iletilmesini talep ediyorum.

Gereğini bilgilerinize arz ederim.

Saygılarımızla."""
    sonuç = sanitize_draft_body(temiz)
    assert "transkript belgemin" in sonuç
    assert "2024-2025" in sonuç
    assert "Saygılarımızla." in sonuç
    # Gövdenin kayda değer bir kısmı kaybolmamalı
    assert len(sonuç) > len(temiz) * 0.85


@pytest.mark.parametrize("boş", ["", None])
def test_sanitize_boş_girdide_patlamaz(boş) -> None:
    assert sanitize_draft_body(boş) in ("", None)
