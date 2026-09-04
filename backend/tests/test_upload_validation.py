"""Doküman yükleme doğrulaması.

Üç açık kapatıldı:
  - Boyut sınırı dosya TAMAMEN okunduktan SONRA uygulanıyordu.
  - MIME yalnızca istemcinin Content-Type başlığından alınıyordu; python-magic
    bağımlılık olarak duruyor ama hiçbir yerden import edilmiyordu.
  - tags alanı doğrulanmadan tags_json'a yazılıyor, bozuk JSON arama
    sırasında sessizce []'ye düşüyordu.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api.v1.knowledge import _dogrulanmis_etiketler, _dogrulanmis_mime

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
DOCX = b"PK\x03\x04" + b"\x00" * 40


# --------------------------------------------------------------------------- #
# MIME doğrulama
# --------------------------------------------------------------------------- #

def test_pdf_imzasindan_taninir() -> None:
    assert _dogrulanmis_mime(PDF, "application/pdf", "a.pdf") == "application/pdf"


def test_yanlis_content_type_imzayla_duzeltilir() -> None:
    """İstemcinin bildirdiği tip yanlış olabilir; imza önceliklidir."""
    assert _dogrulanmis_mime(PDF, "text/plain", "belge.txt") == "application/pdf"


def test_docx_zip_imzasindan_taninir() -> None:
    mime = _dogrulanmis_mime(DOCX, "application/octet-stream", "a.docx")
    assert "wordprocessingml" in mime


def test_uzantidan_taninan_metin_dosyalari() -> None:
    metin = "Yaz okulu esasları".encode("utf-8")
    assert _dogrulanmis_mime(metin, None, "rehber.txt") == "text/plain"
    assert _dogrulanmis_mime(metin, None, "rehber.md") == "text/markdown"


@pytest.mark.parametrize(
    "içerik, mime, ad",
    [
        (b"MZ\x90\x00", "application/pdf", "kotu.exe"),          # Windows PE
        (b"\x7fELF", "text/plain", "kotu.bin"),                  # Linux ELF
        (b"\x89PNG\r\n", "application/pdf", "resim.png"),        # PNG
    ],
)
def test_izinsiz_tipler_reddedilir(içerik: bytes, mime: str, ad: str) -> None:
    """Sahte Content-Type ile izinsiz dosya geçirilememeli."""
    with pytest.raises(HTTPException) as hata:
        _dogrulanmis_mime(içerik, mime, ad)
    assert hata.value.status_code == 415


def test_metin_gibi_gorunmeyen_dosya_reddedilir() -> None:
    """İkili içerik .txt adıyla girip indekslemede FAILED olmasın."""
    with pytest.raises(HTTPException) as hata:
        _dogrulanmis_mime(b"veri\x00\x00ikili", "text/plain", "sahte.txt")
    assert hata.value.status_code == 415


def test_gercek_fixture_pdf_kabul_edilir() -> None:
    from tests.conftest import fixture_path

    ham = fixture_path("mevzuat", "gazi_lisansustu_yonetmelik.pdf").read_bytes()
    assert _dogrulanmis_mime(ham, "application/pdf", "y.pdf") == "application/pdf"


# --------------------------------------------------------------------------- #
# tags doğrulama
# --------------------------------------------------------------------------- #

def test_gecerli_etiketler_korunur() -> None:
    sonuç = _dogrulanmis_etiketler('["transcript_request", "grade_objection"]')
    assert json.loads(sonuç) == ["transcript_request", "grade_objection"]


def test_bos_etiket_varsayilani() -> None:
    assert json.loads(_dogrulanmis_etiketler("")) == []
    assert json.loads(_dogrulanmis_etiketler("[]")) == []


def test_turkce_etiketler_kacisla_bozulmaz() -> None:
    sonuç = _dogrulanmis_etiketler('["kayıt_dondurma"]')
    assert "kayıt_dondurma" in sonuç


@pytest.mark.parametrize(
    "bozuk",
    [
        "{bozuk json",
        '{"bu": "dizi degil"}',
        '[1, 2, 3]',              # sayı öğeler
        '["gecerli", 42]',        # karışık
        '"sadece-string"',
    ],
)
def test_bozuk_etiketler_yuklemede_reddedilir(bozuk: str) -> None:
    """Sessiz kayıp yerine erken hata.

    Eskiden bozuk JSON doğrudan tags_json'a yazılıyor, arama sırasında
    rag_engine'deki geniş except ile sessizce []'ye düşüyordu — etiketler
    kayboluyor ama kimse fark etmiyordu.
    """
    with pytest.raises(HTTPException) as hata:
        _dogrulanmis_etiketler(bozuk)
    assert hata.value.status_code == 422
