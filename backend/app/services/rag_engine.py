"""RAG Engine — PostgreSQL pgvector + Ollama Embeddings

Doküman indeksleme (PDF → chunk → embed → pgvector) ve
cosine similarity ile bağlam-zenginleştirilmiş sorgu.
"""
from __future__ import annotations

import collections
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import cast, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import TSQUERY

from app.config import settings
from app.db.models.document_chunk import DocumentChunk
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---- Hibrit arama parametreleri ---------------------------------------------
# Her iki aramadan kaç aday çekilecek (füzyondan önce).
CANDIDATE_POOL = 20

# Reciprocal Rank Fusion sabiti. Standart değer 60; büyüdükçe sıralama farkları
# yumuşar, küçüldükçe ilk sıralar baskınlaşır.
RRF_K = 60

# Sorgunun intent'iyle etiketli chunk'lara eklenen bonus. RRF skorları
# ~1/60 mertebesinde olduğu için bu değer "eşit durumda etiketliyi öne al"
# etkisi yaratır, tek başına alakasız bir dokümanı zirveye taşımaz.
INTENT_BONUS = 0.015

# ts_rank uzunluk normalizasyonu (PostgreSQL bit maskesi).
# 0 = normalizasyon yok. Bu varsayılan, uzun chunk'ları kayırır: eski taranmış
# PDF chunk'ları ortalama 2330 karakter, yeni bilgi tabanı dokümanları 371.
# Uzun metin daha çok sorgu kelimesi barındırdığı için ts_rank'te öne geçiyor
# ve konuyla birebir ilgili kısa dokümanı bastırıyordu (ölçüldü: 13 hatanın
# 8'inde 1. sırada aynı büyük PDF vardı).
# 1 = rank / (1 + log(doküman uzunluğu)).
#
# Bu değer İKİ farklı doküman tipiyle birlikte ölçülerek seçildi:
#   - kısa, konuya özel rehber metinleri (~370 karakter)
#   - gerçek üniversite yönetmeliği chunk'ları (~2450 karakter)
#
#                    yönetmelik@3  yönetmelik@7  kısa@3  kısa@7
#   norm=0                   75%           75%     80%     97%
#   norm=1                   75%           81%     83%     93%   <-- seçilen
#   norm=2                   38%           62%     87%     97%
#
# norm=2 yalnızca kısa dokümanlara bakılarak seçilirse cazip görünüyor ama
# uzun mevzuat metnini eziyor — bilgi tabanı gerçek yönetmeliklerle
# dolduğunda asıl ihtiyaç duyulan içerik bulunamaz hale geliyor.
FTS_NORMALIZATION = 1

# Sonuçta tek bir dokümandan en fazla kaç chunk yer alabilir.
# Bilgi tabanı dengesiz: bir yönetmelik PDF'i 20 chunk, konuya özel rehberler
# 1'er chunk. Sınır olmadan büyük doküman tüm slotları kapıp asıl aranan kısa
# dokümanı bağlam penceresinin dışında bırakabiliyor.
MAX_CHUNKS_PER_DOC = 2


def _turkish_tsvector(column):
    """to_tsvector('turkish', column) — regconfig literal olarak gömülür.

    Bind parametresi kullanılırsa PostgreSQL to_tsvector(text, text) imzasını
    arar ve fonksiyon bulunamaz hatası verir; bu yüzden literal_column şart.
    """
    return func.to_tsvector(literal_column("'turkish'"), column)


