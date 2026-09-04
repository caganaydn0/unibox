"""Dokümanları mevcut chunk ayarlarıyla yeniden indeksler.

Neden gerekli:
    Bilgi tabanında iki farklı granülerlik yan yana duruyordu — eski taranmış
    PDF'ler ortalama 2330 karakterlik chunk'lara, sonradan eklenen metin
    dokümanları 371 karakterlik chunk'lara bölünmüştü. Uzun chunk'lar hem
    tam metin aramasında (daha çok kelime barındırdıkları için) hem de
    bağlam penceresinde kısa ve konuya birebir uyan dokümanları bastırıyordu.

    RAG_CHUNK_SIZE değiştirildikten sonra bu script mevcut dokümanları yeni
    ayarla yeniden böler ve yeniden embed eder.

Kullanım:
    cd backend && uv run python ../scripts/reindex_documents.py            # hepsi
    cd backend && uv run python ../scripts/reindex_documents.py --pdf-only # sadece PDF'ler
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models.document_chunk import DocumentChunk  # noqa: E402
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-only", action="store_true", help="yalnızca PDF dokümanları")
    args = ap.parse_args()

    async with AsyncSessionLocal() as s:
        # INDEXED olmayanları da al: yarıda kalmış (PROCESSING) veya hata almış
        # (FAILED) dokümanlar aksi halde bir daha hiç denenemez.
        q = select(KnowledgeDocument).where(
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status.in_([
                ProcessingStatus.INDEXED,
                ProcessingStatus.PROCESSING,
                ProcessingStatus.FAILED,
                ProcessingStatus.PENDING,
            ]),
        )
        if args.pdf_only:
            q = q.where(KnowledgeDocument.mime_type != "text/plain")
        docs = list((await s.execute(q)).scalars())

    print(f"Chunk boyutu : {settings.RAG_CHUNK_SIZE} kelime (~{settings.RAG_CHUNK_SIZE * 5} karakter)")
    print(f"İşlenecek    : {len(docs)} doküman")
    print("-" * 60)

    rag = RagEngine()
    for d in docs:
        önce = d.chunk_count
        try:
            if d.mime_type == "text/plain":
                await _reindex_text(rag, d.id)
            else:
                await rag.index_document(d.id)
        except Exception as exc:
            print(f"  HATA {d.original_filename}: {exc}")
            continue

        async with AsyncSessionLocal() as s:
            sonra = await s.scalar(
                select(func.count()).select_from(DocumentChunk).where(
                    DocumentChunk.document_id == d.id
                )
            )
        print(f"  {d.original_filename[:45]:47s} {önce:3d} -> {sonra:3d} chunk")

    async with AsyncSessionLocal() as s:
        toplam = await s.scalar(select(func.count()).select_from(DocumentChunk))
        ort = await s.scalar(select(func.avg(func.length(DocumentChunk.content))))
    print("-" * 60)
    print(f"Toplam chunk : {toplam}   ortalama uzunluk: {round(ort)} karakter")


async def _reindex_text(rag: RagEngine, doc_id: str) -> None:
    """Metin dokümanları için yeniden bölme — index_document PDF varsayıyor."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlalchemy import delete

    async with AsyncSessionLocal() as s:
        doc = await s.get(KnowledgeDocument, doc_id)
        metin = doc.file_data.decode("utf-8")
        await s.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))

        parçalar = rag.split_text(metin)
        for i, p in enumerate(parçalar):
            s.add(DocumentChunk(
                id=str(uuid4()), document_id=doc_id, chunk_index=i, content=p,
                embedding=await rag.embed_text(p), tags_json=doc.tags_json,
                word_count=len(p.split()),
            ))
        doc.chunk_count = len(parçalar)
        doc.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await s.commit()


if __name__ == "__main__":
    asyncio.run(main())
