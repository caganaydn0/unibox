"""E-posta taslağı üretim kalitesi — model karşılaştırması.

unibox_outputs/email_draft_test.jsonl içindeki (intent + toplanan alanlar)
girdileriyle gerçek taslak üretim hattını (RAG dahil) çalıştırır ve çıktıyı
nesnel hata modlarına göre puanlar.

Ölçülenler — hepsi otomatik doğrulanabilir, insan yargısı gerekmez:
  json_ok      : model geçerli JSON döndürdü mü
  pii_ihlal    : TCKN / öğrenci no / ad-soyad İSTEDİ mi  (KVKK — kritik)
  placeholder  : [Adınız] gibi doldurulmamış yer tutucu bıraktı mı
  alan_kapsama : toplanan değerler (2024-2025, Güz...) gövdede geçiyor mu
  tekrar       : aynı cümleyi tekrarladı mı
  süre         : üretim süresi

Puanlama HAM model çıktısı üzerinde yapılır — sanitize_draft_body temizliği
uygulanmaz, çünkü amaç modellerin kendi davranışını karşılaştırmak.

Kullanım:
    cd backend && uv run python ../scripts/eval_draft.py --n 8
    cd backend && uv run python ../scripts/eval_draft.py --n 8 --models llama3.1:8b,unibox-llama3
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import random
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings  # noqa: E402
from app.services.anonymizer import _PII_TALEP_RE, _PLACEHOLDER_RE  # noqa: E402
from app.services.email_workflow import DRAFT_CONTEXT_MAX_CHARS  # noqa: E402
from app.services.intent_detector import INTENT_DESCRIPTIONS  # noqa: E402
from app.services.llm_provider import OllamaProvider  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402

DEFAULT_SOURCE = Path(
    r"C:\Users\Çağan Aydın\OneDrive\Masaüstü\unibox_outputs\email_draft_test.jsonl"
)


def _draft_prompt(intent: str, collected: dict, rag_context: str) -> str:
    """email_workflow._generate_draft ile aynı sistem promptu."""
    konu = INTENT_DESCRIPTIONS.get(intent, intent)
    return f"""Sen bir üniversite asistanısın. Aşağıdaki bilgilerle resmi bir e-posta taslağı oluştur.
E-posta, öğrencinin "{konu}" talebini ilgili birime ileten resmi bir başvuru yazısıdır.
Konu satırı ve e-posta gövdesi ayrı ayrı JSON olarak döndür.
Format: {{"subject": "...", "body": "..."}}

Toplanan bilgiler: {json.dumps(collected, ensure_ascii=False)}
İlgili yönetmelik bilgisi: {rag_context}

