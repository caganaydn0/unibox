"""İndeksleme dayanıklılığı ve dosya tipi desteği.

İki sınıf test:

1. Saf (servis gerektirmez): metin çıkarma dağıtıcısı — PDF/TXT/MD/DOCX ve
   kodlama düşüşü. Eskiden index_document KOŞULSUZ PdfReader çağırdığı için
   admin panelinden yüklenen her metin dosyası FAILED oluyordu.

2. rag_eval: yeniden indeksleme sırasında hata olursa eski chunk'lar
   korunuyor mu? Bu, sessizce arama sonuçlarından doküman düşüren bir veri
   kaybı bug'ının regresyon testi.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.rag_engine import RagEngine


# --------------------------------------------------------------------------- #
# 1. Metin çıkarma — saf testler
# --------------------------------------------------------------------------- #

def test_duz_metin_utf8_cozulur() -> None:
    metin = "Transkript belgesi öğrencinin tüm derslerini gösterir."
    assert RagEngine.decode_text(metin.encode("utf-8")) == metin


def test_bom_kirpilir() -> None:
    """Windows Not Defteri UTF-8'i BOM ile kaydeder."""
    ham = "Kayıt dondurma".encode("utf-8-sig")
    assert ham.startswith(b"\xef\xbb\xbf"), "test verisi BOM içermeli"

    çözülen = RagEngine.decode_text(ham)
    assert çözülen == "Kayıt dondurma"
    assert not çözülen.startswith("﻿")


def test_cp1254_geri_dusus() -> None:
    """Türk kurumlarından gelen metinler sıklıkla Windows-1254 kodlu.

    Kör utf-8 decode UnicodeDecodeError veriyor ve doküman FAILED oluyordu.
    """
    ham = "Öğrenci İşleri Şubesi".encode("cp1254")
    with pytest.raises(UnicodeDecodeError):
        ham.decode("utf-8")
    assert RagEngine.decode_text(ham) == "Öğrenci İşleri Şubesi"


def test_bozuk_bayt_dokumani_dusurmez() -> None:
    """Çözülemeyen bayt varsa metni kaybetmektense o baytı kaybederiz."""
    sonuç = RagEngine.decode_text(b"Ge\xff\xfeerli metin devam ediyor")
    assert "erli metin devam ediyor" in sonuç


@pytest.mark.parametrize(
    "mime, dosya",
    [
        ("text/plain", "rehber.txt"),
        ("text/markdown", "rehber.md"),
        ("application/octet-stream", "rehber.md"),   # tarayıcı MIME'ı bilmiyor
        ("", "rehber.txt"),                           # MIME hiç yok
    ],
)
def test_metin_dosyalari_pdf_ayristiricisina_gitmez(mime: str, dosya: str) -> None:
    içerik = "Yaz okulu temmuz ve ağustos aylarında açılır."
    sonuç = RagEngine().extract_text(içerik.encode("utf-8"), mime, dosya)
    assert sonuç == içerik


def test_docx_metni_cikarilir() -> None:
    docx = pytest.importorskip("docx")

    belge = docx.Document()
    belge.add_paragraph("Kayıt dondurma başvurusu dilekçe ile yapılır.")
    tablo = belge.add_table(rows=1, cols=2)
    tablo.rows[0].cells[0].text = "Süre"
    tablo.rows[0].cells[1].text = "En fazla iki dönem"
    tampon = io.BytesIO()
    belge.save(tampon)

    sonuç = RagEngine().extract_text(
        tampon.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "kayit.docx",
    )
    assert "Kayıt dondurma başvurusu" in sonuç
    # Tablolar da içerik taşır — yönetmelik ekleri sıklıkla tablo hâlinde
    assert "En fazla iki dönem" in sonuç


def test_pdf_imzasi_mime_yanlissa_da_taninir() -> None:
    from tests.conftest import fixture_path

    ham = fixture_path("mevzuat", "gazi_lisansustu_yonetmelik.pdf").read_bytes()
    # MIME ve uzantı yanlış; yalnızca %PDF- imzasından tanınmalı
    sonuç = RagEngine().extract_text(ham, "application/octet-stream", "belge.bin")
    assert "MADDE" in sonuç


# --------------------------------------------------------------------------- #
# 2. Yeniden indeksleme dayanıklılığı
# --------------------------------------------------------------------------- #

