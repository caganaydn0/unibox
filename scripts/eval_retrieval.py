"""RAG geri getirim (retrieval) kalitesi ölçümü.

Soru: "Öğrencinin sorusuna gerçekten doğru doküman geliyor mu?"

Yöntem: intent_test.jsonl'deki sorular intent etiketli, bilgi tabanındaki
dokümanlar da aynı intent'lerle etiketli. Bir soruyu embed edip vektör
araması yapıyoruz; dönen dokümanlar arasında sorunun intent'iyle etiketli
bir doküman var mı diye bakıyoruz.

recall@1 : en üstteki doküman doğru mu
recall@3 : ilk 3 içinde doğru doküman var mı
recall@7 : uygulamanın gerçekte kullandığı RAG_TOP_K içinde var mı

LLM çağrısı yok — sadece embedding, bu yüzden hızlı çalışır.

Kullanım:
    cd backend && uv run python ../scripts/eval_retrieval.py --n 10
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import random
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

DEFAULT_SOURCE = Path(
    r"C:\Users\Çağan Aydın\OneDrive\Masaüstü\unibox_outputs\intent_test.jsonl"
)


async def etiketli_intentler() -> set[str]:
    """Bilgi tabanında en az bir dokümanla temsil edilen intent'ler."""
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(KnowledgeDocument.tags_json).where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status == ProcessingStatus.INDEXED,
            )
        )).scalars().all()
    etiketler: set[str] = set()
    for r in rows:
        try:
            etiketler.update(json.loads(r))
        except Exception:
            pass
    return etiketler


async def ara_saf_vektor(rag: RagEngine, soru: str, k: int) -> list[list[str]]:
    """Referans: eski davranış — yalnızca vektör araması."""
    vec = await rag.embed_text(soru)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(DocumentChunk.tags_json)
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status == ProcessingStatus.INDEXED,
                DocumentChunk.embedding.isnot(None),
            )
            .order_by(DocumentChunk.embedding.cosine_distance(vec))
            .limit(k)
        )).scalars().all()
    out = []
    for tags in rows:
        try:
            out.append(json.loads(tags))
        except Exception:
            out.append([])
    return out


async def ara_hibrit(rag: RagEngine, soru: str, intent: str, k: int) -> list[list[str]]:
    """Yeni davranış — RagEngine.search (vektör + Türkçe FTS, RRF füzyonu)."""
    return [tags for _, _, tags in await rag.search(soru, intent, top_k=k)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="intent başına soru sayısı")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--mod", choices=["hibrit", "vektor", "ikisi"], default="ikisi",
                    help="hangi arama yöntemi ölçülsün")
    args = ap.parse_args()

    hedef = await etiketli_intentler()
    if not hedef:
        sys.exit("Bilgi tabanında etiketli doküman yok — ölçüm yapılamaz.")

    rows = [json.loads(l) for l in args.source.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_intent: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r["expected_intent"] in hedef:
            by_intent[r["expected_intent"]].append(r)

    rng = random.Random(args.seed)
    print(f"Embedding modeli : {settings.EMBEDDING_MODEL}")
    print(f"Ölçülen intent'ler: {', '.join(sorted(by_intent))}")
    print(f"Intent başına     : {args.n} soru")
    print("=" * 66)

    rag = RagEngine()
    K = settings.RAG_TOP_K
    yöntemler = ["vektor", "hibrit"] if args.mod == "ikisi" else [args.mod]

    # Aynı soru kümesini her yöntemde kullan — karşılaştırma adil olsun
    seçilen = {
        intent: rng.sample(by_intent[intent], min(args.n, len(by_intent[intent])))
        for intent in sorted(by_intent)
    }

    sonuçlar: dict[str, dict[str, collections.Counter]] = {}
    for yöntem in yöntemler:
        per_intent: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for intent, örnekler in seçilen.items():
            for r in örnekler:
                if yöntem == "vektor":
                    bulunan = await ara_saf_vektor(rag, r["input"], K)
                else:
                    bulunan = await ara_hibrit(rag, r["input"], intent, K)
                konumlar = [i for i, tags in enumerate(bulunan) if intent in tags]
                ilk = konumlar[0] if konumlar else None
                for k in (1, 3, K):
                    per_intent[intent][f"recall@{k}"] += ilk is not None and ilk < k
                per_intent[intent]["n"] += 1
        sonuçlar[yöntem] = per_intent

    başlık = {"vektor": "saf vektör", "hibrit": "hibrit (vektör+FTS)"}
    for k in (1, 3, K):
        print(f"\n### recall@{k}")
        kolonlar = "  ".join(f"{başlık[y]:>20s}" for y in yöntemler)
        print(f"{'intent':24s} {kolonlar}")
        print("-" * (24 + 22 * len(yöntemler)))
        for intent in sorted(seçilen):
            satır = f"{intent:24s} "
            for y in yöntemler:
                c = sonuçlar[y][intent]
                satır += f"{c[f'recall@{k}']/c['n']:>20.0%}  "
            print(satır)
        print("-" * (24 + 22 * len(yöntemler)))
        satır = f"{'TOPLAM':24s} "
        for y in yöntemler:
            tv = sum(c[f"recall@{k}"] for c in sonuçlar[y].values())
            tn = sum(c["n"] for c in sonuçlar[y].values())
            satır += f"{tv/tn:>20.0%}  "
        print(satır)


if __name__ == "__main__":
    asyncio.run(main())
