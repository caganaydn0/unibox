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

    # Admin parolası — İKİ BİÇİM desteklenir:
    #
    #   ADMIN_PASSWORD_HASH : bcrypt özeti (ÖNERİLEN, üretimde ZORUNLU)
    #   ADMIN_PASSWORD      : düz metin (yalnızca geliştirme kolaylığı)
    #
    # Hash üretmek için:
    #   cd backend && uv run python -c \
    #     "from app.core.security import hash_password; print(hash_password('parolanız'))"
    #
    # Hash tanımlıysa düz metin YOK SAYILIR.
    ADMIN_PASSWORD: str = "CHANGE_ME"
    ADMIN_PASSWORD_HASH: str = ""

    # Veritabanı (PostgreSQL + pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/unibox"

    # Connection pool — eskiden db/session.py içinde sabit kodluydu.
    # pool_recycle/pool_timeout hiç yoktu: bağlantı havuzdaki bir bağlantıyı
    # sonsuza dek canlı sayıyordu; PgBouncer/güvenlik duvarı gibi bir ara
    # katman onu sessizce düşürürse ilk kullanan istek `pool_pre_ping` devreye
    # girene kadar hata alıyordu. Değerler geliştirme ölçeğine göredir —
    # üretimde eşzamanlı admin+worker sayısına göre ayarlanmalı.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800  # saniye — bu süreden eski bağlantılar geri dönüştürülür
    DB_POOL_TIMEOUT: int = 30    # saniye — havuzdan bağlantı bekleme üst sınırı

    # KVKK: Fernet şifreleme anahtarı
    FERNET_KEY: str = "CHANGE_ME_FERNET_KEY"

    # LLM
    UNIBOX_LLM_BACKEND: str = "ollama"  # "ollama" | "llama_cpp"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    # Ollama'nın kendi varsayılanı (2048) RAG context'ini sessizce kırpıyordu:
    # 7 chunk'lık (~500 kelime/chunk) bağlam + sistem promptu rahatlıkla
    # 2048 token'ı aşıyor, Ollama fazlasını mesajın BAŞINDAN atıyor — hem
    # uydurma-karşıtı kurallar hem ilgili MADDE metni kayboluyordu. Ölçüldü:
    # aynı soruda num_ctx=2048 (varsayılan) tamamen uydurma yanıt verdi,
    # num_ctx=8192 ile MADDE 31'i birebir doğru özetledi. LLAMA_CPP_N_CTX ile
    # aynı değer.
    OLLAMA_NUM_CTX: int = 8192
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

    # ---- Hibrit arama parametreleri -------------------------------------
    # Bu değerler rag_engine.py'de modül sabiti olarak duruyordu ve ortamdan
    # ayarlanamıyordu. Kalibrasyon notları buraya taşındı.

    # Her iki aramadan füzyondan ÖNCE çekilen aday sayısı.
    #
    # 20'den 50'ye çıkarıldı ve bu, madde-farkındalıklı bölmeyle AYNI ANDA
    # gitmek ZORUNDA: fixture korpusunda yönetmelik chunk sayısı 27 -> 84'e
    # çıkıyor (toplam 52 -> 109). Tek bir yönetmelik (54 chunk) 20'lik havuzu
    # tek başına doldurabilir ve kısa rehber dokümanlarını tamamen dışarı
    # iter. Aynı hata daha önce chunk boyutu 150 kelimeye düşürülünce
    # yaşanmıştı (recall@3 %70 -> %50, bkz. RAG_CHUNK_SIZE notu).
    RAG_CANDIDATE_POOL: int = 50

    # Reciprocal Rank Fusion sabiti. Standart 60; büyüdükçe sıralama
    # farkları yumuşar, küçüldükçe ilk sıralar baskınlaşır.
    RAG_RRF_K: int = 60

    # Sorgunun intent'iyle etiketli chunk'lara eklenen bonus.
    #
    # 0.015'ten 0.003'e DÜŞÜRÜLDÜ. Gerekçe: RRF'de bir listede 1. sıra olmanın
    # katkısı 1/(60+1) = 0.0164. Yani 0.015'lik bonus, tam bir birincilik
    # kadar ağırdı — "eşit durumda etiketliyi öne al" değil, "etiketliyi
    # zirveye taşı" demekti. Gerçek bir beraberlik kırıcının mertebesi
    # 10. sıradan 5. sıraya çıkışın değeri kadardır: 1/65 - 1/70 = 0.0011.
    RAG_INTENT_BONUS: float = 0.003

    # ts_rank uzunluk normalizasyonu (PostgreSQL bit maskesi).
    # 0 = normalizasyon yok, uzun chunk'ları kayırır.
    # 1 = rank / (1 + log(uzunluk))  <-- seçilen
    # İki farklı doküman tipiyle ölçülerek seçildi; norm=2 kısa dokümanlarda
    # cazip görünüyor ama uzun mevzuat metnini eziyor.
    RAG_FTS_NORMALIZATION: int = 1

    # Sonuçta tek bir dokümandan en fazla kaç chunk yer alabilir.
    #
    # 2'den 3'e çıkarıldı. Sınırın varlık sebebi "bir PDF 20 chunk, rehberler
    # 1'er chunk" dengesizliğiydi. Madde bazlı bölmeden sonra yönetmelik
    # chunk'ları kendi kendine yeten maddeler hâline geliyor ve doğru cevap
    # sıklıkla AYNI dokümandaki 2-3 komşu madde oluyor.
    #
    # Ayrıca: sınır artık sonucu k'nın altına düşürmüyor. Yetersiz kalırsa
    # ikinci bir doldurma turu sınırı gevşetiyor (bkz. rag_engine.search).
    RAG_MAX_CHUNKS_PER_DOC: int = 3

    # Reranker (Faz 7, kill-criterion'lı — bkz. YOL_HARİTASI.md).
    #
    # Varsayılan KAPALI: ölçüm eşiği (madde@1 paired düzelen>bozulan, ≥5 soru
    # fark) geçilene kadar production davranışını etkilemesin. Ayrı HF TEI
    # container'ı — Ollama cross-encoder servis etmiyor, süreç içi
    # sentence-transformers reddedildi (torch ~2.5GB, senkron, air-gapped
    # on-prem'de HF Hub erişilemez).
    RERANKER_ENABLED: bool = False
    RERANKER_URL: str = "http://localhost:8090"
    # Tek bütçe hem sohbet (≤800ms p95) hem gelen e-posta (≤5sn) için yeterli:
    # ≤800ms zaten ≤5sn'yi sağlıyor, akışa özel ayrı bütçe gerekmiyor.
    RERANKER_TIMEOUT_MS: int = 800
    # RAG_CANDIDATE_POOL'un (50) tamamını CPU'da rerank etmek bütçeyi
    # zorlayabilir; RRF sırasına göre yalnızca ilk N aday gönderilir.
    RERANKER_TOP_N: int = 20

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
        for ad in ("SECRET_KEY", "FERNET_KEY"):
            if getattr(self, ad) in _GUVENSIZ_VARSAYILANLAR:
                sorunlar.append(f"{ad} hâlâ şablon değerinde")

        # Parola: üretimde bcrypt özeti zorunlu. Düz metin parola ortam
        # değişkeninde durursa süreç listesinden, çekirdek dökümünden ve
        # yedeklerden okunabilir.
        if not self.ADMIN_PASSWORD_HASH:
            sorunlar.append(
                "ADMIN_PASSWORD_HASH tanımlı değil — üretimde düz metin parola "
                "kullanılamaz. Üretmek için: uv run python -c "
                "\"from app.core.security import hash_password; "
                "print(hash_password('parolanız'))\""
            )
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
