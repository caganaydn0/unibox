"""Knowledge Base API — Doküman yükleme, listeleme, silme, yeniden indeksleme"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, field_serializer, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
from app.deps import get_current_admin, get_db

router = APIRouter()


class DocumentOut(BaseModel):
    id: str
    original_filename: str
    file_size_bytes: int
    mime_type: str
    status: str
    processing_error: Optional[str]
    uploaded_by: str
    uploaded_at: datetime
    indexed_at: Optional[datetime]
    description: Optional[str]
    tags_json: str
    chunk_count: int

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _make_datetimes_utc(self) -> "DocumentOut":
        if self.uploaded_at is not None and self.uploaded_at.tzinfo is None:
            self.uploaded_at = self.uploaded_at.replace(tzinfo=timezone.utc)
        if self.indexed_at is not None and self.indexed_at.tzinfo is None:
            self.indexed_at = self.indexed_at.replace(tzinfo=timezone.utc)
        return self


@router.post("/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: str = Form("[]"),  # JSON array string
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Doküman yükle (PDF/DOCX/TXT/MD). 202 Accepted döner, indeksleme arka planda."""

    # Boyut kontrolü
    content = await file.read()
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(413, f"Maksimum dosya boyutu {settings.MAX_UPLOAD_SIZE_MB}MB.")

    # MIME tip kontrolü
    mime = file.content_type or "application/octet-stream"
    if mime not in settings.allowed_mime_types:
        raise HTTPException(
            415,
            f"Desteklenmeyen dosya tipi: {mime}. "
            f"İzin verilenler: PDF, DOCX, TXT, MD",
        )

    # SHA-256 duplikat kontrolü
    sha256 = hashlib.sha256(content).hexdigest()
    existing = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.sha256_hash == sha256)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Bu dosya zaten yüklü (SHA-256 eşleşti).")

    # DB kaydı oluştur — PDF BYTEA olarak saklanır
    safe_filename = Path(file.filename or "document").name
    doc = KnowledgeDocument(
        filename=safe_filename,
        original_filename=file.filename or safe_filename,
        file_data=content,
        file_size_bytes=len(content),
        mime_type=mime,
        sha256_hash=sha256,
        status=ProcessingStatus.PENDING,
        uploaded_by=admin,
        description=description,
        tags_json=tags,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # İndeksleme kuyruğuna ekle
    from app.tasks.queue import index_queue
    await index_queue.put(doc.id)

    return {"id": doc.id, "status": "PENDING", "message": "Doküman kuyruğa eklendi."}


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    q = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.deleted_at.is_(None))
        .order_by(KnowledgeDocument.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status:
        try:
            q = q.where(KnowledgeDocument.status == ProcessingStatus(status))
        except ValueError:
            raise HTTPException(400, f"Geçersiz status: {status}")
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    return await _get_doc_or_404(db, doc_id)


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Orijinal PDF dosyasını indir."""
    doc = await _get_doc_or_404(db, doc_id)
    return Response(
        content=doc.file_data,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_filename}"'
        },
    )


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: str,
    description: Optional[str] = None,
    tags: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    doc = await _get_doc_or_404(db, doc_id)
    if description is not None:
        doc.description = description
    if tags is not None:
        doc.tags_json = tags
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Dokümanı sil: DB soft delete + pgvector chunk'ları hard delete."""
    doc = await _get_doc_or_404(db, doc_id)

    # pgvector chunk'larını sil
    from app.services.rag_engine import RagEngine
    rag = RagEngine()
    await rag.delete_document_chunks(doc.id)

    doc.deleted_at = datetime.utcnow()
    doc.status = ProcessingStatus.DELETED
    await db.commit()
    return {"detail": "Doküman silindi.", "doc_id": doc_id}


@router.post("/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Başarısız dokümanı yeniden indeksle."""
    doc = await _get_doc_or_404(db, doc_id)
    if doc.status not in {ProcessingStatus.FAILED, ProcessingStatus.INDEXED}:
        raise HTTPException(400, "Sadece FAILED veya INDEXED dokümanlar yeniden indekslenebilir.")

    doc.status = ProcessingStatus.PENDING
    doc.processing_error = None
    await db.commit()

    from app.tasks.queue import index_queue
    await index_queue.put(doc.id)
    return {"detail": "Yeniden indeksleme kuyruğa eklendi.", "doc_id": doc_id}


async def _get_doc_or_404(db: AsyncSession, doc_id: str) -> KnowledgeDocument:
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Doküman bulunamadı.")
    return doc
