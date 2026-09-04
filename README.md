# UniBox — Üniversite AI Asistanı

KVKK uyumlu, tamamen yerel çalışan üniversite öğrenci asistanı. Hiçbir veri
dış servise gitmez: LLM, embedding ve veritabanı kurum içinde çalışır.

İki e-posta akışı yönetir:

- **Giden**: Öğrenci bot ile konuşur → talep tipi tespit edilir → eksik bilgi
  toplanır → taslak üretilir → admin onaylar → SMTP ile gönderilir
- **Gelen**: IMAP öğrenci e-postalarını çeker → AI analiz eder ve yanıt üretir
  → admin inceler → SMTP ile yanıtlanır

## Hızlı Başlangıç

### 1. Ortam Değişkenleri

Üç ayrı dosya gerekiyor:

```bash
# 1) Uygulama ayarları
cp .env.example backend/.env
#    İçini doldurun: FERNET_KEY, SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL

# 2) docker-compose'un okuduğu veritabanı parolası
echo "POSTGRES_PASSWORD=<güçlü-parola>" > .env
#    backend/.env içindeki DATABASE_URL ile AYNI parola olmalı

# 3) Frontend
cp frontend/.env.local.example frontend/.env.local
```

> **FERNET_KEY uyarısı:** Bu anahtar veritabanındaki tüm şifreli veriyi
> (öğrenci bilgileri, gönderen adresleri) açar. Kaybederseniz veri kalıcı
> olarak okunamaz hale gelir. Yedekleyin, üretimde asla yeniden üretmeyin.

### 2. Bağımlılıkları Yükle

```bash
cd backend && uv sync          # veya: pip install -e .
cd ../frontend && npm install
```

### 3. Altyapıyı Başlat

```bash
docker compose up -d
```

| Servis | Adres | Not |
|---|---|---|
| PostgreSQL + pgvector | `127.0.0.1:5432` | |
| Ollama (container) | `127.0.0.1:11435` | host'ta Ollama varsa gerekmez |
| MailHog | http://localhost:8025 | giden e-postaları yakalar |

### 4. LLM Modellerini İndir

**İkisi de zorunlu.** `bge-m3` olmadan RAG hiçbir sonuç döndürmez.

```bash
# Host'ta kurulu Ollama kullanıyorsanız (varsayılan, .env → 11434):
ollama pull llama3.1:8b
ollama pull bge-m3

# docker-compose container'ını kullanacaksanız (.env → 11435):
docker exec unibox_ollama ollama pull llama3.1:8b
docker exec unibox_ollama ollama pull bge-m3
```

### 5. Veritabanını Hazırla

```bash
cd backend
uv run alembic upgrade head
uv run python ../scripts/seed_db.py    # örnek veri (opsiyonel)
```

### 6. Backend'i Başlat

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
# API dokümanı: http://localhost:8000/docs   (APP_ENV=production'da kapalı)
```

### 7. Frontend'i Başlat

```bash
cd frontend
npm run dev
# Dashboard: http://localhost:3000
```

---

## Mimari

```
unibox/
├── backend/                # FastAPI + SQLAlchemy 2.0 (async) + pgvector
│   ├── alembic/versions/   # 0001 → 0006 migration zinciri
│   └── app/
│       ├── api/v1/         # 9 router: auth, chat, emails, incoming,
│       │                   #   knowledge, dashboard, monitor, logs, settings
│       ├── services/       # LLM sağlayıcı, RAG motoru, e-posta akışları,
│       │                   #   IMAP alıcı, KVKK anonymizer
│       ├── db/models/      # SQLAlchemy ORM modelleri
│       ├── core/           # JWT, WebSocket yöneticisi, lifespan
│       └── tasks/          # asyncio kuyruk worker'ları + retention cron
├── frontend/src/
│   ├── app/(dashboard)/    # 7 korumalı sayfa: Overview, Monitoring, Emails,
│   │                       #   Incoming, Knowledge Base, Logs, Settings
│   ├── contexts/           # WsContext — admin WS + kenar çubuğu rozetleri
│   ├── hooks/              # useWebSocket, useEmailDrafts, useSystemMode, ...
│   └── lib/api.ts          # tipli fetch istemcisi (BFF proxy üzerinden)
├── scripts/                # kurulum, içe aktarma ve ölçüm scriptleri
└── docker-compose.yml      # PostgreSQL + Ollama + MailHog
```

### RAG Mimarisi

Bilgi tabanı araması **hibrit**: iki bağımsız arama Reciprocal Rank Fusion
ile birleştirilir.

```
soru → ┬→ anlamsal:   bge-m3 embedding → pgvector cosine (HNSW)  ─┐
       └→ sözcüksel:  PostgreSQL 'turkish' FTS → ts_rank (GIN)   ─┴→ RRF
                                                                     ↓
                                        intent bonusu → doküman çeşitliliği
                                                                     ↓
                                                            top-K chunk → LLM
