"""Test fixture'larını kaynak veri setlerinden üretir.

NEDEN VAR: Ölçüm verisinin tamamı repo dışında, geliştirici makinesine özgü
mutlak yollarda duruyordu (unibox_outputs\\*.jsonl, 2534 satır / 615 KB).
Bu, ölçümleri başka bir makinede tekrarlanamaz hâle getiriyordu.

Çözüm, tamamını versiyonlamak DEĞİL: 2534 satırın pratikte yalnızca birkaç
yüzü kullanılıyor. Bunun yerine sabit tohumlu, sınıf başına dengeli bir alt
küme üretip repoya alıyoruz. Bu script alt kümenin nereden geldiğini
(provenance) kayıt altına alır ve gerektiğinde birebir yeniden üretir.

Kaynak veri kişisel veri içermiyor (tamamı "combinatorial" etiketli, sentetik
üretilmiş) ama repoya girmeden önce yine de anonymizer'dan geçiriliyor —
KVKK iddiası taşıyan bir projede versiyonlanan veride hiç PII bulunmaması
daha savunulabilir bir duruş.

Kullanım:
    cd backend && uv run python ../scripts/build_fixtures.py
    cd backend && uv run python ../scripts/build_fixtures.py --kaynak D:\\veri
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.anonymizer import has_pii, mask_pii  # noqa: E402

# Kaynak veri seti — repoda değil, geliştirici makinesinde.
VARSAYILAN_KAYNAK = Path.home() / "OneDrive" / "Masaüstü" / "unibox_outputs"

HEDEF = REPO / "backend" / "tests" / "fixtures" / "queries"

# Sabit tohum: aynı kaynak dosyadan her zaman aynı alt küme çıkar.
TOHUM = 42
# Intent başına örnek sayısı. 8 intent x 20 = 160 satır (~40 KB).
INTENT_BASINA = 20


def jsonl_oku(yol: Path) -> list[dict]:
    return [
        json.loads(satır)
        for satır in yol.read_text(encoding="utf-8").splitlines()
        if satır.strip()
    ]


def jsonl_yaz(yol: Path, kayıtlar: list[dict]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(
        "\n".join(json.dumps(k, ensure_ascii=False) for k in kayıtlar) + "\n",
        encoding="utf-8",
    )


def dengeli_örnekle(kayıtlar: list[dict], anahtar: str, adet: int) -> list[dict]:
    """Sınıf başına sabit sayıda, tohumlu örnekleme.

    eval_intent.py ve eval_draft.py bu mantığı ayrı ayrı, birbirinden hafifçe
    farklı biçimde yazmıştı (biri sonda n'e kırpıyor, diğeri kırpmıyor). Tek
    bir yerde topluyoruz.
    """
    rng = random.Random(TOHUM)
    gruplar: dict[str, list[dict]] = collections.defaultdict(list)
    for k in kayıtlar:
        gruplar[k.get(anahtar, "?")].append(k)

    seçilen: list[dict] = []
    for sınıf in sorted(gruplar):  # sıralı: platformdan bağımsız determinizm
        havuz = sorted(gruplar[sınıf], key=lambda k: k.get("input", ""))
        seçilen.extend(rng.sample(havuz, min(adet, len(havuz))))
    rng.shuffle(seçilen)
    return seçilen


def intent_fixture(kaynak: Path) -> None:
    src = kaynak / "intent_test.jsonl"
    if not src.exists():
        sys.exit(f"Kaynak bulunamadı: {src}\n--kaynak ile başka bir dizin verebilirsiniz.")

    ham = jsonl_oku(src)
    seçilen = dengeli_örnekle(ham, "expected_intent", INTENT_BASINA)

    temizlenen = 0
    çıktı: list[dict] = []
    for k in seçilen:
        metin = k["input"]
        if has_pii(metin):
            metin = mask_pii(metin)
            temizlenen += 1
        çıktı.append({
            "input": metin,
            "expected_intent": k["expected_intent"],
            "expected_requires_email": k.get("expected_requires_email"),
        })

    hedef = HEDEF / "intent.jsonl"
    jsonl_yaz(hedef, çıktı)

    dağılım = collections.Counter(k["expected_intent"] for k in çıktı)
    print(f"  kaynak       : {src.name} ({len(ham)} satır)")
    print(f"  seçilen      : {len(çıktı)} satır (intent başına {INTENT_BASINA}, tohum {TOHUM})")
    print(f"  maskelenen   : {temizlenen} satırda PII bulundu ve maskelendi")
    print(f"  dağılım      : {dict(sorted(dağılım.items()))}")
    print(f"  yazıldı      : {hedef.relative_to(REPO)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kaynak", type=Path, default=VARSAYILAN_KAYNAK,
                    help=f"kaynak veri dizini (varsayılan: {VARSAYILAN_KAYNAK})")
    args = ap.parse_args()

    print(f"Kaynak dizin : {args.kaynak}")
    print("-" * 70)
    print("intent.jsonl")
    intent_fixture(args.kaynak)
    print("-" * 70)
    print("Bitti. Üretilen dosyaları commit'lemeyi unutmayın.")


if __name__ == "__main__":
    main()
