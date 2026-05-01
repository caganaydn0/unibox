# UniBox — Üniversite AI Asistanı

KVKK uyumlu, tamamen yerel çalışan üniversite öğrenci asistanı.

## Hızlı Başlangıç

### 1. Ortam Değişkenleri

```bash
# Backend
cp .env.example backend/.env
# İçini doldurun: FERNET_KEY, ADMIN_PASSWORD, SMTP ayarları vb.

# Frontend
cp frontend/.env.local.example frontend/.env.local
```

### 2. Bağımlılıkları Yükle

```bash
# Backend (uv veya pip)
cd backend
uv sync        # veya: pip install -e .

# Frontend
cd ../frontend
npm install
```

### 3. Dev Servislerini Başlat (MailHog + Ollama)

```bash
docker-compose up -d
# MailHog UI: http://localhost:8025
# Ollama: http://localhost:11434
```

### 4. LLM Modelini İndir (Ollama kullanıyorsanız)

```bash
docker exec unibox_ollama ollama pull llama3.1:8b
```

### 5. Veritabanını Hazırla

```bash
cd backend
alembic upgrade head
python ../scripts/seed_db.py   # Örnek veri (opsiyonel)
```

### 6. Backend'i Başlat

```bash
cd backend
uvicorn app.main:app --reload --port 8000
# API Docs: http://localhost:8000/docs
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
├── backend/           # FastAPI + LlamaIndex + ChromaDB
│   └── app/
│       ├── api/v1/    # REST + WebSocket endpoint'leri
│       ├── services/  # LLM, RAG, email workflow, KVKK anonymizer
│       ├── db/        # SQLAlchemy modelleri + Alembic
│       ├── core/      # JWT, WebSocket yöneticisi, lifespan
│       └── tasks/     # Async queue workers (email, index, retention)
├── frontend/          # Next.js Admin Dashboard
│   └── src/
│       ├── app/       # 5 sayfa: Overview, Monitoring, Emails, KB, Logs
│       ├── hooks/     # useWebSocket, useEmailDrafts, useDashboardStats
│       └── lib/       # Typed API client
├── data/              # Yerel veri (git'te yok — KVKK)
├── scripts/           # seed_db.py, test_smtp.py
└── docker-compose.yml # MailHog + Ollama
```

## KVKK Uyumluluk Notları

- Tüm öğrenci PII (TCKN, ad, tel) `anonymizer.py` ile **yazım anında** maskelenir
- `collected_fields_enc`: Fernet şifrelemeli, SENT/REJECTED sonrası NULL'lanır
- Öğrenci silme hakkı: `DELETE /api/v1/chat/session/{token}`
- Veri saklama: Konuşmalar 90 gün, email log'ları 180 gün (günlük cron)
- İki ayrı WS kanalı: öğrenci ↔ bot (bidirectional) ve admin izleme (read-only)

## Email Onay Akışı

```
Öğrenci → Bot (intent tespiti) → Bilgi toplama → Taslak oluşturma
→ Admin Dashboard (PENDING_APPROVAL) → Admin inceler/düzenler
→ Onayla → SMTP gönderim → Email Log (PII maskelendi)
        → Reddet → Öğrenciye bildirim
```

## Test

```bash
# SMTP bağlantı testi
cd backend && python ../scripts/test_smtp.py

# Admin giriş (API)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"CHANGE_ME"}'

# Bekleyen emailler
curl http://localhost:8000/api/v1/emails/drafts?status=PENDING_APPROVAL \
  -H "Authorization: Bearer <token>"
```
