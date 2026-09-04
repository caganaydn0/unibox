"""Doküman düzeyinde geri getirim ölçümü — etiketsiz dokümanlar üzerinde.

Neden bu ikinci ölçüm var:
    eval_retrieval.py "intent'i X olan soruya X etiketli doküman geliyor mu"
    diye sorar. Ama RagEngine intent'le etiketli chunk'lara bonus veriyor —
    yani o test kısmen kendi kendini doğruluyor. Ayrıca bilgi tabanındaki
    54 chunk'ın sadece 8'i etiketli; kalan 46'sı orada hiç ölçülmüyor.

    Bu script yalnızca ETİKETSİZ dokümanları hedefler. Bu dokümanlar intent
    bonusu almadığı için hibrit arama çıplak ölçülür.

Sorular kasıtlı olarak doküman başlığındaki kelimeleri tekrarlamayacak şekilde
yazıldı ("Çift Anadal" yerine "iki bölümden birden diploma"), aksi halde test
anahtar kelime aramasının lehine hileli olurdu.

Kullanım:
    cd backend && uv run python ../scripts/eval_retrieval_docs.py
"""
from __future__ import annotations

import asyncio
import collections
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models.document_chunk import DocumentChunk  # noqa: E402
from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402

# (soru, beklenen doküman başlığı) — hepsi etiketsiz dokümanlar
SORULAR: list[tuple[str, str]] = [
    ("Vize sınavları dönemin kaçıncı haftasında yapılıyor?", "Akademik Takvim ve Genel Bilgiler"),
    ("Ders ekleme çıkarma için ne kadar sürem var?", "Akademik Takvim ve Genel Bilgiler"),
    ("İki bölümden birden diploma alabilir miyim?", "Çift Anadal ve Yan Dal Programları"),
    ("Yan dal yapmak için ortalamam kaç olmalı?", "Çift Anadal ve Yan Dal Programları"),
    ("Kaydımı sildirirsem ödediğim para geri döner mi?", "Harç ve Ödeme Bilgileri"),
    ("Öğrenim ücretini kim belirliyor?", "Harç ve Ödeme Bilgileri"),
    ("Üniversitede ücretsiz terapi hizmeti var mı?", "Psikolojik Destek ve Öğrenci Refahı"),
    ("Engelli öğrenciler sınavda ek süre alabiliyor mu?", "Psikolojik Destek ve Öğrenci Refahı"),
    ("Başka bir üniversiteden buraya nakil olmak istiyorum.", "Yatay Geçiş Yönetmeliği"),
    ("Ön lisans bitirdim, lisansa nasıl devam edebilirim?", "Dikey Geçiş Sınavı (DGS) ve İntibak"),
    ("Daha önce aldığım dersler burada sayılır mı?", "Ders Muafiyeti ve İntibak"),
    ("Ders içeriklerinin yüzde kaçı örtüşmeli?", "Ders Muafiyeti ve İntibak"),
    ("Mezun olmak için toplam kaç AKTS gerekiyor?", "Mezuniyet Koşulları ve Diploma"),
    ("Diplomam hazır olana kadar bana bir belge verilir mi?", "Mezuniyet Koşulları ve Diploma"),
    ("Dönem ortalamam 3.6, bir belge almaya hak kazanır mıyım?", "Onur ve Yüksek Onur Belgesi"),
    ("Zorunlu uygulama kaç iş günü sürüyor?", "Staj Süreci ve SGK"),
    ("İşyerinde çalışırken sigortam yapılıyor mu?", "Staj Süreci ve SGK"),
    ("Bir dönem yurt dışında okumak istiyorum, nasıl başvururum?", "Erasmus ve Değişim Programları"),
    ("Yurt dışında aldığım dersler burada tanınır mı?", "Erasmus ve Değişim Programları"),
    ("Kaldığım dersi temmuzda alabilir miyim?", "Yaz Okulu Uygulama Esasları"),
    ("Not yükseltmek için ders almak mümkün mü?", "Yaz Okulu Uygulama Esasları"),
    ("Ders seçimi yapmazsam ne olur?", "Kayıt Yenileme ve Ders Seçimi"),
    ("Danışman onayı şart mı?", "Kayıt Yenileme ve Ders Seçimi"),
    ("BB notu kaç katsayıya denk geliyor?", "GNO / AGNO Hesaplama"),
    ("Ortalamam 2'nin altında kalırsa ne olur?", "GNO / AGNO Hesaplama"),
    ("Şifremi unuttum, sisteme nasıl girerim?", "Öğrenci Bilgi Sistemi (ÖİBS) Kullanımı"),
    ("Uluslararası öğrenciyim, ikamet iznim için ne gerekiyor?", "Yabancı Uyruklu Öğrenci İşlemleri"),
    ("Türkçe seviye şartı var mı?", "Yabancı Uyruklu Öğrenci İşlemleri"),
    ("Kitabı geç teslim edersem ceza öder miyim?", "Kütüphane ve Barınma Hizmetleri"),
    ("Yurt başvurusunu nereden yapıyorum?", "Kütüphane ve Barınma Hizmetleri"),
]


async def saf_vektor(rag: RagEngine, soru: str, k: int) -> list[str]:
    vec = await rag.embed_text(soru)
    async with AsyncSessionLocal() as s:
        return list((await s.execute(
            select(KnowledgeDocument.description)
            .join(DocumentChunk, DocumentChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status == ProcessingStatus.INDEXED,
                DocumentChunk.embedding.isnot(None),
            )
            .order_by(DocumentChunk.embedding.cosine_distance(vec))
            .limit(k)
        )).scalars())


async def main() -> None:
    rag = RagEngine()
    K = settings.RAG_TOP_K
    print(f"Embedding modeli: {settings.EMBEDDING_MODEL}")
    print(f"Soru sayısı     : {len(SORULAR)} (tamamı ETİKETSİZ doküman — intent bonusu yok)")
    print("=" * 72)

    sayac: dict[str, collections.Counter] = {
        "vektor": collections.Counter(), "hibrit": collections.Counter()
    }
    kaçırılan: list[tuple[str, str, str]] = []

    for soru, beklenen in SORULAR:
        v_docs = await saf_vektor(rag, soru, K)
        h_docs = [etiket for _, etiket, _ in await rag.search(soru, None, top_k=K)]

        for ad, docs in (("vektor", v_docs), ("hibrit", h_docs)):
            konum = next((i for i, d in enumerate(docs) if d == beklenen), None)
            for k in (1, 3, K):
                sayac[ad][k] += konum is not None and konum < k
            sayac[ad]["n"] += 1
            if ad == "hibrit" and (konum is None or konum >= 3):
                kaçırılan.append((soru, beklenen, docs[0] if docs else "-"))

    print(f"{'yöntem':22s} {'recall@1':>10s} {'recall@3':>10s} {'recall@'+str(K):>10s}")
    print("-" * 72)
    for ad, başlık in (("vektor", "saf vektör"), ("hibrit", "hibrit (vektör+FTS)")):
        c = sayac[ad]
        n = c["n"]
        print(f"{başlık:22s} {c[1]/n:>9.0%} {c[3]/n:>10.0%} {c[K]/n:>10.0%}")

    if kaçırılan:
        print(f"\nHibrit aramanın ilk 3'te bulamadığı {len(kaçırılan)} soru:")
        for soru, beklenen, geldi in kaçırılan:
            print(f"  '{soru}'")
            print(f"     beklenen: {beklenen}")
            print(f"     1. sıra : {geldi}")


if __name__ == "__main__":
    asyncio.run(main())
