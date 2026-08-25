"""Intent Detector

Öğrenci mesajından intent'i sınıflandırır.
LLM tabanlı zero-shot sınıflandırma kullanır.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.services.llm_provider import llm

logger = logging.getLogger(__name__)

# E-posta gerektiren intent tipleri
EMAIL_REQUIRED_INTENTS = {
    "transcript_request",
    "certificate_request",
    "enrollment_letter",
    "leave_of_absence",
    "complaint",
    "grade_objection",
}

INTENT_DESCRIPTIONS = {
    "transcript_request": "Transkript belgesi talebi",
    "certificate_request": "Öğrenci belgesi / sertifika talebi",
    "enrollment_letter": "Kayıt belgesi talebi",
    "leave_of_absence": "İzin / kayıt dondurma talebi",
    "complaint": "Şikayet veya itiraz",
    "grade_objection": "Not itirazı",
    "general_question": "Genel bilgi sorusu (e-posta gerektirmez)",
    "other": "Diğer",
}

CLASSIFIER_SYSTEM = """You are a university assistant classifier. Classify the student message into one of these categories and return ONLY a JSON object, nothing else.

Categories:
- transcript_request: Requesting a transcript document
- certificate_request: Requesting a student certificate
- enrollment_letter: Requesting an enrollment letter
- leave_of_absence: Requesting leave or enrollment freeze
- complaint: A complaint or objection
- grade_objection: Grade objection
- general_question: General information question
- other: Other

Return ONLY this JSON, no other text:
{"intent": "category_name", "confidence": 0.9, "requires_email": true}"""


@dataclass
class IntentResult:
    intent_type: str
    confidence: float
    requires_email: bool
    raw_output: str


async def detect_intent(message: str) -> IntentResult:
    """Mesajdan intent'i tespit et."""
    raw = ""
    try:
        raw = await llm().generate(
            prompt=f"Öğrenci mesajı: {message}",
            system=CLASSIFIER_SYSTEM,
            format="json",
        )
        # JSON çıktısını parse et
        # LLM bazen markdown kod bloğu veya açıklayıcı metin ekler — temizle
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(
                line for line in lines if not line.startswith("```")
            )
        # JSON bloğunu bul (LLM bazen öncesine/sonrasına metin ekler)
        json_match = re.search(r'\{[^{}]*"intent"[^{}]*\}', clean)
        if json_match:
            clean = json_match.group(0)
        data = json.loads(clean)
        intent_type = data.get("intent", "other")
        confidence = float(data.get("confidence", 0.7))
        # LLM requires_email'i yanlış döndürebilir — intent tipine göre override et
        requires_email = intent_type in EMAIL_REQUIRED_INTENTS

        return IntentResult(
            intent_type=intent_type,
            confidence=confidence,
            requires_email=requires_email,
            raw_output=raw,
        )
    except Exception as exc:
        logger.warning("Intent tespiti başarısız: %s — fallback: general_question", exc)
        return IntentResult(
            intent_type="general_question",
            confidence=0.5,
            requires_email=False,
            raw_output=raw,
        )
