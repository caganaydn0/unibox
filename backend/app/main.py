import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.events import lifespan

logging.basicConfig(
    level=logging.DEBUG if settings.APP_ENV == "development" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_geliştirme = settings.APP_ENV == "development"

app = FastAPI(
    title="UniBox API",
    description="KVKK uyumlu üniversite AI asistanı — Admin Dashboard ve Chat API",
    version="0.1.0",
    lifespan=lifespan,
    # Prod'da docs'u kapat.
    # openapi_url da kapatılmalı: docs_url=None tek başına şemayı kapatmıyor,
    # /openapi.json anonim erişime açık kalıyor ve tüm uç listesini,
    # model alanlarını ifşa ediyordu.
    docs_url="/docs" if _geliştirme else None,
    redoc_url="/redoc" if _geliştirme else None,
    openapi_url="/openapi.json" if _geliştirme else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_listesi,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları kayıt et
from app.api.v1.router import router as v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Sığ canlılık kontrolü — süreç ayakta mı?

    Bağımlılıkları KONTROL ETMEZ; süreç yöneticisinin (systemd/Docker)
    "yeniden başlat" kararı için. Bağımlılıklar için /ready kullanın.
    """
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/ready", tags=["system"])
async def ready() -> JSONResponse:
    """Gerçek hazırlık kontrolü — bağımlılıklar ve worker'lar.

    /health eskiden Postgres ve Ollama tamamen kapalıyken bile 200 dönüyordu;
    yük dengeleyici ve yeniden başlatma politikaları buna bakarak yanlış karar
    veriyordu. Worker canlılığı da kontrol ediliyor: e-posta gönderimi tamamen
    durmuşken sistemin "sağlıklı" görünmesi en sinsi arıza biçimiydi.
    """
    from sqlalchemy import text

    from app.db.session import engine

    kontroller: dict[str, str] = {}

    # 1. Veritabanı
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        kontroller["database"] = "ok"
    except Exception as exc:
        kontroller["database"] = f"hata: {type(exc).__name__}"

    # 2. Ollama (LLM + embedding). RAG bunsuz sözcüksel aramaya düşer,
    #    yani "degraded" — tamamen çökmüş değil.
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as istemci:
            yanıt = await istemci.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            yanıt.raise_for_status()
            modeller = {m["name"].split(":")[0] for m in yanıt.json().get("models", [])}
        eksik = {settings.OLLAMA_MODEL.split(":")[0], settings.EMBEDDING_MODEL} - modeller
        kontroller["ollama"] = "ok" if not eksik else f"model eksik: {sorted(eksik)}"
    except Exception as exc:
        kontroller["ollama"] = f"hata: {type(exc).__name__}"

    # 3. Arka plan worker'ları
    görevler = getattr(app.state, "worker_tasks", [])
    ölü = [t.get_name() for t in görevler if t.done()]
    kontroller["workers"] = "ok" if not ölü else f"ölü: {ölü}"

    hazır = kontroller["database"] == "ok" and not ölü
    return JSONResponse(
        status_code=200 if hazır else 503,
        content={"ready": hazır, "checks": kontroller, "env": settings.APP_ENV},
    )
