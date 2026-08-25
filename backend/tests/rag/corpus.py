"""Tekrarlanabilir ölçüm korpusu.

SORUN: Mevcut eval scriptleri ölçümü GELİŞTİRME veritabanına karşı yapıyordu.
O veritabanının içeriği zamanla değişiyor (bugün 29 doküman / 54 chunk), dolayısıyla
"recall@3 %75" gibi bir sayı hangi korpusa karşı ölçüldüğü bilinmeden anlamsız ve
başka bir makinede yeniden üretilemez.

ÇÖZÜM: Ölçümler ayrı bir veritabanında (`unibox_eval`), yalnızca repodaki
fixture'lardan kurulmuş sabit bir korpusa karşı koşar. Geliştirme verisi hiç
görünmez; korpus her makinede birebir aynıdır.

Korpus fixture içeriğinin sha256'sıyla damgalanır. İçerik değişmediyse yeniden
indeksleme yapılmaz (bge-m3 ile ~250 chunk gömmek 1-3 dakika sürüyor).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

logger = logging.getLogger(__name__)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EVAL_DB_NAME = "unibox_eval"

# Korpus damgasının yazıldığı yer — geçerli bir doküman satırı değil, bu yüzden
# aramaya karışmasın diye ayrı bir tabloya değil, kendi meta satırına yazıyoruz.
DAMGA_DOSYASI = "__corpus_stamp__"


@dataclass(frozen=True)
class CorpusInfo:
    doküman_sayısı: int
    chunk_sayısı: int
    damga: str
    yeniden_kuruldu: bool


# --------------------------------------------------------------------------- #
# Veritabanı adresi
# --------------------------------------------------------------------------- #

def eval_database_url(base_url: str | None = None) -> str:
    """Ölçüm veritabanının URL'i — ana URL'in yalnızca db adı değiştirilmiş hâli."""
    if base_url is None:
        from app.config import settings
        base_url = settings.DATABASE_URL
    p = urlparse(base_url)
    return urlunparse(p._replace(path=f"/{EVAL_DB_NAME}"))


def aktif_eval_db_mi() -> bool:
    """settings gerçekten ölçüm veritabanına mı bakıyor?

    conftest, app içe aktarılmadan ÖNCE DATABASE_URL ortam değişkenini
    ayarlar. Bu yapılmadıysa testler yanlışlıkla geliştirme verisini ölçer —
    o yüzden sessizce devam etmek yerine erken ve gürültülü başarısız oluruz.
    """
    from app.config import settings
    return urlparse(settings.DATABASE_URL).path.lstrip("/") == EVAL_DB_NAME


# --------------------------------------------------------------------------- #
# Şema kurulumu
# --------------------------------------------------------------------------- #

async def ensure_database() -> None:
    """Ölçüm veritabanı yoksa oluşturur (bakım bağlantısı üzerinden)."""
    import asyncpg

    from app.config import settings

    p = urlparse(settings.DATABASE_URL)
    bakım = urlunparse(p._replace(path="/postgres")).replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(bakım)
    try:
        var = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", EVAL_DB_NAME)
        if not var:
            # asyncpg CREATE DATABASE'i transaction dışında ister
            await conn.execute(f'CREATE DATABASE "{EVAL_DB_NAME}"')
            logger.info("Ölçüm veritabanı oluşturuldu: %s", EVAL_DB_NAME)
    finally:
        await conn.close()


def run_migrations() -> None:
    """Alembic zincirini ölçüm veritabanına uygular.

    Base.metadata.create_all KULLANMIYORUZ: 0002 (pgvector), 0005 (Türkçe FTS
    GIN indeksi) ve 0006 (1024 boyut + HNSW) ham SQL ile yazılmış ve create_all
    yolunda HİÇ uygulanmaz. O indeksler olmadan hibrit arama sessizce bozulur
    ve ölçüm yanlış olur. Ayrıca bu, migration zincirini de test etmiş olur.

    ALT SÜREÇTE çalıştırıyoruz, `from alembic import command` ile DEĞİL:
    pytest yapılandırması backend/ dizinini sys.path'e koyuyor ve oradaki
    `alembic/` migration klasörü kurulu `alembic` PAKETİNİ gölgeliyor
    (ImportError: cannot import name 'command'). Konsol scripti cwd'yi
    sys.path'e eklemediği için bu sorundan etkilenmez — zaten geliştiricinin
    elle çalıştırdığı yol da bu.
    """
    import shutil
    import subprocess
    import sys

    backend = Path(__file__).resolve().parent.parent.parent
    exe = shutil.which("alembic") or str(Path(sys.executable).parent / "alembic")

    sonuç = subprocess.run(
        [exe, "upgrade", "head"],
        cwd=str(backend),
        env={**os.environ},  # DATABASE_URL conftest tarafından eval db'ye çevrildi
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if sonuç.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head başarısız (çıkış {sonuç.returncode}):\n"
            f"{sonuç.stdout}\n{sonuç.stderr}"
        )


# --------------------------------------------------------------------------- #
# Fixture yükleme
# --------------------------------------------------------------------------- #

def _fixture_damgası() -> str:
    """Tüm fixture içeriğinin ve korpusu ETKİLEYEN her şeyin tek özeti.

    DİKKAT: Korpusun içeriğini değiştirebilecek HER GİRDİ buraya girmeli.
    Chunker sürümü başta unutulmuştu ve madde-farkındalıklı bölmeye geçişte
    damga değişmediği için korpus önbellekten gelmeye devam etti; ölçüm
    sessizce ESKİ chunk'lara karşı yapıldı. Yeni bir bölme parametresi
    eklerken bu listeyi güncellemeyi unutmayın.
    """
    from app.config import settings
    from app.services.chunking import CHUNKER_SURUMU

    h = hashlib.sha256()
    for yol in sorted(FIXTURES.rglob("*")):
        if yol.is_file() and yol.suffix in {".pdf", ".jsonl"}:
            h.update(yol.name.encode("utf-8"))
            h.update(yol.read_bytes())
    for ayar in (settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS,
                 settings.RAG_CHUNK_SIZE, settings.RAG_CHUNK_OVERLAP,
                 CHUNKER_SURUMU):
        h.update(str(ayar).encode("utf-8"))
    return h.hexdigest()[:16]


async def _mevcut_damga() -> str | None:
    from sqlalchemy import select

    from app.db.models.knowledge_document import KnowledgeDocument
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        return await s.scalar(
            select(KnowledgeDocument.description).where(
                KnowledgeDocument.filename == DAMGA_DOSYASI
            )
        )


async def _korpusu_temizle() -> None:
    from sqlalchemy import delete

    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.knowledge_document import KnowledgeDocument
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(delete(DocumentChunk))
        await s.execute(delete(KnowledgeDocument))
        await s.commit()


async def _doküman_ekle(rag, *, başlık: str, içerik: str, ham: bytes,
                        mime: str, etiketler: list[str]) -> int:
    """Tek dokümanı chunk'layıp gömer. Eklenen chunk sayısını döner."""
    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    doc_id = str(uuid4())
    şimdi = datetime.now(timezone.utc).replace(tzinfo=None)
    # split_with_meta: üretim yolunun aynısı. split_text kullanmak meta
    # veriyi düşürür ve korpus üretimden farklı olurdu.
    parçalar = rag.split_with_meta(içerik)
    etiket_json = json.dumps(etiketler, ensure_ascii=False)

    gömüler = [await rag.embed_text(p.icerik) for p in parçalar]

    async with AsyncSessionLocal() as s:
        s.add(KnowledgeDocument(
            id=doc_id,
            filename=başlık,
            original_filename=başlık,
            description=başlık,
            mime_type=mime,
            file_size_bytes=len(ham),
            file_data=ham,
            sha256_hash=hashlib.sha256(ham).hexdigest(),
            tags_json=etiket_json,
            status=ProcessingStatus.INDEXED,
            chunk_count=len(parçalar),
            indexed_at=şimdi,
            uploaded_by="eval_fixture",
        ))
        for i, (parça, gömü) in enumerate(zip(parçalar, gömüler)):
            s.add(DocumentChunk(
                id=str(uuid4()), document_id=doc_id, chunk_index=i,
                content=parça.icerik, embedding=gömü, tags_json=etiket_json,
                meta_json=parça.meta, word_count=len(parça.icerik.split()),
            ))
        await s.commit()
    return len(parçalar)


