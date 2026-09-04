"""Reranker istemcisi — HF Text Embeddings Inference (TEI) /rerank uç noktası.

Faz 7 (kill-criterion'lı, bkz. YOL_HARİTASI.md). Ollama cross-encoder servis
etmiyor, bu yüzden ayrı bir TEI container'ı (docker-compose.yml: reranker).

API şeması gerçek bir TEI container'ına karşı doğrulandı (bge-reranker-base,
tei v1.9.3):
  POST /rerank {"query": str, "texts": [str, ...]}
  -> [{"index": int, "score": float}, ...]  (skora göre azalan sırada)
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def rerank(query: str, texts: list[str]) -> list[float] | None:
    """Her metin için reranker skoru döner (texts ile AYNI SIRADA).

    Hata/timeout durumunda None döner — çağıran RRF sırasına düşmeli,
    istek asla başarısız olmamalı (roadmap: "isteği asla düşürme").
    """
    if not texts:
        return []

    try:
        async with httpx.AsyncClient(
            base_url=settings.RERANKER_URL,
            timeout=settings.RERANKER_TIMEOUT_MS / 1000,
        ) as client:
            resp = await client.post(
                "/rerank", json={"query": query, "texts": texts}
            )
            resp.raise_for_status()
            sonuçlar = resp.json()

        skorlar = [0.0] * len(texts)
        for kayıt in sonuçlar:
            skorlar[kayıt["index"]] = kayıt["score"]
        return skorlar
    except Exception as exc:
        logger.warning("Reranker başarısız/zaman aşımı, RRF sırasına düşülüyor: %s", exc)
        return None
