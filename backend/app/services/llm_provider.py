"""LLM Provider Soyutlama

UNIBOX_LLM_BACKEND env var'a göre Ollama REST API veya llama-cpp-python kullanır.
Her iki backend de aynı async generate() arayüzünü sunar.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.config import settings

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: str = "", format: str | None = None) -> str:
        """Kullanıcı mesajını alıp asistan yanıtı döner.

        format="json" verildiğinde çıktı dilbilgisi seviyesinde geçerli JSON'a
        zorlanır. Küçük modeller "JSON döndür" talimatını yok sayıp düz metin
        veya prompt'un kendisini geri yansıtabiliyor; bu parametre o riski
        modelden bağımsız olarak ortadan kaldırır.
        """
        ...


class OllamaProvider(BaseLLMProvider):
    """Ollama REST API üzerinden LLM."""

    def __init__(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=300.0)
        self._model = settings.OLLAMA_MODEL

    async def generate(self, prompt: str, system: str = "", format: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            # Resmi e-posta yanıtı — yaratıcılık yerine tutarlılık istiyoruz.
            # Düşük temperature halüsinasyon ve off-topic sapmayı azaltır.
            # num_ctx: Ollama'nın varsayılanı (2048) RAG bağlamını sessizce
            # kırpıp uydurmaya yol açıyordu — bkz. config.py:OLLAMA_NUM_CTX.
            "options": {"temperature": 0.2, "top_p": 0.9, "num_ctx": settings.OLLAMA_NUM_CTX},
        }
        if format:
            # Ollama çıktıyı grammar ile kısıtlar — model ne üretmek isterse
            # istesin sonuç parse edilebilir JSON olur.
            payload["format"] = format

        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """Ollama /api/embeddings ile metin → vektör."""
        resp = await self._client.post(
            "/api/embeddings",
            json={
                "model": model or settings.EMBEDDING_MODEL,
                "prompt": text,
            },
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def aclose(self) -> None:
        await self._client.aclose()


class LlamaCppProvider(BaseLLMProvider):
    """llama-cpp-python üzerinden doğrudan GGUF yükleme."""

    def __init__(self) -> None:
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "llama-cpp-python yüklü değil. "
                "pyproject.toml'da llama-cpp-python bağımlılığını aktif edin."
            ) from e

        logger.info("GGUF model yükleniyor: %s", settings.LLAMA_CPP_MODEL_PATH)
        self._llm = Llama(
            model_path=settings.LLAMA_CPP_MODEL_PATH,
            n_ctx=settings.LLAMA_CPP_N_CTX,
            n_gpu_layers=settings.LLAMA_CPP_N_GPU_LAYERS,
            verbose=False,
        )

    async def generate(self, prompt: str, system: str = "", format: str | None = None) -> str:
        import asyncio

        # llama-cpp-python senkron API — thread pool'da çalıştır
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {"messages": messages}
        if format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._llm.create_chat_completion(**kwargs),
        )
        return response["choices"][0]["message"]["content"]


def get_llm_provider() -> BaseLLMProvider:
    """Config'e göre doğru provider'ı döner."""
    backend = settings.UNIBOX_LLM_BACKEND.lower()
    if backend == "ollama":
        return OllamaProvider()
    elif backend == "llama_cpp":
        return LlamaCppProvider()
    else:
        raise ValueError(f"Bilinmeyen LLM backend: {backend}")


# Singleton — uygulama başında bir kez oluşturulur
_provider: BaseLLMProvider | None = None


def llm() -> BaseLLMProvider:
    global _provider
    if _provider is None:
        _provider = get_llm_provider()
    return _provider
