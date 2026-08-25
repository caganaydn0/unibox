from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env dosyasını MUTLAK yolla çözüyoruz. Göreli ".env" yalnızca süreç
# backend/ dizininden başlatıldığında bulunuyordu; başka bir çalışma
# dizininden (systemd, konteyner, kök dizinden uvicorn) başlatıldığında
# dosya SESSİZCE yok sayılıyor ve uygulama aşağıdaki CHANGE_ME
# varsayılanlarıyla açılıyordu.
_ENV_DOSYASI = Path(__file__).resolve().parent.parent / ".env"

# Üretimde kabul edilemez varsayılanlar
_GUVENSIZ_VARSAYILANLAR = {
    "CHANGE_ME_IN_PRODUCTION",
    "CHANGE_ME",
    "CHANGE_ME_FERNET_KEY",
    "CHANGE_ME_RANDOM_32_CHARS",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_DOSYASI,
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
    # bge-m3: çok dilli embedding modeli. nomic-embed-text ağırlıklı İngilizce
    # eğitildiği için Türkçe sorularda zayıf kalıyordu.
    # Model veya boyut değiştirilirse: yeni bir Alembic migration ile
    # document_chunks.embedding kolonu güncellenmeli, ardından
    # scripts/reindex_documents.py çalıştırılmalı.
    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIMENSIONS: int = 1024
    # 150 kelimelik chunk denendi ve ÖLÇÜMLE ELENDİ: büyük bir PDF 20 yerine
    # 74 chunk'a bölününce aday havuzunu doldurup tek chunk'lık kısa
    # dokümanları dışarı itti (recall@3 %70 -> %50). Doküman başına chunk
    # sayısındaki dengesizlik, chunk uzunluğundaki dengesizlikten daha zararlı.
    # Değiştirirseniz sonrasında: scripts/reindex_documents.py
    RAG_CHUNK_SIZE: int = 500        # kelime başına chunk
    RAG_CHUNK_OVERLAP: int = 50      # kelime örtüşmesi
    RAG_TOP_K: int = 7               # benzerlik araması sonuç sayısı

    # Kapsam dışı soru eşiği (kosinüs mesafesi). En yakın chunk bu değerden
    # uzaksa soru bilgi tabanının kapsamı dışında sayılır ve LLM'e HİÇ bağlam
    # verilmez — böylece eline tutuşturulan alakasız metinden cevap uydurmaz.
    #
    # Kalibrasyon (81 kapsam içi soru: intent_test + kısa doküman + yönetmelik,
    # 5 kapsam dışı soru). Dağılımlar örtüşüyor, kusursuz ayrım yok:
    #   eşik   kapsam içi kayıp   kapsam dışı yakalanan
    #   0.47              7%                    80%
    #   0.50              1%                    40%   <-- seçilen
    #   0.55              0%                    20%
    #
    # Asıl savunma hattı eşik DEĞİL, prompt. Ölçüldü: eşik tamamen devre dışı
    # bırakıldığında bile, "bağlam ilgisizse uydurma" kuralı sayesinde 6 kapsam
    # dışı sorunun 6'sı doğru şekilde öğrenci işlerine yönlendirildi (düzeltme
    # öncesi model otopark ücretini "aylık 150 TL" diye uydurmuştu).
    #
    # Denenen eşikler ve geri getirimde yarattığı kayıp (etiketli intent, recall@7):
    #   0.47 -> %82  (çok agresif, meşru soruların altıda birini reddetti)
    #   0.50 -> %89
    #   0.60 -> %97  (ölçülen kayıp yok)
    # Bu yüzden eşik yalnızca uç durumlar için emniyet ağı olarak, maliyetinin
    # sıfır olduğu noktada tutuluyor.
    RAG_MAX_DISTANCE: float = 0.60

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

    # CORS — virgülle ayrılmış origin listesi.
    # Boş bırakılırsa development'ta http://localhost:3000 varsayılır.
    # Üretimde kurumun gerçek alan adı yazılmalı:
    #   CORS_ORIGINS=https://unibox.universite.edu.tr
    # Tarayıcı istekleri normalde Next.js BFF proxy'sinden geçtiği için CORS
    # devreye girmez; bu liste doğrudan erişim senaryoları içindir.
    CORS_ORIGINS: str = ""

    @property
    def cors_origin_listesi(self) -> list[str]:
        if self.CORS_ORIGINS.strip():
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return ["http://localhost:3000"] if self.APP_ENV == "development" else []

    @model_validator(mode="after")
    def _uretimde_guvenli_mi(self) -> "Settings":
        """APP_ENV=production iken güvensiz varsayılanlarla açılmayı reddeder.

        Bu değerler kaynak kodda yazılı olduğu için "varsayılan" değil, bilinen
        sabitlerdir: SECRET_KEY bilinirse herkes geçerli bir admin JWT'si
        imzalayabilir, FERNET_KEY bilinirse şifreli tüm veri okunabilir.

        Sessizce açılmak, sorunu fark edilmez kılıyordu. Erken ve gürültülü
        başarısız olmak, üretimde açık bir sistemden iyidir.
        """
        if self.APP_ENV != "production":
            return self

        sorunlar: list[str] = []
        for ad in ("SECRET_KEY", "FERNET_KEY", "ADMIN_PASSWORD"):
            if getattr(self, ad) in _GUVENSIZ_VARSAYILANLAR:
                sorunlar.append(f"{ad} hâlâ şablon değerinde")
        if len(self.SECRET_KEY) < 32:
            sorunlar.append("SECRET_KEY en az 32 karakter olmalı")
        if self.SMTP_BACKEND == "console":
            sorunlar.append(
                "SMTP_BACKEND='console' — e-postalar gönderilmez, yalnızca loglanır"
            )
        if not _ENV_DOSYASI.exists():
            sorunlar.append(f"{_ENV_DOSYASI} bulunamadı; ayarlar varsayılanlardan geliyor")

        if sorunlar:
            raise ValueError(
                "Üretim yapılandırması güvenli değil:\n  - "
                + "\n  - ".join(sorunlar)
                + "\n\nFERNET_KEY üretmek için:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                "DİKKAT: canlı veritabanı varsa FERNET_KEY'i YENİDEN ÜRETMEYİN, "
                "mevcut şifreli veri okunamaz hâle gelir."
            )
        return self

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
