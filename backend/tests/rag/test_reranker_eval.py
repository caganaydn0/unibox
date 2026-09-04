"""Faz 7 kill-criterion ölçümü — reranker açıkken madde@1 gerçekten iyileşiyor mu?

Bu, sürekli çalışan bir regresyon testi DEĞİL (bkz. test_retrieval.py için
o). Tek seferlik bir KARAR ölçümü: reranker'ı zorla açıp aynı soru setini
(regulation_madde.jsonl) dondurulmuş reranker'sız baseline'a (yonetmelik_madde.json)
karşı `paired_diff` ile karşılaştırır.

Reranker servisi (docker-compose.yml: reranker) ayakta değilse atlanır —
CI'da veya reranker container'ı olmayan bir makinede bu testin varlığı
mevcut hiçbir işi bozmaz.

Çalıştırma: uv run pytest tests/rag/test_reranker_eval.py -s
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import pytest

from tests.rag.metrics import Ölçüm, paired_diff, tablo
from tests.rag.test_retrieval import _madde_içeriyor, _soruları_oku

pytestmark = pytest.mark.rag_eval


def _reranker_ayakta() -> bool:
    from app.config import settings

    p = urlparse(settings.RERANKER_URL)
    try:
        with socket.create_connection((p.hostname or "localhost", p.port or 80), timeout=1.5):
            return True
    except OSError:
        return False


async def test_reranker_madde_at_1_karsilastirma(korpus, monkeypatch) -> None:
    if not _reranker_ayakta():
        pytest.skip(
            "Reranker erişilemiyor — `docker compose up -d reranker` ile başlatın "
            "(bkz. YOL_HARİTASI.md Faz 7)."
        )

    # Bu ölçüm KALİTE tavanını bulmaya çalışıyor — üretim gecikme bütçesi
    # (800ms) ayrı bir soru. Üretim bütçesiyle koşulursa her çağrı zaman
    # aşımına uğrayıp sessizce RRF'ye düşer ve "reranked" ölçüm aslında
    # rerank'siz ölçümle birebir aynı çıkar (ölçüldü — ilk denemede 55
    # sorunun 55'i de timeout'a düştü).
    from app.config import settings
    monkeypatch.setattr(settings, "RERANKER_TIMEOUT_MS", 30_000)

    from app.services.rag_engine import RagEngine

    sorular = _soruları_oku("regulation_madde.jsonl")

    ölçüm = Ölçüm("yonetmelik_madde_reranked")
    rag = RagEngine()
    for kayıt in sorular:
        parçalar = await rag.search(kayıt["soru"], None, use_reranker=True)
        konum = next(
            (i for i, (içerik, _e, _t) in enumerate(parçalar)
             if _madde_içeriyor(içerik, kayıt["madde"])),
            None,
        )
        ölçüm.ekle(kayıt["soru"], konum)

    print("\n" + tablo(ölçüm))

    baseline = Ölçüm("yonetmelik_madde").baseline_oku()
    if baseline is None:
        pytest.skip(
            "'yonetmelik_madde' için baseline yok — önce reranker'sız baseline'ı "
            "dondurun: UNIBOX_WRITE_BASELINE=1 uv run pytest tests/rag/test_retrieval.py -s"
        )

    for k in (1, 3, 7):
        fark = paired_diff(baseline["konumlar"], ölçüm, k)
        print(f"  reranker'sız baseline'a göre {fark}")
        if fark.düzelen:
            print(f"    düzelen: {fark.düzelen}")
        if fark.bozulan:
            print(f"    bozulan: {fark.bozulan}")

    fark_at_1 = paired_diff(baseline["konumlar"], ölçüm, 1)
    net = len(fark_at_1.düzelen) - len(fark_at_1.bozulan)
    print(
        f"\n  KILL-CRITERION (madde@1): düzelen={len(fark_at_1.düzelen)} "
        f"bozulan={len(fark_at_1.bozulan)} net={net}"
    )
    if net >= 5 and len(fark_at_1.düzelen) > len(fark_at_1.bozulan):
        print("  => ESIK GECILDI: RERANKER_ENABLED varsayilani True yapilabilir.")
    else:
        print("  => ESIK GECILEMEDI: RERANKER_ENABLED=False varsayilaninda kalinmali.")
