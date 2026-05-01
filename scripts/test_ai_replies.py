"""AI yanıt üretim testi — farklı intent/mevzuat senaryolarını uçtan uca çalıştırır.

Çalıştır:
    cd backend
    .venv/Scripts/python.exe ../scripts/test_ai_replies.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

# Windows cmd cp1254'te UTF-8 karakterleri takılmasın
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# SQLAlchemy verbose log'unu kapat — test çıktısını kirletir
import logging as _logging
_logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_logging.getLogger("sqlalchemy.engine").setLevel(_logging.WARNING)
_logging.getLogger("sqlalchemy").setLevel(_logging.WARNING)
# email_analyzer raw LLM + post-sanitize DEBUG logları görünsün
_logging.getLogger("app.services.email_analyzer").setLevel(_logging.DEBUG)

from app.services.email_analyzer import (
    EmailAnalyzer,
    _replace_name_placeholders,
    _sanitize_reply_body,
)
from app.services.intent_detector import detect_intent
from app.services.rag_engine import RagEngine


CASES = [
    {
        "name": "Transkript talebi",
        "sender_name": "Ahmet Yılmaz",
        "subject": "Transkript talebi",
        "body": (
            "Merhaba, güncel transkriptimi alabilir miyim? Lisansüstü başvurum için "
            "noter onaylı olması gerekiyor mu?"
        ),
    },
    {
        "name": "Öğrenci belgesi",
        "sender_name": "Zeynep Kaya",
        "subject": "Öğrenci belgesi",
        "body": "İş başvurusu için öğrenci belgesine ihtiyacım var, nasıl alabilirim?",
    },
    {
        "name": "Kayıt belgesi",
        "sender_name": "Mehmet Demir",
        "subject": "Kayıt belgesi istiyorum",
        "body": "Askerlik erteleme işlemi için kayıt belgesi çıkartabilir miyim?",
    },
    {
        "name": "Not itirazı",
        "sender_name": "Elif Şahin",
        "subject": "Not itirazı prosedürü",
        "body": (
            "MAT101 final sınavından aldığım nota itiraz etmek istiyorum. "
            "Hangi süre içinde ve nereye başvurmam gerekiyor?"
        ),
    },
    {
        "name": "Kayıt dondurma",
        "sender_name": "Burak Aydın",
        "subject": "Kayıt dondurma",
        "body": (
            "Sağlık sebebiyle bu dönem kayıt dondurmak istiyorum. "
            "Hangi belgeler isteniyor ve azami kaç dönem dondurabilirim?"
        ),
    },
    {
        "name": "Genel mevzuat sorusu (ön lisans → lisans)",
        "sender_name": "Doğukan Arslan",
        "subject": "Ön lisans → lisans geçiş",
        "body": (
            "Meslek yüksekokulu mezunuyum. Lisans programlarına devam edebilmek için "
            "hangi yönetmelik geçerli? Özetleyebilir misiniz?"
        ),
    },
    {
        "name": "İsim yer tutucusu regresyon testi (sender_name boş)",
        "sender_name": None,
        "subject": "Test",
        "body": "Akademik takvim ne zaman ilan edilir?",
    },
]


async def run_one(analyzer: EmailAnalyzer, case: dict) -> dict:
    intent = await detect_intent(case["body"])
    rag_context = await analyzer._rag.query(
        f"{case['subject']} {case['body']}", intent.intent_type
    )
    rag_source_count = rag_context.count("[Kaynak") if rag_context else 0

    reply_subject, reply_body = await analyzer._generate_reply(
        email_body=case["body"],
        email_subject=case["subject"],
        intent_type=intent.intent_type,
        rag_context=rag_context or "Yönetmelik bilgisi bulunamadı.",
        sender_name=case["sender_name"],
    )

    return {
        "case": case["name"],
        "sender_name": case["sender_name"],
        "intent": intent.intent_type,
        "confidence": intent.confidence,
        "rag_source_count": rag_source_count,
        "reply_subject": reply_subject,
        "reply_body": reply_body,
    }


def _validate(result: dict) -> list[str]:
    issues: list[str] = []
    body = result["reply_body"]
    # Placeholder kaçağı var mı?
    for bad in ("[isim]", "[İsim]", "[ad]", "[Ad]", "{name}", "{{name}}", "[öğrenci adı]"):
        if bad.lower() in body.lower():
            issues.append(f"Placeholder kaçağı: {bad!r}")
    # Greeting doğru mu?
    expected_name = (result["sender_name"] or "Öğrenci").strip()
    if not any(
        line.lower().startswith(f"sayın {expected_name.lower()}")
        or line.lower().startswith("sayın öğrenci")
        for line in body.splitlines()[:3]
    ):
        issues.append(f"Başlık 'Sayın {expected_name},' değil")
    # Kapanış
    if "saygılarımızla" not in body.lower():
        issues.append("Kapanış eksik (Saygılarımızla)")
    # RAG kullanımı — confidence yüksekse ama source=0 ise uyar
    if result["rag_source_count"] == 0:
        issues.append("RAG bağlamı bulunamadı (0 kaynak)")
    return issues


async def main() -> None:
    analyzer = EmailAnalyzer()
    print(f"LLM model: {os.environ.get('OLLAMA_MODEL', 'llama3.1:8b (varsayılan)')}\n")
    print("=" * 80)

    total = len(CASES)
    for idx, case in enumerate(CASES, 1):
        print(f"\n[{idx}/{total}] {case['name']}")
        print("-" * 80)
        try:
            r = await run_one(analyzer, case)
        except Exception as exc:
            print(f"  HATA: {exc!r}")
            continue

        print(f"  Sender:    {r['sender_name']!r}")
        print(f"  Intent:    {r['intent']}  (conf={r['confidence']:.2f})")
        print(f"  RAG:       {r['rag_source_count']} kaynak")
        print(f"  Subject:   {r['reply_subject']}")
        print("  Body:")
        for line in r["reply_body"].splitlines():
            print(f"    {line}")
        issues = _validate(r)
        if issues:
            print("  [!] Sorunlar:")
            for s in issues:
                print(f"    - {s}")
        else:
            print("  [OK] Kontroller OK")

    print("\n" + "=" * 80)
    print("Placeholder regex birim testi:")
    for raw, sender, expected_contains in [
        ("Sayın [isim], merhaba.", "Ayşe", "Sayın Ayşe, merhaba."),
        ("Sayın [İsim]", None, "Sayın Öğrenci"),
        ("Hello {name}!", "Bob", "Hello Bob!"),
        ("Sayın [öğrenci adı],", "Can", "Sayın Can,"),
    ]:
        got = _replace_name_placeholders(raw, sender)
        ok = expected_contains in got
        print(f"  [{'OK' if ok else 'FAIL'}] {raw!r} + {sender!r} → {got!r}")

    print("\nSanitize birim testi:")
    cases = [
        (
            "Greeting yanlış ismi düzeltir",
            "Sayın Öğrenci,\nTranskript hakkında...\nSaygılarımızla,",
            "Ahmet Yılmaz",
            "Sayın Ahmet Yılmaz,",
        ),
        (
            "Greeting yoksa ekler",
            "Transkript hakkında bilgi verelim.\nSaygılarımızla,",
            "Ayşe",
            "Sayın Ayşe,",
        ),
        (
            "JSON kaçağını temizler",
            '{"subject": "Re: X", "body": Sayın Öğrenci, bilgi verelim."}',
            "Can",
            "Sayın Can,",
        ),
        (
            "Kaynak etiketini temizler",
            "Sayın Demir,\n[Kaynak 1 — 7.5.8315.pdf] Madde 3'e göre...",
            "Demir",
            "Madde 3",
        ),
    ]
    for label, raw, sender, must_contain in cases:
        got = _sanitize_reply_body(raw, sender)
        ok = must_contain in got
        short = got.replace("\n", " | ")[:120]
        print(f"  [{'OK' if ok else 'FAIL'}] {label} → {short!r}")


if __name__ == "__main__":
    asyncio.run(main())