ZORUNLU KURALLAR:
- Yalnızca yukarıdaki "Toplanan bilgiler"i kullan. Başka bilgi İSTEME.
- TCKN, öğrenci numarası, ad-soyad, doğum tarihi YAZMA ve TALEP ETME.
- Köşeli parantezli yer tutucu ([Adınız] gibi) KULLANMA; bilgi eksikse o cümleyi hiç yazma.
- Aynı cümleyi tekrarlama."""


def _tekrar_var(text: str) -> bool:
    görülen: set[str] = set()
    for satır in text.splitlines():
        a = " ".join(satır.split()).lower()
        if len(a) > 25:
            if a in görülen:
                return True
            görülen.add(a)
    return False


def _alan_kapsama(body: str, collected: dict) -> float:
    if not collected:
        return 1.0
    düşük = body.lower()
    bulunan = sum(1 for v in collected.values() if str(v).lower()[:20] in düşük)
    return bulunan / len(collected)


async def model_ölç(model: str, örnekler: list[dict], rag: RagEngine) -> dict:
    sağlayıcı = OllamaProvider()
    sağlayıcı._model = model  # noqa: SLF001 — karşılaştırma için model override

    s: collections.Counter = collections.Counter()
    kapsama_toplam = 0.0
    süre_toplam = 0.0
    örnek_çıktı = ""

    for i, r in enumerate(örnekler, 1):
        intent = r["intent"]
        collected = r.get("collected", {})
        konu = INTENT_DESCRIPTIONS.get(intent, intent)
        ctx = await rag.query(konu, intent)
        if len(ctx) > DRAFT_CONTEXT_MAX_CHARS:
            ctx = ctx[:DRAFT_CONTEXT_MAX_CHARS] + "\n[...]"

        t = time.monotonic()
        try:
            ham = await sağlayıcı.generate(
                "E-posta taslağı oluştur",
                system=_draft_prompt(intent, collected, ctx),
                format="json",
            )
        except Exception as exc:
            print(f"    [{i}] HATA: {type(exc).__name__}")
            s["hata"] += 1
            continue
        süre_toplam += time.monotonic() - t

        try:
            veri = json.loads(ham.strip().strip("```json").strip("```"))
            subject = str(veri.get("subject", ""))
            body = str(veri.get("body", ""))
            s["json_ok"] += 1
        except Exception:
            subject, body = "", ham

        birleşik = f"{subject}\n{body}"
        s["pii_ihlal"] += bool(_PII_TALEP_RE.search(birleşik))
        s["placeholder"] += bool(_PLACEHOLDER_RE.search(birleşik))
        s["tekrar"] += _tekrar_var(body)
        kapsama_toplam += _alan_kapsama(body, collected)
        s["n"] += 1

        if i == 1:
            örnek_çıktı = f"{subject}\n{'-' * 40}\n{body[:320]}"

    n = max(s["n"], 1)
    await sağlayıcı.aclose()
    return {
        "n": s["n"], "hata": s["hata"],
        "json_ok": s["json_ok"] / n,
        "pii_ihlal": s["pii_ihlal"] / n,
        "placeholder": s["placeholder"] / n,
        "tekrar": s["tekrar"] / n,
        "kapsama": kapsama_toplam / n,
        "süre": süre_toplam / n,
        "örnek": örnek_çıktı,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8, help="model başına örnek sayısı")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--models", type=str, default=settings.OLLAMA_MODEL,
                    help="virgülle ayrılmış model listesi")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.source.read_text(encoding="utf-8").splitlines() if l.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["intent"]].append(r)

    rng = random.Random(args.seed)
    per = max(1, args.n // len(by))
    örnekler: list[dict] = []
    for intent in sorted(by):
        örnekler.extend(rng.sample(by[intent], min(per, len(by[intent]))))
    rng.shuffle(örnekler)
    örnekler = örnekler[:args.n]

    modeller = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"Embedding : {settings.EMBEDDING_MODEL}")
    print(f"Örnek     : {len(örnekler)} taslak / model")
    print(f"Modeller  : {', '.join(modeller)}")
    print("=" * 78)

    rag = RagEngine()
    sonuçlar: dict[str, dict] = {}
    for m in modeller:
        print(f"\n>>> {m}")
        sonuçlar[m] = await model_ölç(m, örnekler, rag)
        print(f"    bitti ({sonuçlar[m]['süre']:.1f} sn/taslak)")

    print("\n" + "=" * 78)
    print(f"{'model':22s} {'JSON':>7s} {'PII ihlal':>10s} {'placeh.':>9s} {'tekrar':>8s} {'alan':>7s} {'sn':>7s}")
    print("-" * 78)
    for m, r in sonuçlar.items():
        print(f"{m:22s} {r['json_ok']:>6.0%} {r['pii_ihlal']:>10.0%} "
              f"{r['placeholder']:>9.0%} {r['tekrar']:>8.0%} {r['kapsama']:>7.0%} {r['süre']:>7.1f}")
    print("-" * 78)
    print("PII ihlal ve placeholder DÜŞÜK, JSON ve alan kapsama YÜKSEK olmalı.")

    for m, r in sonuçlar.items():
        print(f"\n--- {m} örnek çıktı ---\n{r['örnek']}")


if __name__ == "__main__":
    asyncio.run(main())
