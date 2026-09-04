"""Geri getirim metrikleri ve baseline karşılaştırması.

Üç eval scripti aynı recall@k döngüsünü birbirinden bağımsız olarak yazmıştı
(eval_retrieval.py:141, eval_retrieval_docs.py:110, eval_regulation.py:76).
Tek yerde topluyoruz.

EŞLEŞTİRİLMİŞ (PAIRED) RAPORLAMA — bu modülün asıl varlık sebebi:

  eval_regulation.py n=16 ile çalışıyor. p=0.75'te binom standart hatası
  10.8 puan. Yani "%75 -> %81" farkı gürültünün içinde kalıyor ve bir
  iyileştirmenin işe yarayıp yaramadığı SÖYLENEMEZ.

  Çözüm yüzdeleri karşılaştırmak değil, aynı soruların tek tek ne olduğuna
  bakmak: "5 soru düzeldi, 0 soru bozuldu" n=16'da bile anlamlıdır.
  Her faz raporu bu formatta olmalı.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASELINE_DIZINI = Path(__file__).resolve().parent / "baselines"


@dataclass
class Sonuç:
    """Tek bir sorunun sonucu: hedef kaçıncı sırada bulundu (yoksa None)."""

    soru: str
    konum: int | None

    def ilk_k(self, k: int) -> bool:
        return self.konum is not None and self.konum < k


@dataclass
class Ölçüm:
    ad: str
    sonuçlar: list[Sonuç] = field(default_factory=list)

    def ekle(self, soru: str, konum: int | None) -> None:
        self.sonuçlar.append(Sonuç(soru, konum))

    @property
    def n(self) -> int:
        return len(self.sonuçlar)

    def recall(self, k: int) -> float:
        if not self.sonuçlar:
            return 0.0
        return sum(s.ilk_k(k) for s in self.sonuçlar) / self.n

    def isabet(self, k: int) -> int:
        return sum(s.ilk_k(k) for s in self.sonuçlar)

    def mrr(self) -> float:
        if not self.sonuçlar:
            return 0.0
        return sum(
            1.0 / (s.konum + 1) for s in self.sonuçlar if s.konum is not None
        ) / self.n

    def metrikler(self, ks: tuple[int, ...] = (1, 3, 7)) -> dict[str, float]:
        d = {f"recall@{k}": round(self.recall(k), 4) for k in ks}
        d["mrr"] = round(self.mrr(), 4)
        d["n"] = self.n
        return d

    def kaçırılanlar(self, k: int) -> list[str]:
        return [s.soru for s in self.sonuçlar if not s.ilk_k(k)]

    # -- baseline --------------------------------------------------------- #

    def baseline_yolu(self) -> Path:
        return BASELINE_DIZINI / f"{self.ad}.json"

    def baseline_yaz(self, damga: str) -> Path:
        yol = self.baseline_yolu()
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(
            json.dumps(
                {
                    "ad": self.ad,
                    "korpus_damgası": damga,
                    "metrikler": self.metrikler(),
                    "konumlar": {s.soru: s.konum for s in self.sonuçlar},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return yol

    def baseline_oku(self) -> dict | None:
        yol = self.baseline_yolu()
        if not yol.exists():
            return None
        return json.loads(yol.read_text(encoding="utf-8"))


@dataclass
class Fark:
    """İki ölçüm arasındaki eşleştirilmiş karşılaştırma."""

    düzelen: list[str]
    bozulan: list[str]
    değişmeyen: int
    k: int

    def __str__(self) -> str:
        return (
            f"@{self.k}: {len(self.düzelen)} düzeldi, {len(self.bozulan)} bozuldu, "
            f"{self.değişmeyen} değişmedi"
        )

    @property
    def gerileme_var(self) -> bool:
        return bool(self.bozulan)


def paired_diff(önce: dict[str, int | None], sonra: Ölçüm, k: int) -> Fark:
    """Soru bazında önce/sonra karşılaştırması.

    `önce`, baseline dosyasındaki {soru: konum} eşlemesi.
    Yalnızca iki tarafta da bulunan sorular karşılaştırılır; soru seti
    değiştiyse sessizce yanlış sonuç üretmek yerine ortak kümeye bakarız.
    """
    düzelen: list[str] = []
    bozulan: list[str] = []
    değişmeyen = 0

    for s in sonra.sonuçlar:
        if s.soru not in önce:
            continue  # yeni eklenen soru — karşılaştırmaya girmez
        eski_konum = önce[s.soru]
        eski_isabet = eski_konum is not None and eski_konum < k
        yeni_isabet = s.ilk_k(k)
        if yeni_isabet and not eski_isabet:
            düzelen.append(s.soru)
        elif eski_isabet and not yeni_isabet:
            bozulan.append(s.soru)
        else:
            değişmeyen += 1

    return Fark(düzelen, bozulan, değişmeyen, k)


def tablo(ölçüm: Ölçüm, ks: tuple[int, ...] = (1, 3, 7)) -> str:
    satırlar = [f"{ölçüm.ad}  (n={ölçüm.n})", "-" * 46]
    for k in ks:
        satırlar.append(
            f"  recall@{k:<3} {ölçüm.recall(k):>7.0%}   ({ölçüm.isabet(k)}/{ölçüm.n})"
        )
    satırlar.append(f"  {'MRR':<10} {ölçüm.mrr():>7.3f}")
    return "\n".join(satırlar)
