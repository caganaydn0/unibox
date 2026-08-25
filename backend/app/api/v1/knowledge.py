"""Knowledge Base API — Doküman yükleme, listeleme, silme, yeniden indeksleme"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, field_serializer, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ratelimit import UPLOAD_LIMIT, limiter
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


# --------------------------------------------------------------------------- #
# Yükleme doğrulama yardımcıları
# --------------------------------------------------------------------------- #

# Dosya imzaları (magic bytes). python-magic bağımlılık olarak duruyordu ama
# HİÇBİR YERDEN import edilmiyordu; Content-Type ise tamamen istemci
# kontrolündedir. Küçük ve bağımlılıksız bir imza kontrolü, yanlış etiketlenmiş
# veya kasten gizlenmiş dosyaları yakalamak için yeterli.
_IMZALAR: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    # DOCX bir ZIP arşivi
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
]

_UZANTI_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


async def _sinirli_oku(file: UploadFile, azami: int) -> bytes:
    """Dosyayı parça parça okur, sınırı aşınca ERKEN keser."""
    parçalar: list[bytes] = []
    toplam = 0
    while parça := await file.read(1024 * 1024):
        toplam += len(parça)
        if toplam > azami:
            raise HTTPException(
                413, f"Maksimum dosya boyutu {settings.MAX_UPLOAD_SIZE_MB}MB."
            )
        parçalar.append(parça)
    if not toplam:
        raise HTTPException(400, "Boş dosya yüklenemez.")
    return b"".join(parçalar)


def _reddet(sebep: str) -> None:
    raise HTTPException(
        415, f"{sebep} İzin verilenler: PDF, DOCX, TXT, MD."
    )


def _dogrulanmis_mime(içerik: bytes, bildirilen: str | None, dosya_adı: str) -> str:
    """Gerçek dosya tipini İÇERİKTEN belirler.

    İstemcinin bildirdiği Content-Type KARAR VERİCİ DEĞİLDİR — tamamen
    istemci kontrolündedir. Erken bir taslakta imzasız dosyalar için
    bildirilen tipe geri düşülüyordu ve bu, "application/pdf" diye bildirilen
    bir Windows çalıştırılabilirinin kabul edilmesine yol açıyordu (testle
    yakalandı).

    Kural: ikili tipler İMZA TAŞIMAK ZORUNDA. İmza yoksa dosya olsa olsa
    metindir ve metin olduğu ayrıca doğrulanır.
    """
    for imza, mime in _IMZALAR:
        if içerik.startswith(imza):
            if mime not in settings.allowed_mime_types:
                _reddet(f"Desteklenmeyen dosya tipi: {mime}.")
            return mime

    uzantı = Path(dosya_adı).suffix.lower()
    uzantı_mime = _UZANTI_MIME.get(uzantı)

    # .pdf/.docx uzantılı ama imzası yok: ya bozuk ya da kasten yanlış adlandırılmış
    if uzantı_mime and not uzantı_mime.startswith("text/"):
        _reddet(
            f"Dosya '{uzantı}' uzantılı ama içeriği o biçimde değil "
            f"(imza bulunamadı)."
        )

    # Buradan sonrası yalnızca metin olabilir. Uzantı tanınmıyorsa istemcinin
    # beyanı YALNIZCA metin yönünde kabul edilir — ve içerik ayrıca doğrulanır.
    if uzantı_mime:
        aday = uzantı_mime
    elif bildirilen and bildirilen.startswith("text/"):
        aday = "text/plain"
    else:
        _reddet(f"Dosya tipi belirlenemedi (uzantı: '{uzantı or 'yok'}').")

    örnek = içerik[:8192]
    if not _metin_gibi_mi(örnek):
        _reddet("Dosya metin gibi görünmüyor (ikili içerik).")
    return aday


# Metinde bulunması normal olan kontrol karakterleri
_IZINLI_KONTROL = {0x09, 0x0A, 0x0B, 0x0C, 0x0D}


def _metin_gibi_mi(örnek: bytes) -> bool:
    """İçerik gerçekten metin mi?

    Yalnızca NUL baytına bakmak yetmiyor: kısa ikili başlıklar (ELF, sınıf
    dosyaları) NUL içermeden de geçebiliyor ve UTF-8 olarak çözülebiliyor
    (testle yakalandı). Gerçek bir metin dosyasında ise 0x00-0x1F aralığında
    sekme/satır sonu dışında karakter bulunmaz — git'in ikili dosya
    sezgisinin aynısı.
    """
    if not örnek:
        return False
    if any(b < 0x20 and b not in _IZINLI_KONTROL for b in örnek):
        return False
    if 0x7F in örnek:          # DEL — metinde yeri yok
        return False
    for kodlama in ("utf-8", "cp1254"):   # cp1254: Türk kurumlarında yaygın
        try:
            örnek.decode(kodlama)
            return True
        except UnicodeDecodeError:
            continue
    return False


def _dogrulanmis_etiketler(ham: str) -> str:
    """tags alanı doğrulanmadan tags_json'a yazılıyordu.

    Bozuk JSON, arama sırasında rag_engine'deki geniş except ile sessizce
    []'ye düşüyor ve etiketler fark edilmeden kayboluyordu. Yükleme anında
    reddetmek, sessiz kayıptan iyidir.
    """
    try:
        değer = json.loads(ham or "[]")
    except json.JSONDecodeError:
        raise HTTPException(422, "tags geçerli bir JSON dizisi olmalı.")
    if not isinstance(değer, list) or not all(isinstance(e, str) for e in değer):
        raise HTTPException(422, "tags yalnızca metin öğelerden oluşan bir dizi olmalı.")
    return json.dumps(değer, ensure_ascii=False)


@router.post("/documents", status_code=202)
@limiter.limit(UPLOAD_LIMIT)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: str = Form("[]"),  # JSON array string
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    """Doküman yükle (PDF/DOCX/TXT/MD). 202 Accepted döner, indeksleme arka planda."""

    # Boyut kontrolü — AKIŞ HÂLİNDE.
    # Eskiden `await file.read()` tüm gövdeyi okuyup SONRA boyuta bakıyordu:
    # 2 GB'lık bir POST tamamen belleğe/diske alınıp ardından reddediliyordu.
    # Uygulama önünde başka bir sınır da yok (ters vekil yapılandırması hâlâ
    # eklenmedi), yani tek koruma buydu.
    content = await _sinirli_oku(file, settings.upload_max_bytes)

    safe_filename = Path(file.filename or "document").name
    mime = _dogrulanmis_mime(content, file.content_type, safe_filename)

    # SHA-256 duplikat kontrolü
    sha256 = hashlib.sha256(content).hexdigest()
    existing = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.sha256_hash == sha256)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Bu dosya zaten yüklü (SHA-256 eşleşti).")

    tags = _dogrulanmis_etiketler(tags)

    # DB kaydı oluştur — dosya BYTEA olarak saklanır
    doc = KnowledgeDocument(
        filename=safe_filename,
        original_filename=safe_filename,
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
    """Orijinal dosyayı indir."""
    doc = await _get_doc_or_404(db, doc_id)

    # Dosya adı BAŞLIĞA doğrudan gömülüyordu. İçinde tırnak veya satır sonu
    # olan bir ad başlık enjeksiyonuna açıktı. RFC 6266: ASCII'ye indirgenmiş
    # güvenli bir ad + UTF-8 için ayrı filename* parametresi.
    ad = Path(doc.original_filename or "belge").name
    ascii_ad = "".join(k if 32 <= ord(k) < 127 and k not in '"\\' else "_" for k in ad)
    return Response(
        content=doc.file_data,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_ad}"; '
                f"filename*=UTF-8''{quote(ad, safe='')}"
            ),
            # Tarayıcı içerik tipini tahmin edip HTML gibi çalıştırmasın
            "X-Content-Type-Options": "nosniff",
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