@pytest.fixture
async def gecici_dokuman(korpus):
    """Test için tek dokümanlık geçici kayıt; sonunda MUTLAKA silinir.

    Temizlik şart: korpusta kalan fazladan bir doküman, test_retrieval'ın
    ölçümlerini sessizce kaydırır.
    """
    from sqlalchemy import delete

    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    doc_id = str(uuid4())
    içerik = (
        "Bütünleme sınavı finalden geçemeyen öğrenciler için yapılır. "
        "Sonuçlar beş iş günü içinde ilan edilir. Mazeret sınavı ise "
        "belgelendirilmiş mazereti olan öğrencilere uygulanır."
    )
    ham = içerik.encode("utf-8")

    async with AsyncSessionLocal() as s:
        s.add(KnowledgeDocument(
            id=doc_id,
            filename="__test_gecici__",
            original_filename="__test_gecici__.txt",
            description="__test_gecici__",
            mime_type="text/plain",
            file_size_bytes=len(ham),
            file_data=ham,
            sha256_hash=hashlib.sha256(ham + doc_id.encode()).hexdigest(),
            tags_json="[]",
            status=ProcessingStatus.PENDING,
            chunk_count=0,
            uploaded_by="test",
            uploaded_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        await s.commit()

    try:
        yield doc_id
    finally:
        async with AsyncSessionLocal() as s:
            await s.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await s.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
            await s.commit()


async def _chunk_sayısı(doc_id: str) -> int:
    from sqlalchemy import func, select

    from app.db.models.document_chunk import DocumentChunk
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
        ) or 0


@pytest.mark.rag_eval
async def test_metin_dokumani_indekslenebilir(gecici_dokuman) -> None:
    """TXT yüklemesi artık FAILED olmamalı.

    Eskiden index_document koşulsuz PdfReader çağırıyordu; config
    text/plain'e izin verdiği için dosya yüklenebiliyor ama HER ZAMAN
    başarısız oluyordu ve reindex ucu da aynı yola gittiği için
    arayüzden kurtarmak imkânsızdı.
    """
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    await RagEngine().index_document(gecici_dokuman)

    async with AsyncSessionLocal() as s:
        doc = await s.get(KnowledgeDocument, gecici_dokuman)
        assert doc.status == ProcessingStatus.INDEXED, doc.processing_error
        assert doc.chunk_count > 0
    assert await _chunk_sayısı(gecici_dokuman) > 0


@pytest.mark.rag_eval
async def test_indeksleme_hatasi_eski_chunklari_korumali(gecici_dokuman, monkeypatch) -> None:
    """VERİ KAYBI REGRESYONU.

    Eski kod önce DELETE ediyor, sonra embedding döngüsüne giriyordu. Döngüde
    bir hata olursa except bloğundaki commit() bekleyen DELETE'i de kalıcı
    yapıyordu → doküman FAILED + SIFIR chunk, ama chunk_count güncellenmediği
    için arayüz hâlâ eski sayıyı gösteriyordu. Daha önce çalışan bir doküman
    aramadan sessizce düşüyordu.
    """
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
    from app.db.session import AsyncSessionLocal

    rag = RagEngine()

    # 1. Başarıyla indeksle
    await rag.index_document(gecici_dokuman)
    önceki = await _chunk_sayısı(gecici_dokuman)
    assert önceki > 0

    # 2. Embedding'i patlat ve yeniden indekslemeyi dene
    async def patlayan_embed(self, text: str):
        raise RuntimeError("Ollama yanıt vermedi (simüle edilmiş timeout)")

    monkeypatch.setattr(RagEngine, "embed_text", patlayan_embed)

    with pytest.raises(RuntimeError):
        await RagEngine().index_document(gecici_dokuman)

    # 3. ESKİ CHUNK'LAR DURUYOR OLMALI — doküman aramada çalışmaya devam etmeli
    sonraki = await _chunk_sayısı(gecici_dokuman)
    assert sonraki == önceki, (
        f"Veri kaybı: chunk sayısı {önceki} -> {sonraki}. Başarısız yeniden "
        f"indeksleme mevcut chunk'ları silmemeli."
    )

    # 4. Durum FAILED, sebebi kayıtlı olmalı
    async with AsyncSessionLocal() as s:
        doc = await s.get(KnowledgeDocument, gecici_dokuman)
        assert doc.status == ProcessingStatus.FAILED
        assert doc.processing_error
        # chunk_count gerçekle tutarlı kalmalı (arayüz yalan söylememeli)
        assert doc.chunk_count == önceki