```

Saf vektör araması Türkçe'de zayıftı (ölçüm: recall@1 %19); sözcüksel arama
"transkript" gibi birebir geçen anahtar kelimeleri yakalar.

Ayarlanabilir parametreler ve **ölçümle belirlenmiş kalibrasyon tabloları**
`backend/app/config.py` içinde yorum olarak belgelenmiştir — değiştirmeden
önce okuyun.

> **Embedding modelini veya boyutunu değiştirirseniz:** yeni bir Alembic
> migration ile `document_chunks.embedding` kolonunu güncelleyin, ardından
> `uv run python ../scripts/reindex_documents.py` çalıştırın.

## Frontend API Proxy (BFF)

Tarayıcı istekleri `NEXT_PUBLIC_API_URL=http://localhost:3000/api/backend`
adresine gider; Next.js bunu sunucu tarafında `BACKEND_URL`'e proxy'ler. Bu
backend'i tarayıcıdan gizler ve CORS'u ortadan kaldırır.
`NEXT_PUBLIC_API_URL`'i doğrudan FastAPI'ye yönlendirmeyin.

## KVKK Uyumluluk Notları

- Öğrenci PII'si (TCKN, ad, telefon) LLM'e gönderilmeden önce
  `anonymizer.py` ile maskelenir
- Giden taslak gövdesi `sanitize_draft_body()` ile deterministik olarak
  temizlenir — prompt'un "PII isteme" kuralına güvenilmez
- `collected_fields_enc`: Fernet şifreli, SENT/REJECTED sonrası NULL'lanır
- `IncomingEmail.sender_email_enc`: Fernet şifreli; tekilleştirme için
  yalnızca SHA-256 özeti saklanır
- Veri saklama: konuşmalar 90 gün, e-posta logları 180 gün — `tasks/retention.py`
- Öğrenci silme hakkı: `DELETE /api/v1/chat/session/{token}`
- İki ayrı WebSocket kanalı: öğrenci ↔ bot (çift yönlü) ve admin izleme
  (yalnızca okuma) — gizlilik izolasyonu

## E-posta Onay Akışı

```
Öğrenci → Bot (intent tespiti) → Bilgi toplama → Taslak oluşturma
→ Admin Dashboard (PENDING_APPROVAL) → Admin inceler/düzenler
→ Onayla → SMTP gönderim → E-posta logu (PII maskelenmiş)
        → Reddet → Öğrenciye bildirim
```

## Scriptler

Hepsi `cd backend` sonrası `uv run python ../scripts/<ad>.py` ile çalışır.

| Script | İş |
|---|---|
| `seed_db.py` | Geliştirme için örnek kayıtlar |
| `test_smtp.py` | SMTP bağlantı testi |
| `import_kb_from_jsonl.py` | JSONL'den bilgi tabanı içe aktarma |
| `reindex_documents.py` | Mevcut ayarlarla tüm dokümanları yeniden indeksle |
| `eval_intent.py` | Intent sınıflandırma doğruluğu |
| `eval_retrieval.py` | Intent-etiketli geri getirim (vektör vs hibrit) |
| `eval_retrieval_docs.py` | Etiketsiz doküman-düzeyi recall |
| `eval_regulation.py` | Gerçek yönetmelikte madde-düzeyi recall |
| `eval_draft.py` | Taslak kalitesi, çoklu model karşılaştırması |
| `eval_reply.py` | Kapsam içi cevap vs kapsam dışı geri çekilme |

> **Ölçüm scriptlerinin bilinen sınırı:** test verisi henüz repo dışında,
> sabit bir yolda duruyor ve ölçümler o anki veritabanına karşı yapılıyor —
> yani başka bir makinede tekrarlanamaz ve sayılar baseline sayılamaz.
> Fixture tabanlı pytest'e taşıma işi planlanmış durumda.
