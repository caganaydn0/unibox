"""Admin kimlik doğrulaması ve JWT yetkilendirmesi.

İki açık düzeltildi:

1. Parola düz metin ortam değişkeninden okunup `!=` ile karşılaştırılıyordu.
   `!=` erken çıkışlı olduğu için karşılaştırma süresi doğru karakter
   sayısıyla değişiyor (zamanlama sızıntısı). security.py'de bcrypt
   yardımcıları TANIMLIYDI ama hiçbir yerden çağrılmıyordu.

2. get_current_admin, payload["sub"]'ı hiç kontrol etmeden döndürüyordu:
   SECRET_KEY ile imzalanmış `type=access` olan HERHANGİ bir jeton tam admin
   yetkisi veriyordu.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    kimlik_dogrula,
    verify_password,
)


# --------------------------------------------------------------------------- #
# Parola doğrulama
# --------------------------------------------------------------------------- #

def test_bcrypt_ozeti_dogrulanir() -> None:
    özet = hash_password("gizli-parola")
    assert özet != "gizli-parola", "parola düz metin saklanmamalı"
    assert verify_password("gizli-parola", özet)
    assert not verify_password("yanlış", özet)


@pytest.mark.parametrize(
    "parola",
    [
        "şifremŞĞÜÖÇI",          # Türkçe karakterler
        "çok-güçlü-parolaş",
        "boşluk içeren parola",
        "emoji-🔐-parola",
    ],
)
def test_turkce_parolalar_calisir(parola: str) -> None:
    """Türk üniversitesinde Türkçe parola beklenen durum.

    İki ayrı hata vardı: secrets.compare_digest str girdide YALNIZCA ASCII
    kabul edip aksi hâlde TypeError fırlatıyordu (giriş ucu temiz 401 yerine
    500 veriyordu), ve passlib+bcrypt 4.x uyumsuzluğu yüzünden hash_password
    hiç çalışmıyordu.
    """
    özet = hash_password(parola)
    assert verify_password(parola, özet)
    assert not verify_password(parola + "x", özet)
    assert not verify_password("tamamen-başka", özet)


@pytest.mark.parametrize("parola", ["a" * 100, "ğ" * 60])
def test_uzun_parolalar_patlamadan_islenir(parola: str) -> None:
    """72 baytı aşan parolalar hata vermeden hash'lenip doğrulanmalı.

    Türkçe karakterler UTF-8'de 2 bayt tuttuğu için bu sınıra beklenenden
    erken ulaşılıyor: 36 karakterlik bir Türkçe parola zaten 72 bayt.
    Ham bcrypt bu durumda ValueError fırlatıyor; biz kesiyoruz.
    """
    özet = hash_password(parola)
    assert verify_password(parola, özet)
    assert not verify_password("tamamen-başka-parola", özet)


def test_bcrypt_72_bayt_sinirinin_sonucu_belgeleniyor() -> None:
    """bcrypt girdiyi 72 baytta keser — bu evrensel bir bcrypt özelliği.

    Sonucu: 72 bayttan uzun iki parola, ilk 72 baytları aynıysa AYNI kabul
    edilir. Bu bir hata değil, bcrypt'in bilinen sınırı; burada açıkça
    belgeliyoruz ki ileride "güvenlik açığı" sanılıp yanlış düzeltilmesin.
    """
    from app.core.security import BCRYPT_MAX_BYTES

    taban = "x" * BCRYPT_MAX_BYTES
    özet = hash_password(taban)
    assert verify_password(taban + "farklı-kuyruk", özet), (
        "72 bayt sonrası fark bcrypt tarafından görülmez"
    )
    # Sınırın ALTINDAKİ fark elbette görülmeli
    assert not verify_password("x" * (BCRYPT_MAX_BYTES - 1) + "y", özet)


def test_turkce_parola_giriste_500_vermez(monkeypatch) -> None:
    """REGRESYON: sabit zamanlı karşılaştırma non-ASCII'de patlıyordu."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "doğru-şifre")

    assert kimlik_dogrula("admin", "doğru-şifre")
    # Yanlış Türkçe parola: istisna DEĞİL, temiz False dönmeli
    assert not kimlik_dogrula("admin", "yanlış")
    assert not kimlik_dogrula("çağan", "doğru-şifre")


def test_hash_tanimliysa_kullanilir(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", hash_password("doğru-parola"))
    # Düz metin farklı bir değer — hash varken YOK SAYILMALI
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "başka-şey")

    assert kimlik_dogrula("admin", "doğru-parola")
    assert not kimlik_dogrula("admin", "başka-şey")


def test_yanlis_kullanici_adi_reddedilir(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", hash_password("p"))
    assert not kimlik_dogrula("saldirgan", "p")


def test_bozuk_hash_girisi_reddeder(monkeypatch) -> None:
    """Bozuk yapılandırma sistemi AÇIK bırakmamalı."""
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "bu-bir-bcrypt-ozeti-degil")
    assert not kimlik_dogrula("admin", "herhangi")


def test_uretimde_hash_yoksa_giris_reddedilir(monkeypatch) -> None:
    """İkinci savunma hattı: config doğrulaması bir şekilde atlanırsa."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "düz-metin")
    assert not kimlik_dogrula("admin", "düz-metin")


def test_gelistirmede_duz_metin_calisir(monkeypatch) -> None:
    """Geliştirme akışı bozulmamalı."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "dev-parola")
    assert kimlik_dogrula("admin", "dev-parola")
    assert not kimlik_dogrula("admin", "yanlış")


# --------------------------------------------------------------------------- #
# JWT özne doğrulaması
# --------------------------------------------------------------------------- #

async def _admin_al(jeton: str) -> str:
    from app.deps import get_current_admin

    return await get_current_admin(token=jeton)


async def test_gecerli_jeton_kabul_edilir(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    assert await _admin_al(create_access_token("admin")) == "admin"


async def test_baska_ozneli_jeton_reddedilir(monkeypatch) -> None:
    """ASIL AÇIK: aynı SECRET_KEY ile imzalanmış ama öznesi farklı bir jeton.

    Örneğin öğrenci tarafı için üretilmiş ya da başka bir amaçla imzalanmış
    bir jeton, eskiden tam admin yetkisi veriyordu.
    """
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    sahte = create_access_token("saldirgan")

    with pytest.raises(HTTPException) as hata:
        await _admin_al(sahte)
    assert hata.value.status_code == 401


async def test_refresh_jetonu_access_yerine_kullanilamaz(monkeypatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    with pytest.raises(HTTPException):
        await _admin_al(create_refresh_token("admin"))


async def test_bozuk_jeton_reddedilir() -> None:
    from fastapi import HTTPException

    for bozuk in ("", "abc", "a.b.c", "Bearer x"):
        with pytest.raises(HTTPException):
            await _admin_al(bozuk)


def test_access_jetonu_refresh_olarak_cozulmez() -> None:
    from app.core.security import decode_refresh_token

    assert decode_refresh_token(create_access_token("admin")) is None
    assert decode_access_token(create_refresh_token("admin")) is None
