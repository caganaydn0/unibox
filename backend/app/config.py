from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Genel
    APP_ENV: str = "development"
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "CHANGE_ME"

    # Veritabanı (PostgreSQL + pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/unibox"

    # KVKK: Fernet şifreleme anahtarı
    FERNET_KEY: str = "CHANGE_ME_FERNET_KEY"

    # LLM
    UNIBOX_LLM_BACKEND: str = "ollama"  # "ollama" | "llama_cpp"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    LLAMA_CPP_MODEL_PATH: str = "./models/llama-3.1-8b.gguf"
    LLAMA_CPP_N_CTX: int = 8192
    LLAMA_CPP_N_GPU_LAYERS: int = 0

    # Embedding (RAG)
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSIONS: int = 768
    RAG_CHUNK_SIZE: int = 500        # kelime başına chunk
    RAG_CHUNK_OVERLAP: int = 50      # kelime örtüşmesi
    RAG_TOP_K: int = 7               # benzerlik araması sonuç sayısı

    # SMTP
    SMTP_BACKEND: str = "console"    # "console" | "smtp"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "unibox@university.edu.tr"
    SMTP_FROM_NAME: str = "UniBox Asistan"
    SMTP_USE_TLS: bool = False
    SMTP_MAX_RETRIES: int = 3

    # IMAP (Gelen e-posta)
    IMAP_BACKEND: str = "disabled"       # "disabled" | "imap"
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USERNAME: str = ""
    IMAP_PASSWORD: str = ""              # Gmail App Password
    IMAP_USE_SSL: bool = True
    IMAP_MAILBOX: str = "INBOX"
    IMAP_POLL_INTERVAL_SECONDS: int = 30
    IMAP_MAX_FETCH_PER_POLL: int = 10
    INCOMING_EMAIL_RETENTION_DAYS: int = 180

    # Dosya yükleme (PDF'ler DB'de BYTEA olarak saklanır)
    MAX_UPLOAD_SIZE_MB: int = 20

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # KVKK veri saklama
    CONVERSATION_RETENTION_DAYS: int = 90
    EMAIL_LOG_RETENTION_DAYS: int = 180

    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30

    @property
    def upload_max_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def allowed_mime_types(self) -> set[str]:
        return {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "text/markdown",
        }


settings = Settings()