def _turkish_tsquery(soru: str):
    """Kullanıcı sorusunu VEYA bağlantılı tsquery'ye çevirir.

    plainto_tsquery kullanmıyoruz çünkü tüm kelimeleri VE ile bağlıyor:
    "transkriptimi nasıl alırım" sorgusu, bir dokümanda üç kelimenin de
    geçmesini şart koşar ve pratikte hiçbir şey dönmez (ölçüldü: 0 sonuç).

    Bunun yerine soruyu tsvector'e çevirip lexeme'leri ' | ' ile birleştiriyoruz.
    Böylece Postgres'in kendi Türkçe stopword ve stemmer'ı devreye girer,
    kullanıcı metni doğrudan sorguya gömülmediği için enjeksiyon riski de olmaz.

    Her lexeme quote_literal ile tırnaklanıyor. İki sebep:

    1. DOĞRULUK: tsvector_to_array bize zaten NORMALİZE EDİLMİŞ lexeme'i
       veriyor. Tırnaksız bıraktığımızda tsquery ayrıştırıcısı onu yeniden
       yorumluyor ve bileşik lexeme'leri (URL, dosya yolu, e-posta) bölerek
       tsvector'dekiyle eşleşmeyen bir sorguya çevirebiliyor. Tırnaklı hâli
       tsvector'de duranla birebir eşleşir.

    2. SAĞLAMLIK: tsquery'de `! & | ( ) : < '` özel karakter. Bir lexeme
       bunlardan birini içerirse tırnaksız cast "syntax error in tsquery"
       fırlatır. (search() bunu artık yakalıyor ama o zaman da sözcüksel
       aramayı tamamen kaybederdik.)

    Tüm kelimeler stopword ise sonuç boş tsquery olur; bu hata vermez,
    yalnızca hiçbir satırla eşleşmez.
    """
    return cast(
        func.array_to_string(
            func.array(
                select(func.quote_literal(literal_column("l")))
                .select_from(
                    func.unnest(
                        func.tsvector_to_array(
                            func.to_tsvector(literal_column("'turkish'"), soru)
                        )
                    ).alias("l")
                )
                .scalar_subquery()
            ),
            " | ",
        ),
        TSQUERY,
    )


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
        """Ollama /api/embeddings endpoint'i ile metin → vektör.

        Not: bge-m3 asimetrik önek ("query: " / "passage: ") İSTEMEZ —
        E5 ve bge-v1.5 ailelerinden farklı olarak sorgu ile doküman aynı
        şekilde gömülür. Eklemeyin.
        """
        async with httpx.AsyncClient(base_url=self._ollama_url, timeout=60.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": self._embedding_model, "prompt": text},
            )
            resp.raise_for_status()
            vektör = resp.json().get("embedding") or []

        # Boyut doğrulaması. Olmadığında iki hata sınıfı, teşhisi zor
        # pgvector mesajlarına dönüşüyordu:
        #  - boş metin -> [] -> "vector must have at least 1 dimension"
        #  - yanlış model (ör. nomic-embed-text hâlâ yüklü) -> 768 boyut ->
        #    "expected 1024 dimensions, not 768"
        if len(vektör) != settings.EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding boyutu beklenenden farklı: {len(vektör)} != "
                f"{settings.EMBEDDING_DIMENSIONS}. Model '{self._embedding_model}' "
                f"yüklü mü ve EMBEDDING_DIMENSIONS doğru mu? Model değiştiyse "
                f"migration + scripts/reindex_documents.py gerekir."
            )
        return vektör

    # ------------------------------------------------------------------ #
    # Metin çıkarma & parçalama
    # ------------------------------------------------------------------ #
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """pypdf ile PDF byte'larından metin çıkar."""
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    @staticmethod
    def decode_text(data: bytes) -> str:
        """Düz metni çöz — UTF-8, olmazsa Windows-1254.

        Türk kurumlarından gelen metin dosyaları sıklıkla cp1254 (Windows
        Türkçe) kodlanmış oluyor. Kör bir utf-8 decode UnicodeDecodeError
        ile patlıyor ve doküman FAILED oluyordu.
        """
        for kodlama in ("utf-8-sig", "utf-8", "cp1254"):
            try:
                return data.decode(kodlama)
            except UnicodeDecodeError:
                continue
        # Son çare: bozuk baytları kaybetmek, dokümanı tamamen kaybetmekten iyi
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def extract_text_from_docx(data: bytes) -> str:
        from docx import Document  # yerel import: yalnızca .docx yüklenince gerekir

        belge = Document(io.BytesIO(data))
        parçalar = [p.text for p in belge.paragraphs]
        # Tablolar da içerik taşıyor — yönetmelik ekleri sıklıkla tablo hâlinde
        for tablo in belge.tables:
            for satır in tablo.rows:
                parçalar.append(" | ".join(h.text.strip() for h in satır.cells))
        return "\n".join(parçalar)

    def extract_text(self, data: bytes, mime_type: str = "", filename: str = "") -> str:
        """Dosya tipine göre doğru çıkarıcıyı seçer.

        Eskiden index_document KOŞULSUZ olarak PdfReader çağırıyordu; oysa
        config.allowed_mime_types TXT, Markdown ve DOCX'i de kabul ediyor.
        Sonuç: admin panelinden yüklenen her metin dosyası FAILED oluyor ve
        yeniden indeksleme de aynı yola gittiği için kurtarılamıyordu.

        MIME'a tek başına güvenmiyoruz: tarayıcılar Markdown'ı tutarsız
        gönderiyor (text/plain, text/markdown, application/octet-stream).
        Uzantı ikinci sinyal olarak kullanılıyor.
        """
        uzantı = Path(filename).suffix.lower()

        if mime_type == "application/pdf" or uzantı == ".pdf":
            return self.extract_text_from_pdf(data)
        if uzantı == ".docx" or "wordprocessingml" in mime_type:
            return self.extract_text_from_docx(data)
        if mime_type.startswith("text/") or uzantı in {".txt", ".md", ".markdown"}:
            return self.decode_text(data)

        # Bilinmeyen tip: PDF imzası varsa PDF say, yoksa metin olarak dene.
        if data[:5] == b"%PDF-":
            return self.extract_text_from_pdf(data)
        return self.decode_text(data)

    def split_text(self, text: str) -> list[str]:
        """Metni ~500 kelimelik chunk'lara böl."""
        chunks = self._splitter.split_text(text)
        return [c for c in chunks if c.strip()]

    # ------------------------------------------------------------------ #
    # İndeksleme
    # ------------------------------------------------------------------ #
    async def _indeksleme_basarisiz(self, doc_id: str, exc: Exception) -> None:
        """Dokümanı FAILED işaretler — KENDİ temiz oturumunda.

        Ayrı oturum şart: hata anındaki oturumda bekleyen (commit edilmemiş)
        DELETE olabilir. O oturumda commit çağırmak silmeyi de kalıcı yapardı.
        """
        try:
            async with AsyncSessionLocal() as session:
                doc = await session.get(KnowledgeDocument, doc_id)
                if doc:
                    doc.status = ProcessingStatus.FAILED
                    doc.processing_error = str(exc)[:2000]
                    await session.commit()
        except Exception:
            logger.exception("Doküman FAILED olarak işaretlenemedi: %s", doc_id)

    async def index_document(self, doc_id: str) -> None:
        """Doküman → metin → chunk → embed → pgvector.

        ÜÇ AYRI OTURUM kullanılıyor; bu bilinçli bir tasarım:

        1. Eski hâli tek bir oturumu tüm embedding HTTP çağrıları boyunca açık
           tutuyordu. 47 chunk'lık bir doküman için havuzdaki bir bağlantı
           (pool_size=5) dakikalarca bloke oluyordu.

        2. Daha ciddisi VERİ KAYBIYDI: eski chunk'lar DELETE ediliyor, sonra
           embedding döngüsü başlıyordu. Döngüde bir Ollama timeout'u olursa
           except bloğundaki commit() bekleyen DELETE'i de KALICI yapıyordu.
           Sonuç: daha önce çalışan bir doküman FAILED + sıfır chunk hâline
           geliyor, üstelik chunk_count güncellenmediği için arayüz hâlâ eski
           sayıyı ("20 chunk") gösteriyordu.

        Artık silme ve yazma tek bir transaction'da, tüm embedding'ler
        hazırlandıktan SONRA yapılıyor. Hata hâlinde eski chunk'lara
        dokunulmaz; doküman aramada çalışmaya devam eder.
        """
        # --- 1. Oturum: dokümanı oku, PROCESSING işaretle, oturumu KAPAT ---
        async with AsyncSessionLocal() as session:
            doc = await session.get(KnowledgeDocument, doc_id)
            if not doc:
                logger.error("Doküman bulunamadı: %s", doc_id)
                return
            veri = doc.file_data
            mime = doc.mime_type
            etiket_json = doc.tags_json
            dosya_adı = doc.original_filename
            doc.status = ProcessingStatus.PROCESSING
            await session.commit()

        # --- 2. Oturumsuz: ağır iş (metin çıkarma + embedding) ---
        try:
            metin = self.extract_text(veri, mime, dosya_adı)
            if not metin.strip():
                raise ValueError(
                    "Dosyadan metin çıkarılamadı (boş dosya veya taranmış/OCR'sız PDF)."
                )
            parçalar = self.split_text(metin)
            if not parçalar:
                raise ValueError("Metin parçalanamadı.")

            gömüler = [await self.embed_text(p) for p in parçalar]
        except Exception as exc:
            await self._indeksleme_basarisiz(doc_id, exc)
            logger.error("İndeksleme hatası (doc=%s): %s", doc_id, exc, exc_info=True)
            raise

        # --- 3. Oturum: sil + yaz, TEK transaction ---
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )
                session.add_all([
                    DocumentChunk(
                        document_id=doc_id,
                        chunk_index=i,
                        content=parça,
                        embedding=gömü,
                        tags_json=etiket_json,
                        word_count=len(parça.split()),
                    )
                    for i, (parça, gömü) in enumerate(zip(parçalar, gömüler))
                ])
                doc = await session.get(KnowledgeDocument, doc_id)
                doc.status = ProcessingStatus.INDEXED
                doc.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                doc.chunk_count = len(parçalar)
                doc.processing_error = None
                await session.commit()
        except Exception as exc:
            await self._indeksleme_basarisiz(doc_id, exc)
            logger.error("Chunk yazma hatası (doc=%s): %s", doc_id, exc, exc_info=True)
            raise

        logger.info("Doküman indekslendi: %s (%d chunk)", doc_id, len(parçalar))

        from app.core.ws_manager import ws_manager
        await ws_manager.broadcast_to_admins({
            "type": "document_indexed",
            "doc_id": doc_id,
            "filename": dosya_adı,
            "chunk_count": len(parçalar),
        })

    # ------------------------------------------------------------------ #
    # Sorgu (RAG retrieval)
    # ------------------------------------------------------------------ #
    async def search(
        self, question: str, intent_type: str | None = None, top_k: int | None = None
    ) -> list[tuple[str, str, list[str]]]:
        """Hibrit arama — (içerik, belge etiketi, chunk etiketleri) listesi döner.

        İki bağımsız arama çalıştırılır:
          1. Anlamsal: pgvector cosine benzerliği
          2. Sözcüksel: PostgreSQL 'turkish' tam metin araması (ts_rank)

        Sonuçlar Reciprocal Rank Fusion ile birleştirilir: her chunk için
        skor = Σ 1/(RRF_K + sıra). Böylece iki listede de üstlerde çıkan
        chunk'lar öne geçer; sadece birinde çıkanlar da tamamen elenmez.

        Neden hibrit: saf vektör araması Türkçe'de zayıftı (ölçüm: recall@1
        %19). "Transkript" gibi birebir geçen anahtar kelimeleri sözcüksel
        arama yakalar, anlamsal yakınlığı ise vektör araması taşır.
        """
        k = top_k or settings.RAG_TOP_K

        # Boş/yalnızca boşluk sorgu: Ollama boş vektör döndürüyor ve pgvector
        # "vector must have at least 1 dimension" ile reddediyor. Sohbet
        # ucunda mesaj uzunluğu doğrulanmadığı için bu erişilebilir bir
        # 500'dü. Aramanın anlamı da yok — erken çık.
        if not question or not question.strip():
            return []

        görünür = (
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status == ProcessingStatus.INDEXED,
        )

        # --- 1. Anlamsal arama ---
        #
        # Embedding çağrısı BİLİNÇLİ olarak oturum bloğunun DIŞINDA: eskiden
        # havuzdan bir bağlantı, Ollama gidiş-dönüşü boyunca tutuluyordu
        # (pool_size=5 + overflow=10 → 15 eşzamanlı sohbet havuzu tüketir).
        #
        # İki geri getirim BAĞIMSIZ ARIZA ALANI. Eskiden vektör arama ikisinin
        # de ön koşuluydu: Ollama kapalıysa embed_text istisnası doğrudan
        # sohbet isteğini 500'e çeviriyordu — oysa sözcüksel arama Ollama
        # gerektirmiyor ve tek başına iş görebilir.
        vek_ids: list[str] = []
        en_yakın: float | None = None
        vektör_çalıştı = False
        try:
            question_embedding = await self.embed_text(question)
            async with AsyncSessionLocal() as session:
                mesafe = DocumentChunk.embedding.cosine_distance(question_embedding)
                vek_stmt = (
                    select(DocumentChunk.id, mesafe.label("mesafe"))
                    .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
                    .where(*görünür, DocumentChunk.embedding.isnot(None))
                    # id ile beraberlik kırma: eşit mesafede sıra rastgele
                    # olmasın, ölçümler koşular arasında oynamasın.
                    .order_by(mesafe, DocumentChunk.id)
                    .limit(CANDIDATE_POOL)
                )
                vek_satırlar = (await session.execute(vek_stmt)).all()
            vek_ids = [r[0] for r in vek_satırlar]
            en_yakın = float(vek_satırlar[0][1]) if vek_satırlar else None
            vektör_çalıştı = True
        except Exception:
            logger.warning(
                "Anlamsal arama başarısız (Ollama erişilemiyor olabilir) — "
                "yalnızca sözcüksel arama ile devam ediliyor.", exc_info=True,
            )

        # --- Kapsam kontrolü ---
        # En yakın chunk bile uzaksa soru bilgi tabanının dışındadır. Boş
        # dönüyoruz: LLM bağlamsız kalır ve prompt'undaki "bilgi yoksa öğrenci
        # işlerine yönlendir" kuralına düşer. Aksi halde alakasız chunk'ları
        # okuyup cevap uyduruyor (ölçüldü: otopark ücretine "aylık 150 TL").
        #
        # Yalnızca vektör arama ÇALIŞTIYSA uygulanır — başarısız olduysa
        # elimizde mesafe yok, sözcüksel arama ile devam etmek daha doğru.
        if vektör_çalıştı and (en_yakın is None or en_yakın > settings.RAG_MAX_DISTANCE):
            logger.info(
                "Kapsam dışı sayıldı (en yakın mesafe=%s > %s): %.80s",
                f"{en_yakın:.3f}" if en_yakın is not None else "yok",
                settings.RAG_MAX_DISTANCE, question,
            )
            return []

        # --- 2. Sözcüksel arama ---
        fts_ids: list[str] = []
        try:
            async with AsyncSessionLocal() as session:
                tsv = _turkish_tsvector(DocumentChunk.content)
                tsq = _turkish_tsquery(question)
                fts_stmt = (
                    select(DocumentChunk.id)
                    .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
                    .where(*görünür, tsv.op("@@")(tsq))
                    .order_by(
                        func.ts_rank(tsv, tsq, FTS_NORMALIZATION).desc(),
                        DocumentChunk.id,
                    )
                    .limit(CANDIDATE_POOL)
                )
                fts_ids = list((await session.execute(fts_stmt)).scalars())
        except Exception:
            logger.warning(
                "Sözcüksel arama başarısız — yalnızca anlamsal arama ile "
                "devam ediliyor.", exc_info=True,
            )

        # --- 3. Reciprocal Rank Fusion ---
        skorlar: dict[str, float] = {}
        for liste in (vek_ids, fts_ids):
            for sıra, cid in enumerate(liste):
                skorlar[cid] = skorlar.get(cid, 0.0) + 1.0 / (RRF_K + sıra + 1)

        if not skorlar:
            return []

        # --- 4. Adayların içeriğini çek ---
        async with AsyncSessionLocal() as session:
            satırlar = (await session.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.content,
                    DocumentChunk.tags_json,
                    DocumentChunk.document_id,
                    KnowledgeDocument.original_filename,
                    KnowledgeDocument.description,
                )
                .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
                .where(DocumentChunk.id.in_(list(skorlar)))
            )).all()

        # --- 5. Intent bonusu ---
        # Intent zaten tespit edilmiş durumda; o intent'le etiketli chunk'ları
        # öne çekiyoruz. Eskiden burada bir filtre vardı ama etiketsiz chunk'lar
        # her zaman dahil edildiği için pratikte hiçbir etkisi yoktu.
        sonuç = []
        for cid, content, tags_json, doc_id, filename, description in satırlar:
            try:
                etiketler = json.loads(tags_json)
            except Exception:
                etiketler = []
            skor = skorlar[cid]
            if intent_type and intent_type in etiketler:
                skor += INTENT_BONUS
            sonuç.append((skor, content, description or filename, etiketler, doc_id))

        sonuç.sort(key=lambda r: r[0], reverse=True)

        # Doküman çeşitliliği — tek kaynak tüm slotları kapmasın
        seçilen: list[tuple[str, str, list[str]]] = []
        doküman_sayacı: collections.Counter[str] = collections.Counter()
        for _, content, etiket, tags, doc_id in sonuç:
            if doküman_sayacı[doc_id] >= MAX_CHUNKS_PER_DOC:
                continue
            doküman_sayacı[doc_id] += 1
            seçilen.append((content, etiket, tags))
            if len(seçilen) >= k:
                break
        return seçilen

    async def query(self, question: str, intent_type: str | None = None) -> str:
        """Hibrit arama sonucunu LLM'e verilecek bağlam metnine dönüştürür."""
        parçalar = await self.search(question, intent_type)
        if not parçalar:
            return ""

        context_parts = [
            f"[Kaynak {i} — {etiket}]\n{content}"
            for i, (content, etiket, _) in enumerate(parçalar, 1)
        ]
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
