# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UniBox is a KVKK-compliant university AI assistant that runs fully locally. It manages two email flows:
1. **Outgoing**: Students chat with a bot → intent detected → info collected → draft created → admin approves → SMTP send
2. **Incoming**: IMAP polls for student emails → AI analyzes + generates reply → admin reviews → SMTP reply

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL + pgvector, Pydantic Settings
- **LLM**: Ollama (`llama3.1:8b`) or llama-cpp — switchable via `UNIBOX_LLM_BACKEND`
- **Embeddings/RAG**: LlamaIndex + `nomic-embed-text` via Ollama, stored in pgvector
- **Frontend**: Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v3, Lucide icons
- **Dev infra**: Docker Compose (MailHog on :8025, Ollama on :11434)

## Commands

### Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000   # dev server; API docs at /docs
alembic upgrade head                         # run migrations
alembic revision --autogenerate -m "name"    # create migration
python ../scripts/test_smtp.py               # SMTP connectivity test
```

### Frontend
```bash
cd frontend
npm run dev      # dev server on :3000 (uses --webpack flag)
npm run build
npm run lint
```

### Infrastructure
```bash
docker-compose up -d
docker exec unibox_ollama ollama pull llama3.1:8b
docker exec unibox_ollama ollama pull nomic-embed-text
```

## Architecture

```
unibox/
├── backend/app/
│   ├── api/v1/
│   │   ├── router.py          # registers all sub-routers under /api/v1
│   │   ├── auth.py            # POST /auth/login, /auth/refresh
│   │   ├── chat.py            # WS + REST for student chat sessions
│   │   ├── email_drafts.py    # outgoing draft CRUD + approve/reject/retry
│   │   ├── incoming_emails.py # incoming email CRUD + approve/skip/reanalyze
│   │   ├── knowledge.py       # document upload + KB management
│   │   ├── dashboard.py       # stats aggregation
│   │   ├── monitor.py         # WS /monitor/ws (admin broadcast, read-only)
│   │   └── logs.py            # anonymized send history
│   ├── services/
│   │   ├── intent_detector.py    # LLM-based intent classification
│   │   ├── email_workflow.py     # outgoing draft state machine logic
│   │   ├── email_sender.py       # SMTP send (console | smtp backend)
│   │   ├── email_analyzer.py     # incoming email AI analysis
│   │   ├── imap_receiver.py      # IMAP polling loop
│   │   ├── incoming_reply_sender.py
│   │   ├── rag_engine.py         # pgvector similarity search
│   │   ├── llm_provider.py       # Ollama/llama-cpp abstraction
│   │   └── anonymizer.py         # PII masking (KVKK)
│   ├── tasks/
│   │   ├── queue.py     # asyncio.Queue instances
│   │   ├── workers.py   # background workers (email send, indexing, IMAP)
│   │   └── retention.py # daily cron: delete expired data
│   ├── db/models/       # SQLAlchemy ORM models
│   ├── core/
│   │   ├── security.py   # JWT + Fernet helpers
│   │   ├── ws_manager.py # WebSocket connection manager
│   │   └── events.py     # FastAPI lifespan (startup/shutdown)
│   └── config.py         # Pydantic Settings — single source of truth
├── frontend/src/
│   ├── app/(dashboard)/  # 6 protected pages: /, /monitoring, /emails, /incoming, /knowledge-base, /logs
│   │   └── layout.tsx    # JWT check, redirects to /login, wraps with WsProvider
│   ├── contexts/WsContext.tsx  # global WS state + pending counts for sidebar badges
│   ├── hooks/            # useWebSocket, useEmailDrafts, useDashboardStats
│   └── lib/api.ts        # typed fetch client (proxied through Next.js /api/backend)
└── docker-compose.yml
```

## State Machines

Both flows use strictly enforced state machines. Invalid transitions raise an error. Definitions (including `VALID_TRANSITIONS` dicts) live in the model files.

**EmailDraft** (outgoing, 9 states):
```
IDLE → COLLECTING_INFO → DRAFT_CREATED → PENDING_APPROVAL → APPROVED → SENT
                    ↓             ↓              ↓              ↓
                CANCELLED    CANCELLED    REJECTED/CANCELLED   FAILED → retry → APPROVED
```

**IncomingEmail** (8 states):
```
RECEIVED → ANALYZING → REPLY_GENERATED → PENDING_REVIEW → APPROVED → REPLIED
               ↓                                ↓              ↓
        ANALYSIS_FAILED → retry RECEIVED    SKIPPED        FAILED → retry → APPROVED
```

## WebSocket Architecture

Two separate channels (privacy isolation):
- **Student WS** (`/api/v1/chat/{session_token}`): bidirectional student ↔ bot
- **Admin monitor WS** (`/api/v1/monitor/ws?token=<jwt>`): read-only broadcast to all admin tabs

`WsContext` connects to the admin channel and fans out events to page-level subscribers via `subscribe()`. Sidebar badge counts update on specific event types (e.g., `email_pending_approval`, `incoming_email_received`).

## Frontend API Proxy (BFF Pattern)

Browser API calls go to `NEXT_PUBLIC_API_URL=http://localhost:3000/api/backend`, which Next.js proxies to `BACKEND_URL=http://localhost:8000` server-side. This hides the backend from the browser and avoids CORS. Do not point `NEXT_PUBLIC_API_URL` directly at FastAPI.

## KVKK Compliance

- `collected_fields_enc`: student info JSON, Fernet encrypted, **nulled after SENT/REJECTED**
- `IncomingEmail.sender_email_enc`: Fernet encrypted; SHA-256 hash stored for dedup only
- `anonymizer.py` masks TCKN, phone, and name patterns before LLM calls
- Retention: conversations 90 days, email logs 180 days — enforced by `tasks/retention.py`
- Student right-to-erasure: `DELETE /api/v1/chat/session/{token}`

## Environment Variables

Backend reads from `backend/.env`. Key variables:

| Variable | Default | Notes |
|---|---|---|
| `FERNET_KEY` | (required) | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/unibox` | Must use asyncpg |
| `UNIBOX_LLM_BACKEND` | `ollama` | `ollama` or `llama_cpp` |
| `SMTP_BACKEND` | `console` | `console` prints to stdout; `smtp` sends real email |
| `IMAP_BACKEND` | `disabled` | `disabled` or `imap` |
| `APP_ENV` | `development` | `production` disables `/docs` and `/redoc` |

Frontend reads from `frontend/.env.local` (copy from `.env.local.example`).