async def _damga_yaz(damga: str) -> None:
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        s.add(KnowledgeDocument(
            id=str(uuid4()),
            filename=DAMGA_DOSYASI,
            original_filename=DAMGA_DOSYASI,
            description=damga,
            mime_type="text/plain",
            file_size_bytes=0,
            file_data=b"",
            sha256_hash=hashlib.sha256(damga.encode()).hexdigest(),
            tags_json="[]",
            # PENDING: search() yalnızca INDEXED dokümanlara bakar, bu satır
            # aramaya asla karışmaz.
            status=ProcessingStatus.PENDING,
            chunk_count=0,
            uploaded_by="eval_fixture",
        ))
        await s.commit()


async def ensure_corpus(zorla: bool = False) -> CorpusInfo:
    """Fixture korpusunu kurar. İçerik değişmediyse hiçbir şey yapmaz."""
    from sqlalchemy import func, select

    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal
    from app.services.rag_engine import RagEngine

    if not aktif_eval_db_mi():
        raise RuntimeError(
            "Testler ölçüm veritabanına yönlendirilmemiş — geliştirme verisini "
            "ölçmek üzeresiniz. conftest.py'nin DATABASE_URL'i ayarladığından emin olun."
        )

    await ensure_database()
    run_migrations()

    damga = _fixture_damgası()
    if not zorla and await _mevcut_damga() == damga:
        async with AsyncSessionLocal() as s:
            d = await s.scalar(
                select(func.count()).select_from(KnowledgeDocument)
                .where(KnowledgeDocument.status == ProcessingStatus.INDEXED)
            )
            c = await s.scalar(select(func.count()).select_from(DocumentChunk))
        return CorpusInfo(d or 0, c or 0, damga, yeniden_kuruldu=False)

    await _korpusu_temizle()
    rag = RagEngine()
    doküman, chunk = 0, 0

    # 1. Yönetmelik PDF'leri
    for pdf in sorted((FIXTURES / "mevzuat").glob("*.pdf")):
        ham = pdf.read_bytes()
        metin = rag.extract_text_from_pdf(ham)
        chunk += await _doküman_ekle(
            rag, başlık=pdf.stem, içerik=metin, ham=ham,
            mime="application/pdf", etiketler=[],
        )
        doküman += 1

    # 2. Kısa rehber metinleri (JSONL)
    kb = FIXTURES / "knowledge_base.jsonl"
    if kb.exists():
        for satır in kb.read_text(encoding="utf-8").splitlines():
            if not satır.strip():
                continue
            kayıt = json.loads(satır)
            içerik = kayıt["content"]
            chunk += await _doküman_ekle(
                rag, başlık=kayıt["title"], içerik=içerik,
                ham=içerik.encode("utf-8"), mime="text/plain",
                etiketler=kayıt.get("tags", []),
            )
            doküman += 1

    await _damga_yaz(damga)
    return CorpusInfo(doküman, chunk, damga, yeniden_kuruldu=True)


# Test oturumu boyunca bir kez kurulsun diye basit önbellek
_ÖNBELLEK: CorpusInfo | None = None


async def corpus() -> CorpusInfo:
    global _ÖNBELLEK
    if _ÖNBELLEK is None:
        _ÖNBELLEK = await ensure_corpus(zorla=bool(os.environ.get("UNIBOX_EVAL_REBUILD")))
    return _ÖNBELLEK
