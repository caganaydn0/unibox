"""Üretim yapılandırması güvenlik doğrulaması.

SECRET_KEY ve FERNET_KEY'in kaynak koddaki şablon değerleri "varsayılan"
değil, BİLİNEN SABİTLERDİR: SECRET_KEY bilinirse herkes geçerli bir admin
JWT'si imzalayabilir, FERNET_KEY bilinirse veritabanındaki şifreli verinin
tamamı okunabilir. Uygulama bu değerlerle sessizce açılıyordu.
"""
from __future__ import annotations

import pytest

from app.config import Settings

# Doğrulamayı geçen minimum geçerli yapılandırma
GEÇERLİ = {
    "APP_ENV": "production",
    "SECRET_KEY": "x" * 48,
    "FERNET_KEY": "3n8Zk7Yl0pQrStUvWxYz1234567890AbCdEfGhIjKlM=",
    # Üretimde düz metin parola kabul edilmiyor; bcrypt özeti şart
    "ADMIN_PASSWORD_HASH": "$2b$12$" + "a" * 53,
    "SMTP_BACKEND": "smtp",
}


@pytest.fixture(autouse=True)
def _cevre_dosyasi_var_olsun(tmp_path, monkeypatch):
    """_uretimde_guvenli_mi, backend/.env'in diskte GERÇEKTEN var olup
    olmadığını da kontrol ediyor. `_ayarlar()`'daki `_env_file=None` yalnızca
    pydantic'in o dosyadan DEĞER okumasını engelliyor — dosyanın var olup
    olmadığı kontrolünü etkilemiyor. Geliştirici makinesinde backend/.env
    gerçekten var olduğu için bu görünmüyordu; CI'da (temiz checkout, .env
    hiç yok) bu modüldeki testler SECRET_KEY/FERNET_KEY/parola/SMTP
    kurallarını değil, farkında olmadan bu dosya kontrolünü test edip
    başarısız oluyordu. Gerçek bir geçici dosya oluşturup _ENV_DOSYASI'nı
    ona yönlendiriyoruz — mock değil, gerçek bir dosya.
    """
    sahte_env = tmp_path / ".env"
    sahte_env.touch()
    monkeypatch.setattr("app.config._ENV_DOSYASI", sahte_env)


def _ayarlar(**değişiklik) -> Settings:
    # _env_file=None: geliştirici makinesindeki backend/.env testi etkilemesin
    return Settings(_env_file=None, **{**GEÇERLİ, **değişiklik})


def test_gecerli_uretim_yapilandirmasi_kabul_edilir() -> None:
    ayar = _ayarlar()
    assert ayar.APP_ENV == "production"


@pytest.mark.parametrize(
    "alan, değer",
    [
        ("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION"),
        ("SECRET_KEY", "CHANGE_ME_RANDOM_32_CHARS"),
        ("FERNET_KEY", "CHANGE_ME_FERNET_KEY"),
    ],
)
def test_sablon_degerler_uretimde_reddedilir(alan: str, değer: str) -> None:
    with pytest.raises(ValueError) as hata:
        _ayarlar(**{alan: değer})
    assert alan in str(hata.value)


def test_uretimde_duz_metin_parola_reddedilir() -> None:
    """Düz metin parola ortam değişkeninde durursa süreç listesinden,
    çekirdek dökümünden ve yedeklerden okunabilir."""
    with pytest.raises(ValueError, match="ADMIN_PASSWORD_HASH"):
        _ayarlar(ADMIN_PASSWORD_HASH="", ADMIN_PASSWORD="düz-metin-parola")


def test_kisa_secret_key_reddedilir() -> None:
    with pytest.raises(ValueError, match="32 karakter"):
        _ayarlar(SECRET_KEY="kısa")


def test_uretimde_console_smtp_reddedilir() -> None:
    """SMTP_BACKEND varsayılanı 'console'; üretimde unutulursa e-posta gitmez."""
    with pytest.raises(ValueError, match="console"):
        _ayarlar(SMTP_BACKEND="console")


def test_gelistirmede_sablon_degerler_serbest() -> None:
    """Doğrulama yalnızca production'da uygulanmalı — dev akışını bozmamalı."""
    ayar = Settings(
        _env_file=None,
        APP_ENV="development",
        SECRET_KEY="CHANGE_ME_IN_PRODUCTION",
        FERNET_KEY="CHANGE_ME_FERNET_KEY",
        ADMIN_PASSWORD="CHANGE_ME",
        SMTP_BACKEND="console",
    )
    assert ayar.APP_ENV == "development"


def test_hata_mesaji_tum_sorunlari_birden_listeler() -> None:
    """Tek tek düzeltip yeniden çalıştırmak yerine hepsini bir kerede görün."""
    with pytest.raises(ValueError) as hata:
        _ayarlar(SECRET_KEY="CHANGE_ME_IN_PRODUCTION", FERNET_KEY="CHANGE_ME_FERNET_KEY")
    metin = str(hata.value)
    assert "SECRET_KEY" in metin and "FERNET_KEY" in metin


# --------------------------------------------------------------------------- #
# CORS
# --------------------------------------------------------------------------- #

def test_cors_listesi_virgulle_ayrilir() -> None:
    ayar = _ayarlar(CORS_ORIGINS="https://a.edu.tr, https://b.edu.tr")
    assert ayar.cors_origin_listesi == ["https://a.edu.tr", "https://b.edu.tr"]


def test_cors_bos_birakilirsa_uretimde_hicbir_origin_acilmaz() -> None:
    assert _ayarlar(CORS_ORIGINS="").cors_origin_listesi == []


def test_cors_gelistirmede_localhost_varsayilir() -> None:
    ayar = Settings(_env_file=None, APP_ENV="development", CORS_ORIGINS="")
    assert ayar.cors_origin_listesi == ["http://localhost:3000"]
