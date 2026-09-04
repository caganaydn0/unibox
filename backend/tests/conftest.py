"""Ortak pytest yapılandırması.

Testler üç kategoriye ayrılır:

- işaretsiz : saf fonksiyonlar. Postgres, Ollama veya ağ gerektirmez.
              CI'da her commit'te koşar.
- rag_eval  : canlı Postgres + Ollama ve indekslenmiş fixture korpusu ister.
- slow      : ayrıca LLM üretimi yapar; dakikalar sürer, tam deterministik değil.

Servis gerektiren testler, servis yoksa BAŞARISIZ OLMAZ — atlanır. Amaç,
geliştirici makinesinde Docker kapalıyken de saf testlerin koşabilmesi.
"""
from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

# --------------------------------------------------------------------------- #
# ÖLÇÜM VERİTABANINA YÖNLENDİRME — app içe aktarılmadan ÖNCE olmalı
# --------------------------------------------------------------------------- #
# Testler asla geliştirme verisine dokunmamalı. İki sebeple:
#   1. Ölçüm, o anki geliştirme korpusuna göre değişirse tekrarlanamaz.
#   2. Testler tablo siliyor; yanlış veritabanında çalışması veri kaybıdır.
#
# pydantic-settings ortam değişkenini .env dosyasının ÜSTÜNDE tutar, bu yüzden
# burada DATABASE_URL'i ezmek app.config içe aktarılırken geçerli olur.
# db/session.py motoru modül seviyesinde kurduğu için sıra kritik: bu blok
# conftest'in en üstünde, herhangi bir `app.*` importundan önce çalışır.
def _eval_db_url_kur() -> None:
    # db/session.py: echo=(APP_ENV == "development") — SQLAlchemy o zaman HER
    # sorguyu bağlı parametreleriyle loglar; 1024 boyutlu embedding vektörleri
    # dahil. Test çıktısını okunamaz hâle getiriyor, ayrıca PII sızdırma yolu.
    # Motor modül seviyesinde kurulduğu için bunu import'tan önce ayarlamalıyız.
    os.environ.setdefault("APP_ENV", "test")

    if os.environ.get("UNIBOX_TEST_USE_DEV_DB"):
        return  # bilinçli devre dışı bırakma
    # .env'i settings'e dokunmadan okumak için minimal ayrıştırma
    ana = os.environ.get("DATABASE_URL")
    if not ana:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for satır in env.read_text(encoding="utf-8").splitlines():
                if satır.startswith("DATABASE_URL="):
                    ana = satır.split("=", 1)[1].strip()
                    break
    if not ana:
        ana = "postgresql+asyncpg://postgres:postgres@localhost:5432/unibox"
    p = urlparse(ana)
    os.environ["DATABASE_URL"] = urlunparse(p._replace(path="/unibox_eval"))


_eval_db_url_kur()

# SQLAlchemy echo, APP_ENV=development iken her sorguyu bağlı parametreleriyle
# loglar — 1024 boyutlu embedding vektörleri dahil. Test çıktısını okunamaz
# hale getiriyor, ayrıca PII sızdırma riski taşıyor.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_path(*parts: str) -> Path:
    """Fixture dosyasına mutlak yol.

    Scriptlerdeki sabit Windows yollarının (unibox_outputs\\...) yerini alır;
    repoyu klonlayan herkeste aynı şekilde çalışır.
    """
    return FIXTURES.joinpath(*parts)


def _port_açık(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _postgres_ayakta() -> bool:
    from app.config import settings

    # postgresql+asyncpg://user:pass@host:port/db
    p = urlparse(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    return _port_açık(p.hostname or "localhost", p.port or 5432)


def _ollama_ayakta() -> bool:
    from app.config import settings

    p = urlparse(settings.OLLAMA_BASE_URL)
    return _port_açık(p.hostname or "localhost", p.port or 11434)


def pytest_collection_modifyitems(config, items):
    """rag_eval / slow testlerini, gerekli servis yoksa atla."""
    if os.environ.get("UNIBOX_TEST_REQUIRE_SERVICES"):
        return  # CI'da servisler garantiyse atlamayı devre dışı bırak

    canlı_gerekiyor = [i for i in items if "rag_eval" in i.keywords or "slow" in i.keywords]
    if not canlı_gerekiyor:
        return

    eksik = []
    if not _postgres_ayakta():
        eksik.append("Postgres")
    if not _ollama_ayakta():
        eksik.append("Ollama")
    if not eksik:
        return

    atla = pytest.mark.skip(
        reason=f"{' ve '.join(eksik)} erişilemiyor — `docker compose up -d` "
        f"ve Ollama'yı başlatın. Zorlamak için: UNIBOX_TEST_REQUIRE_SERVICES=1"
    )
    for item in canlı_gerekiyor:
        item.add_marker(atla)


@pytest.fixture(scope="session")
async def korpus():
    """Sabit ölçüm korpusu — oturum başına bir kez kurulur.

    Fixture içeriği ve chunk/embedding ayarları değişmediyse yeniden
    indekslemez (bge-m3 ile ~250 chunk gömmek 1-3 dakika sürer).
    Zorla yeniden kurmak için: UNIBOX_EVAL_REBUILD=1
    """
    from tests.rag.corpus import corpus

    bilgi = await corpus()
    print(
        f"\n[korpus] {bilgi.doküman_sayısı} doküman / {bilgi.chunk_sayısı} chunk "
        f"· damga {bilgi.damga} · "
        f"{'YENİDEN KURULDU' if bilgi.yeniden_kuruldu else 'önbellekten'}"
    )
    return bilgi
