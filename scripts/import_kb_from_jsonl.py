"""Bilgi tabanını JSONL'den içe aktar.

unibox_outputs/knowledge_base_raw.jsonl dosyasındaki Türkçe rehber metinlerini
knowledge_base_documents + document_chunks tablolarına yazar.

Neden hazır vektörleri (kb_chunks_with_vectors.jsonl) kullanmıyoruz:
  Ölçtük — o dosyadaki vektörler uygulamanın kendi embed_text() çıktısıyla
  yalnızca 0.79-0.89 kosinüs benzerliğinde. Aynı model + aynı yöntemle
  üretilmiş olsalardı ~1.0 olurdu. Farklı vektör uzayından gelen kayıtları
  mevcut chunk'larla karıştırmak arama sonuçlarını bozar. Bu yüzden metni
  alıp uygulamanın kendi embedding hattıyla yeniden vektörleştiriyoruz.

Idempotent: aynı içerik ikinci kez çalıştırılırsa sha256 üzerinden atlanır.

Kullanım:
    cd backend && uv run python ../scripts/import_kb_from_jsonl.py [jsonl_yolu]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.models.document_chunk import DocumentChunk  # noqa: E402
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402

DEFAULT_SOURCE = Path(
    r"C:\Users\Çağan Aydın\OneDrive\Masaüstü\unibox_outputs\knowledge_base_raw.jsonl"
)


async def import_documents(source: Path) -> None:
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{len(rows)} kayıt okundu: {source.name}")

    rag = RagEngine()
    added = skipped = 0

    for row in rows:
        title: str = row["title"]
        content: str = row["content"]
        tags = row.get("tags", [])

        raw = content.encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()

        async with AsyncSessionLocal() as session:
            existing = await session.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.sha256_hash == sha)
            )
            if existing:
                print(f"  atlandı (zaten var): {title}")
                skipped += 1
                continue

            doc = KnowledgeDocument(
                id=str(uuid4()),
                filename=f"{title}.txt",
                original_filename=f"{title}.txt",
                file_data=raw,
                file_size_bytes=len(raw),
                mime_type="text/plain",
                sha256_hash=sha,
                status=ProcessingStatus.PROCESSING,
                uploaded_by="import_script",
                uploaded_at=datetime.now(timezone.utc).replace(tzinfo=None),
                description=title,
                tags_json=json.dumps(tags, ensure_ascii=False),
            )
            session.add(doc)
            await session.commit()

            # Uygulamanın kendi hattı: aynı splitter, aynı embedding modeli
            chunks = rag.split_text(content)
            models = []
            for idx, chunk_text in enumerate(chunks):
                embedding = await rag.embed_text(chunk_text)
                models.append(
                    DocumentChunk(
                        id=str(uuid4()),
                        document_id=doc.id,
                        chunk_index=idx,
                        content=chunk_text,
                        embedding=embedding,
                        tags_json=doc.tags_json,
                        word_count=len(chunk_text.split()),
                    )
                )
            session.add_all(models)

            doc.status = ProcessingStatus.INDEXED
            doc.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            doc.chunk_count = len(models)
            await session.commit()

            print(f"  eklendi: {title} ({len(models)} chunk, etiket: {tags})")
            added += 1

    print(f"\nTamamlandı — {added} doküman eklendi, {skipped} atlandı.")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not src.exists():
        sys.exit(f"Kaynak dosya bulunamadı: {src}")
    asyncio.run(import_documents(src))
