"""Gerçek yönetmelik üzerinde geri getirim ölçümü.

Diğer iki değerlendirme scripti kısa, konu başına yazılmış rehber metinleri
ölçüyor. Bu script farklı bir soruyu yanıtlıyor:

    "Sisteme gerçek bir üniversite yönetmeliği yüklersek, öğrencinin
     sorusuna karşılık gelen MADDE'yi bulabiliyor mu?"

Hedef: bilgi tabanındaki Gazi Üniversitesi Lisansüstü Eğitim-Öğretim ve Sınav
Yönetmeliği (GeneratePdf.pdf) — 45 madde, 20 chunk, gerçek mevzuat metni.

Sorular öğrencinin kullanacağı dille yazıldı; madde başlığındaki kelimeler
kasten tekrarlanmadı ("İzinli sayılma" yerine "bir dönem ara vermek").
Başarı ölçütü: dönen chunk'lardan biri hedef MADDE'yi içeriyor mu.

Kullanım:
    cd backend && uv run python ../scripts/eval_regulation.py
"""
from __future__ import annotations

import asyncio
import collections
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402

# (soru, hedef madde no, maddenin konusu)
SORULAR: list[tuple[str, int, str]] = [
    ("Doktorada yeterlik sınavına ne zaman girmem gerekiyor?", 31, "Doktora yeterlik sınavı"),
    ("Tezimi izleyen komite kimlerden oluşuyor?", 32, "Tez izleme komitesi"),
    ("Sınav sonucuma itiraz etmek istiyorum, ne kadar sürem var?", 12, "Sınav sonucuna itiraz"),
    ("Yüksek lisansta bana danışman nasıl atanıyor?", 20, "Danışman atanması"),
    ("Bir dönem ara vermek istiyorum, şartları neler?", 17, "İzinli sayılma"),
    ("Başka üniversitede aldığım dersler burada sayılır mı?", 10, "Kredi transferi ve intibak"),
    ("Kayıtlı olmadan ders almak mümkün mü?", 15, "Özel öğrenci kabulü"),
    ("Yabancı uyrukluyum, başvuru için ne gerekiyor?", 14, "Yabancı uyruklu öğrenci kabulü"),
    ("Tezsiz programda dönem projesi nasıl değerlendiriliyor?", 26, "Dönem projesi ve yeterlik"),
    ("Kesin kayıt için hangi belgeleri getirmem lazım?", 7, "Kayıt işlemleri"),
    ("Öğrenim ücreti ödemem gerekiyor mu?", 37, "Katkı payları ve öğrenim ücretleri"),
    ("Mezun olunca diplomam ne zaman hazır olur?", 36, "Mezuniyet, diploma"),
    ("Toplam kaç kredi ders almam gerekiyor?", 9, "Dersler ve ders kredileri"),
    ("Doktora tezimi savunmak için süre sınırı var mı?", 34, "Doktora tezinin sonuçlandırılması"),
    ("Programımı değiştirip başka bir programa geçebilir miyim?", 13, "Programlar arası geçiş"),
    ("Başvurular nasıl değerlendiriliyor, sonuçlar nerede ilan ediliyor?", 6, "Değerlendirme ve ilan"),
]


async def main() -> None:
    rag = RagEngine()
    K = settings.RAG_TOP_K
    print(f"Embedding : {settings.EMBEDDING_MODEL}")
    print(f"Hedef     : Gazi Üniv. Lisansüstü Yönetmeliği (45 madde, 20 chunk)")
    print(f"Soru      : {len(SORULAR)} — gerçek mevzuat maddeleri")
    print("=" * 74)

    say = collections.Counter()
    kaçırılan: list[tuple[str, int, str]] = []

    for soru, madde, konu in SORULAR:
        parçalar = await rag.search(soru, None, top_k=K)
        desen = re.compile(rf"MADDE\s*{madde}\b")
        konum = next(
            (i for i, (içerik, _, _) in enumerate(parçalar)
             if desen.search(" ".join(içerik.split()))),
            None,
        )
        for k in (1, 3, K):
            say[k] += konum is not None and konum < k
        say["n"] += 1
        if konum is None or konum >= 3:
            ilk = parçalar[0][1] if parçalar else "-"
            kaçırılan.append((soru, madde, ilk))

    n = say["n"]
    print(f"{'ölçüt':28s} {'oran':>10s}")
    print("-" * 74)
    print(f"{'hedef MADDE ilk sırada':28s} {say[1]/n:>10.0%}")
    print(f"{'hedef MADDE ilk 3''te':28s} {say[3]/n:>10.0%}")
    print(f"{f'hedef MADDE ilk {K}''te':28s} {say[K]/n:>10.0%}")
    print("-" * 74)

    if kaçırılan:
        print(f"\nİlk 3'te bulunamayan {len(kaçırılan)} soru:")
        for soru, madde, ilk in kaçırılan:
            print(f"  '{soru}'")
            print(f"     hedef: MADDE {madde}   |   1. sıra: {ilk}")


if __name__ == "__main__":
    asyncio.run(main())
