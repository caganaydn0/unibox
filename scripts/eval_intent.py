"""Intent sınıflandırma doğruluğu ölçümü.

unibox_outputs/intent_test.jsonl içindeki etiketli örneklerle uygulamanın
detect_intent() fonksiyonunu ölçer. Model karşılaştırması için tasarlandı:
backend/.env içindeki OLLAMA_MODEL'i değiştirip tekrar çalıştırın, sonuçları
karşılaştırın.

Tam set 2534 örnek — 4 GB VRAM'li bir makinede saatler sürer. Bu yüzden
varsayılan olarak sınıf başına dengeli örnekleme yapılır.

Kullanım:
    cd backend && uv run python ../scripts/eval_intent.py --n 80
    cd backend && uv run python ../scripts/eval_intent.py --n 0      # tam set
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import random
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.services.intent_detector import detect_intent  # noqa: E402

# Windows konsolu varsayılan olarak cp1254 — Türkçe çıktı ve ok işareti bozulmasın
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SOURCE = Path(
    r"C:\Users\Çağan Aydın\OneDrive\Masaüstü\unibox_outputs\intent_test.jsonl"
)


def load_samples(source: Path, n: int, seed: int) -> list[dict]:
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if n <= 0 or n >= len(rows):
        return rows

    # Sınıf başına dengeli örnekleme — nadir sınıflar kaybolmasın
    by_label: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_label[r["expected_intent"]].append(r)

    rng = random.Random(seed)
    per_label = max(1, n // len(by_label))
    sampled: list[dict] = []
    for label, items in sorted(by_label.items()):
        sampled.extend(rng.sample(items, min(per_label, len(items))))
    rng.shuffle(sampled)
    return sampled


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80, help="örnek sayısı (0 = tam set)")
    ap.add_argument("--seed", type=int, default=42, help="örnekleme tohumu — karşılaştırmalar arası sabit tutun")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=None, help="hataları JSONL olarak yaz")
    args = ap.parse_args()

    samples = load_samples(args.source, args.n, args.seed)
    print(f"Model     : {settings.OLLAMA_MODEL}")
    print(f"Örnek     : {len(samples)}")
    print("-" * 60)

    correct = 0
    email_correct = 0
    confusion: collections.Counter = collections.Counter()
    errors: list[dict] = []
    started = time.monotonic()

    for i, row in enumerate(samples, 1):
        result = await detect_intent(row["input"])
        ok = result.intent_type == row["expected_intent"]
        correct += ok
        email_correct += result.requires_email == row["expected_requires_email"]
        if not ok:
            confusion[(row["expected_intent"], result.intent_type)] += 1
            errors.append({
                "input": row["input"],
                "expected": row["expected_intent"],
                "got": result.intent_type,
                "confidence": result.confidence,
            })
        if i % 10 == 0 or i == len(samples):
            hiz = (time.monotonic() - started) / i
            print(f"  {i}/{len(samples)} — doğruluk {correct/i:.1%} — {hiz:.1f} sn/örnek")

    süre = time.monotonic() - started
    print("-" * 60)
    print(f"Intent doğruluğu        : {correct}/{len(samples)} = {correct/len(samples):.1%}")
    print(f"requires_email doğruluğu: {email_correct}/{len(samples)} = {email_correct/len(samples):.1%}")
    print(f"Toplam süre             : {süre:.0f} sn ({süre/len(samples):.1f} sn/örnek)")

    if confusion:
        print("\nEn sık karışanlar (beklenen → tahmin):")
        for (exp, got), cnt in confusion.most_common(8):
            print(f"  {exp:22s} → {got:22s} : {cnt}")

    if args.out and errors:
        args.out.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in errors), encoding="utf-8"
        )
        print(f"\n{len(errors)} hata yazıldı: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
