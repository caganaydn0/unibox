# syntax=docker/dockerfile:1
#
# uv ile çok aşamalı derleme. Faz 6 (dağıtım paketi) — YOL_HARİTASI.md.
#
# Migration'lar bu imajda OTOMATİK ÇALIŞTIRILMAZ (kasıtlı): bir migration
# hatası container'ı yeniden başlatma döngüsüne sokar. Deploy adımı olarak
# elle çalıştırın:
#   docker compose -f docker-compose.prod.yml run --rm backend \
#     uv run alembic upgrade head

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Önce yalnızca bağımlılık manifestoları kopyalanır — kaynak kodu değişince
# bu (pahalı) katman cache'ten düşmesin.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# python-magic (dosya yükleme MIME doğrulaması, app/services/knowledge
# uçlarında kullanılıyor) çalışma zamanında libmagic paylaşımlı kütüphanesine
# ihtiyaç duyar. python-magic-bin yalnızca Windows için (pyproject.toml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 unibox
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER unibox

EXPOSE 8000

# /health: sığ canlılık kontrolü (bkz. main.py) — süreç ayakta mı, üretim
# amacıyla tam olarak bunun için tasarlandı. Bağımlılık kontrolü için /ready
# ayrıca var ama container HEALTHCHECK'i için kasıtlı olarak kullanılmadı:
# Postgres/Ollama geçici bir kesintide backend'i "unhealthy" işaretleyip
# yeniden başlatmak, kesintiyi çözmeyip sadece ek bir arıza katmanı ekler.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# --ws-ping-timeout: uvicorn varsayılanı (20sn) ile chat_websocket tek bir
# yavaş LLM yanıtını işlerken (ölçüldü: 88-95sn, RAG bağlamı büyükse daha da
# uzayabilir) bağlantıyı SUNUCU KENDİSİ 1011 "keepalive ping timeout" ile
# kapatıyordu — yanıt DB'ye kaydediliyor ama öğrenciye hiç ulaşmıyordu.
# llm_provider.py'nin kendi httpx timeout'uyla (300sn) aynı üst sınır.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ws-ping-interval", "20", "--ws-ping-timeout", "300"]
