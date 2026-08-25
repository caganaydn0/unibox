"""Ölçüm korpusunun doğru kurulduğunu doğrular.

Diğer tüm rag_eval testleri bu korpusa dayanıyor. Korpus sessizce yanlış
kurulursa (eksik indeks, boş embedding, geliştirme verisine bağlanma) her
ölçüm yanlış çıkar ve bunu fark etmek zor olur. Bu testler o hatayı erken
ve gürültülü hâle getirir.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.rag_eval


async def test_korpus_ölçüm_veritabanında_kuruldu(korpus) -> None:
    """En kritik güvence: geliştirme verisini ölçmüyoruz."""
    from tests.rag.corpus import EVAL_DB_NAME, aktif_eval_db_mi

    assert aktif_eval_db_mi(), (
        "Testler geliştirme veritabanına bakıyor — ölçümler tekrarlanamaz "
        f"ve tablo silme işlemleri veri kaybına yol açar. Beklenen: {EVAL_DB_NAME}"
    )
    assert korpus.doküman_sayısı > 0
    assert korpus.chunk_sayısı > 0


async def test_beklenen_dokümanlar_var(korpus) -> None:
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        adlar = set(
            (await s.execute(
                select(KnowledgeDocument.description).where(
                    KnowledgeDocument.status == ProcessingStatus.INDEXED
                )
            )).scalars()
        )

    # eval_regulation.py'nin hedefi — bu doküman yoksa ölçüm sessizce %0 verir
    assert "gazi_lisansustu_yonetmelik" in adlar
    assert "lisans_ogrenimine_devam_yonetmelik" in adlar
    assert "yabanci_dil_hazirlik_yonetmelik" in adlar
    # Kısa rehber metinlerinden en az biri
    assert len(adlar) >= 20, f"beklenenden az doküman: {len(adlar)}"


async def test_tüm_chunklarda_doğru_boyutta_embedding_var(korpus) -> None:
    """0006 sonrası reindex atlanırsa embedding NULL kalır ve RAG boş döner."""
    from app.config import settings
    from app.db.models.document_chunk import DocumentChunk
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        toplam = await s.scalar(select(func.count()).select_from(DocumentChunk))
        boş = await s.scalar(
            select(func.count()).select_from(DocumentChunk)
            .where(DocumentChunk.embedding.is_(None))
        )
        boyut = await s.scalar(
            text("SELECT vector_dims(embedding) FROM document_chunks "
                 "WHERE embedding IS NOT NULL LIMIT 1")
        )

    assert boş == 0, f"{boş}/{toplam} chunk embedding'siz"
    assert boyut == settings.EMBEDDING_DIMENSIONS


async def test_hibrit_arama_indeksleri_mevcut(korpus) -> None:
    """0005 (Türkçe FTS GIN) ve 0006 (HNSW) uygulanmış olmalı.

    create_all bu ham SQL migration'larını atlar; atlanırsa arama çalışmaya
    devam eder ama yavaşlar ve ts_rank davranışı değişir — sessiz bir bozulma.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        indeksler = set((await s.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'document_chunks'")
        )).scalars())

    assert "ix_document_chunks_content_fts_tr" in indeksler, "0005 uygulanmamış"
    assert "ix_document_chunks_embedding_cosine" in indeksler, "0006 uygulanmamış"


async def test_arama_uçtan_uca_sonuç_döndürüyor(korpus) -> None:
    from app.services.rag_engine import RagEngine

    parçalar = await RagEngine().search("Doktora yeterlik sınavı ne zaman yapılır?")
    assert parçalar, "hibrit arama hiç sonuç döndürmedi"
    assert all(içerik.strip() for içerik, _, _ in parçalar)


async def test_korpus_idempotent(korpus) -> None:
    """İkinci çağrı yeniden indekslememeli — yoksa her test koşusu dakikalar sürer."""
    from tests.rag.corpus import ensure_corpus

    tekrar = await ensure_corpus()
    assert not tekrar.yeniden_kuruldu
    assert tekrar.damga == korpus.damga
    assert tekrar.chunk_sayısı == korpus.chunk_sayısı
