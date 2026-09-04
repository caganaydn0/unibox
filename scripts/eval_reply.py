"""Gelen e-posta yanıtı: belgeden cevap üretebiliyor mu, üretemediğinde geri çekiliyor mu?

İki soruyu ayrı ayrı ölçer:

1. KAPSAM İÇİ sorular — cevabı bilgi tabanında olan gerçek talepler.
   Beklenen: yanıt mevzuata atıf yapsın ("... Madde N uyarınca"), somut
   bilgi versin, "öğrenci işlerine danışınız" ile geçiştirmesin.

2. KAPSAM DIŞI sorular — cevabı bilgi tabanında OLMAYAN talepler
   (otopark ücreti, yemekhane menüsü vb.).
   Beklenen: uydurmasın, "Daha detaylı bilgi için öğrenci işlerine
   danışınız." yazsın.

İkinci grup kritik: bir asistanın bilmediğini söyleyebilmesi, bildiğini
söylemesi kadar önemli. Uydurulmuş bir prosedür öğrenciyi yanlış yönlendirir.

Kullanım:
    cd backend && uv run python ../scripts/eval_reply.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings  # noqa: E402
from app.services.email_analyzer import EmailAnalyzer  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402

# (soru, intent) — cevabı bilgi tabanında MEVCUT
KAPSAM_ICI = [
    ("Sınav sonucuma itiraz etmek istiyorum, ne kadar sürem var?", "grade_objection"),
    ("Transkript belgemi nasıl alabilirim, kaç günde hazır olur?", "transcript_request"),
    ("Kayıt dondurmak istiyorum, şartları neler?", "leave_of_absence"),
    ("Yaz okulunda not yükseltmek için ders alabilir miyim?", "general_question"),
    ("Erasmus başvuruları ne zaman yapılıyor, hangi belgeler gerekiyor?", "general_question"),
    ("Genel not ortalamam 2.00'ın altında kaldı, sonucu ne olur?", "general_question"),
]

# (soru, intent) — cevabı bilgi tabanında YOK
KAPSAM_DISI = [
    ("Kampüs otoparkı ücretli mi, aylık abonelik ne kadar?", "general_question"),
    ("Yemekhanede vegan menü seçeneği var mı?", "general_question"),
    ("Mezuniyet törenine kaç kişi davet edebilirim?", "general_question"),
    ("Öğrenci kulübü kurmak için nereye başvurmalıyım?", "general_question"),
    ("Kampüs içinde bisiklet kiralama hizmeti var mı?", "general_question"),
    ("Bilgisayar mühendisliği bölümünün geçen yılki taban puanı kaçtı?", "general_question"),
]

_FALLBACK_RE = re.compile(r"öğrenci\s*işlerine\s*(?:danış|başvur)", re.IGNORECASE)
_ATIF_RE = re.compile(r"madde\s*\d+", re.IGNORECASE)

# Uydurma göstergesi: somut sayısal iddia (ücret, süre, adet, oran).
# Kapsam dışı bir soruda bunlardan biri geçiyorsa model bilgi uydurmuş demektir.
_SOMUT_RE = re.compile(
    r"\d+\s*(?:TL|₺|lira|gün|hafta|ay|yıl|kişi|adet|kredi|%|puan)", re.IGNORECASE
)


def _sınıfla(body: str, kapsam_ici: bool) -> str:
    """Yanıtı davranışına göre sınıflandırır."""
    fb = bool(_FALLBACK_RE.search(body))
    somut = bool(_SOMUT_RE.search(body))
    gövde = " ".join(body.split())
    # Yalnızca yönlendirme: fallback var, somut iddia yok, kısa
    if fb and not somut and len(gövde) < 400:
        return "yalnızca yönlendirdi"
    if somut and not kapsam_ici:
        return "UYDURDU (somut iddia)"
    if fb and somut:
        return "cevap verdi + yönlendirdi"
    if fb:
        return "yönlendirdi"
    return "cevap verdi"


async def grup_ölç(analyzer: EmailAnalyzer, rag: RagEngine,
                   sorular: list[tuple[str, str]], etiket: str,
                   kapsam_ici: bool) -> dict:
    print(f"\n{'=' * 76}\n{etiket}\n{'=' * 76}")
    sayaç: dict[str, int] = {"n": 0, "uydurma": 0, "yalnız_yönlendirme": 0,
                             "atıf": 0, "boş_bağlam": 0}
    for soru, intent in sorular:
        ctx = await rag.query(soru, intent if intent != "general_question" else None)
        if not ctx:
            sayaç["boş_bağlam"] += 1
        _, body = await analyzer._generate_reply(  # noqa: SLF001
            email_body=soru, email_subject="Öğrenci talebi",
            intent_type=intent, rag_context=ctx, sender_name="Test Öğrenci",
        )
        sınıf = _sınıfla(body, kapsam_ici)
        sayaç["n"] += 1
        sayaç["uydurma"] += sınıf.startswith("UYDURDU")
        sayaç["yalnız_yönlendirme"] += sınıf == "yalnızca yönlendirdi"
        sayaç["atıf"] += bool(_ATIF_RE.search(body))
        print(f"\n  SORU   : {soru}")
        print(f"  BAĞLAM : {'boş (kapsam dışı sayıldı)' if not ctx else f'{len(ctx)} karakter'}")
        print(f"  DURUM  : {sınıf}")
        print(f"  YANIT  : {' '.join(body.split())[:200]}")
    return sayaç


async def main() -> None:
    print(f"Model     : {settings.OLLAMA_MODEL}")
    print(f"Embedding : {settings.EMBEDDING_MODEL}")
    analyzer = EmailAnalyzer()
    rag = RagEngine()

    içi = await grup_ölç(analyzer, rag, KAPSAM_ICI,
                         "KAPSAM İÇİ — cevap bilgi tabanında VAR", kapsam_ici=True)
    dışı = await grup_ölç(analyzer, rag, KAPSAM_DISI,
                          "KAPSAM DIŞI — cevap bilgi tabanında YOK", kapsam_ici=False)

    print(f"\n{'=' * 76}\nÖZET\n{'=' * 76}")
    n1, n2 = içi["n"], dışı["n"]
    print(f"{'':34s} {'kapsam içi':>14s} {'kapsam dışı':>14s}")
    print("-" * 76)
    print(f"{'bağlam boş döndü (kapsam dışı)':34s} {içi['boş_bağlam']/n1:>14.0%} {dışı['boş_bağlam']/n2:>14.0%}")
    print(f"{'UYDURDU (somut iddia)':34s} {'—':>14s} {dışı['uydurma']/n2:>14.0%}")
    print(f"{'yalnızca yönlendirdi':34s} {içi['yalnız_yönlendirme']/n1:>14.0%} {dışı['yalnız_yönlendirme']/n2:>14.0%}")
    print(f"{'mevzuata atıf yaptı':34s} {içi['atıf']/n1:>14.0%} {dışı['atıf']/n2:>14.0%}")
    print("-" * 76)
    print("Kapsam içi : 'yalnızca yönlendirdi' DÜŞÜK olmalı — cevabı vermeli.")
    print("Kapsam dışı: 'UYDURDU' SIFIR, 'yalnızca yönlendirdi' YÜKSEK olmalı.")


if __name__ == "__main__":
    asyncio.run(main())
