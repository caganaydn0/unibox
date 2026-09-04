"""Öğrenci sohbet oturumu güvenliği.

GÜVENLİK AÇIĞI (düzeltildi): session_token istemciden geliyor, sunucu
üretmiyor ve doğrulamıyordu. Bilinmeyen bir jeton sessizce YENİ oturum
yaratıyordu — yani "1", "test", "admin" göndermek geçerli bir oturum
açıyordu. Jetonu bilen/tahmin eden herkes:
  - GET  /chat/history/{token}  ile başkasının tüm konuşmasını okuyabiliyor,
  - DELETE /chat/session/{token} ile oturumunu silip bağlı draft'ların
    PII'sini temizleyebiliyordu.

Bu testler jeton üretimini, format doğrulamasını ve geçmiş budamayı kapsar.
"""
from __future__ import annotations

import json

import pytest

from app.api.v1.chat import (
    MAX_MESSAGES,
    MAX_MESSAGES_JSON,
    _token_gecerli_mi,
    yeni_session_token,
)


# --------------------------------------------------------------------------- #
# Jeton üretimi ve doğrulaması (saf)
# --------------------------------------------------------------------------- #

def test_uretilen_jeton_tahmin_edilemez_ve_uzun() -> None:
    jeton = yeni_session_token()
    assert _token_gecerli_mi(jeton)
    assert len(jeton) >= 32


def test_uretilen_jetonlar_tekrarlanmaz() -> None:
    assert len({yeni_session_token() for _ in range(200)}) == 200


@pytest.mark.parametrize(
    "tahmin",
    ["1", "test", "admin", "session", "abc", "", "   ", "0" * 10],
)
def test_tahmin_edilebilir_jetonlar_reddedilir(tahmin: str) -> None:
    assert not _token_gecerli_mi(tahmin)


def test_asiri_uzun_jeton_reddedilir() -> None:
    """conversations.session_token String(64); daha uzunu asyncpg'de
    StringDataRightTruncation ile 500 üretiyordu."""
    assert not _token_gecerli_mi("a" * 200)


@pytest.mark.parametrize(
    "bozuk",
    [
        "abc def" + "x" * 30,          # boşluk
        "abc/def" + "x" * 30,          # eğik çizgi
        "'; DROP TABLE conversations--" + "x" * 10,
        "../../etc/passwd" + "x" * 20,
        "abc\ndef" + "x" * 30,         # satır sonu
    ],
)
def test_bozuk_karakterli_jetonlar_reddedilir(bozuk: str) -> None:
    assert not _token_gecerli_mi(bozuk)


# --------------------------------------------------------------------------- #
# Geçmiş budama (saf)
# --------------------------------------------------------------------------- #

class _SahteKonusma:
    """_append_message'ın dokunduğu alanlar."""

    def __init__(self, messages_json: str = "[]") -> None:
        self.messages_json = messages_json
        self.session_token = "x" * 43
        self.last_active_at = None


class _SahteOturum:
    async def commit(self) -> None:
        return None


async def _mesaj_ekle(conv, rol: str, içerik: str) -> None:
    from app.api.v1.chat import _append_message

    await _append_message(_SahteOturum(), conv, rol, içerik)


async def test_gecmis_mesaj_sayisiyla_sinirlanir() -> None:
    conv = _SahteKonusma()
    for i in range(MAX_MESSAGES + 40):
        await _mesaj_ekle(conv, "user", f"mesaj {i}")

    mesajlar = json.loads(conv.messages_json)
    assert len(mesajlar) == MAX_MESSAGES
    # En ESKİLER budanmalı, en yeniler kalmalı
    assert mesajlar[-1]["content"].endswith(str(MAX_MESSAGES + 39))


async def test_gecmis_her_zaman_gecerli_json_kalir() -> None:
    """KIRPMA BUG'I REGRESYONU.

    Eski kod `json.dumps(messages)[:65536]` yazıyordu; sınıra ulaşan bir
    konuşmada JSON ORTASINDAN kesiliyor ve geçersiz hâle geliyordu. Bir
    sonraki mesajda json.loads kalıcı olarak patlıyor, GET /history de kalıcı
    500 dönüyordu — konuşma bir daha asla kullanılamıyordu.
    """
    conv = _SahteKonusma()
    uzun = "ç" * 3000  # çok baytlı karakter: kesme hatasını belirginleştirir

    for _ in range(60):
        await _mesaj_ekle(conv, "user", uzun)
        # HER adımda geçerli JSON olmalı
        mesajlar = json.loads(conv.messages_json)
        assert isinstance(mesajlar, list) and mesajlar

    assert len(conv.messages_json) <= MAX_MESSAGES_JSON


async def test_bozuk_gecmis_kalici_hataya_donusmez() -> None:
    """Halihazırda bozulmuş kayıtlar kurtarılabilmeli."""
    conv = _SahteKonusma(messages_json='[{"role": "user", "content": "yarı')
    await _mesaj_ekle(conv, "user", "yeni mesaj")

    mesajlar = json.loads(conv.messages_json)
    assert mesajlar[-1]["content"] == "yeni mesaj"


async def test_gecmise_yazarken_pii_maskelenir() -> None:
    conv = _SahteKonusma()
    await _mesaj_ekle(conv, "user", "TCKN 12345678901 ve tel 0532 111 22 33")

    kayıt = json.loads(conv.messages_json)[0]["content"]
    assert "12345678901" not in kayıt
    assert "0532" not in kayıt
