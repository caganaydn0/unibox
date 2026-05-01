"""RAG Engine — PostgreSQL pgvector + Ollama Embeddings

Doküman indeksleme (PDF → chunk → embed → pgvector) ve
cosine similarity ile bağlam-zenginleştirilmiş sorgu.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import delete, select

from app.config import settings
from app.db.models.document_chunk import DocumentChunk
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class RagEngine:
    def __init__(self) -> None:
        self._embedding_model = settings.EMBEDDING_MODEL
        self._ollama_url = settings.OLLAMA_BASE_URL
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE * 5,   # ~500 kelime ≈ 2500 karakter
            chunk_overlap=settings.RAG_CHUNK_OVERLAP * 5,
            length_function=len,
        )

    # ------------------------------------------------------------------ #
    # Embedding
    # ------------------------------------------------------------------ #
    async def embed_text(self, text: str) -> list[float]:
        """Ollama /api/embeddings endpoint'i ile metin → vektör."""
        async with httpx.AsyncClient(base_url=self._ollama_url, timeout=60.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": self._embedding_model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    # ------------------------------------------------------------------ #
    # Metin çıkarma & parçalama
    # ------------------------------------------------------------------ #
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """pypdf ile PDF byte'larından metin çıkar."""
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    def split_text(self, text: str) -> list[str]:
        """Metni ~500 kelimelik chunk'lara böl."""
        chunks = self._splitter.split_text(text)
        return [c for c in chunks if c.strip()]

    # ------------------------------------------------------------------ #
    # İndeksleme
    # ------------------------------------------------------------------ #
    async def index_document(self, doc_id: str) -> None:
        """PDF → metin → chunk → embed → pgvector'e yaz."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error("Doküman bulunamadı: %s", doc_id)
                return

            doc.status = ProcessingStatus.PROCESSING
            await session.commit()

            try:
                # 1. PDF'den metin çıkar
                full_text = self.extract_text_from_pdf(doc.file_data)
                if not full_text.strip():
                    raise ValueError("PDF'den metin çıkarılamadı (boş dosya veya taranmış PDF).")

                # 2. Chunk'lara böl
                chunks = self.split_text(full_text)
                if not chunks:
                    raise ValueError("Metin parçalanamadı.")

                # 3. Mevcut chunk'ları temizle (reindex durumunda)
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )

                # 4. Her chunk için embed et ve kaydet
                tags_json = doc.tags_json
                chunk_models = []
                for idx, chunk_text in enumerate(chunks):
                    embedding = await self.embed_text(chunk_text)
                    chunk_model = DocumentChunk(
                        document_id=doc_id,
                        chunk_index=idx,
                        content=chunk_text,
                        embedding=embedding,
                        tags_json=tags_json,
                        word_count=len(chunk_text.split()),
                    )
                    chunk_models.append(chunk_model)

                session.add_all(chunk_models)

                # 5. Doküman durumunu güncelle
                doc.status = ProcessingStatus.INDEXED
                doc.indexed_at = datetime.utcnow()
                doc.chunk_count = len(chunk_models)
                doc.processing_error = None
                await session.commit()

                logger.info(
                    "Doküman indekslendi: %s (%d chunk)", doc_id, len(chunk_models)
                )

                from app.core.ws_manager import ws_manager
                await ws_manager.broadcast_to_admins({
                    "type": "document_indexed",
                    "doc_id": doc_id,
                    "filename": doc.original_filename,
                    "chunk_count": len(chunk_models),
                })

            except Exception as exc:
                doc.status = ProcessingStatus.FAILED
                doc.processing_error = str(exc)
                await session.commit()
                logger.error(
                    "İndeksleme hatası (doc=%s): %s", doc_id, exc, exc_info=True
                )
                raise

    # ------------------------------------------------------------------ #
    # Sorgu (RAG retrieval)
    # ------------------------------------------------------------------ #
    async def query(self, question: str, intent_type: str | None = None) -> str:
        """Soruyu embed et → pgvector cosine similarity → top-K chunk döndür."""
        question_embedding = await self.embed_text(question)

        async with AsyncSessionLocal() as session:
            # Silinmemiş dokümanların chunk'larını ara — belge adını da çek
            stmt = (
                select(
                    DocumentChunk.content,
                    KnowledgeDocument.original_filename,
                    KnowledgeDocument.description,
                )
                .join(
                    KnowledgeDocument,
                    DocumentChunk.document_id == KnowledgeDocument.id,
                )
                .where(
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeDocument.status == ProcessingStatus.INDEXED,
                    DocumentChunk.embedding.isnot(None),
                )
                .order_by(DocumentChunk.embedding.cosine_distance(question_embedding))
                .limit(settings.RAG_TOP_K)
            )

            # İsteğe bağlı: intent_type'a göre tag filtresi
            # Etiketsiz chunk'lar (tags_json="[]") her zaman dahil edilir —
            # sadece etiket atanmış chunk'larda intent eşleşmesi aranır.
            if intent_type:
                from sqlalchemy import or_
                stmt = stmt.where(
                    or_(
                        DocumentChunk.tags_json == "[]",
                        DocumentChunk.tags_json.contains(f'"{intent_type}"'),
                    )
                )

            result = await session.execute(stmt)
            rows = result.all()

        if not rows:
            return ""

        # Chunk'ları bağlam string'i olarak birleştir — belge adını dahil et
        context_parts = []
        for i, (content, orig_filename, description) in enumerate(rows, 1):
            doc_label = description or orig_filename
            context_parts.append(f"[Kaynak {i} — {doc_label}]\n{content}")

        return "\n\n---\n\n".join(context_parts)

    # ------------------------------------------------------------------ #
    # Silme
    # ------------------------------------------------------------------ #
    async def delete_document_chunks(self, doc_id: str) -> None:
        """Bir dokümanın tüm chunk'larını PostgreSQL'den sil."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
            )
            await session.commit()
            logger.info("%d chunk silindi (doc=%s).", result.rowcount, doc_id)
