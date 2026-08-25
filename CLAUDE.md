# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UniBox is a KVKK-compliant university AI assistant that runs fully locally. It manages two email flows:
1. **Outgoing**: Students chat with a bot → intent detected → info collected → draft created → admin approves → SMTP send
2. **Incoming**: IMAP polls for student emails → AI analyzes + generates reply → admin reviews → SMTP reply

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL + pgvector, Pydantic Settings
- **LLM**: Ollama (`llama3.1:8b`) or llama-cpp — switchable via `UNIBOX_LLM_BACKEND`
- **Embeddings/RAG**: `bge-m3` (1024-dim, multilingual) via Ollama → pgvector.
  Chunking uses `langchain-text-splitters`; PDF text via `pypdf`.
  There is **no LlamaIndex and no ChromaDB** in this project despite what older
  docs claimed — do not add them.
- **Frontend**: Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v3, Lucide icons
- **Package manager**: `uv` for the backend (`backend/uv.lock` is committed)
- **Dev infra**: Docker Compose — PostgreSQL :5432, Ollama :11435, MailHog :8025.
  All bound to `127.0.0.1` only. Note the app defaults to a **host** Ollama on
  :11434 (that is where `bge-m3` is pulled); the container is the fallback.

## Commands

### Backend
```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000  # dev server; API docs at /docs
uv run alembic upgrade head                        # run migrations
uv run alembic revision --autogenerate -m "name"   # create migration
uv run python ../scripts/test_smtp.py              # SMTP connectivity test
uv run python ../scripts/reindex_documents.py      # rebuild all chunks+embeddings
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
docker compose up -d
# Both models are required — RAG returns nothing without bge-m3.
# Pull into whichever Ollama OLLAMA_BASE_URL points at:
ollama pull llama3.1:8b && ollama pull bge-m3                    # host (default)
docker exec unibox_ollama ollama pull llama3.1:8b bge-m3         # container
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
│   │   ├── logs.py            # anonymized send history
│   │   └── settings.py        # global Pilot / Co-Pilot mode switch
│   ├── services/
│   │   ├── intent_detector.py    # LLM-based intent classification
│   │   ├── email_workflow.py     # outgoing draft state machine logic
│   │   ├── email_sender.py       # SMTP send (console | smtp backend)
│   │   ├── email_analyzer.py     # incoming email AI analysis
│   │   ├── imap_receiver.py      # IMAP polling loop
│   │   ├── incoming_reply_sender.py
│   │   ├── rag_engine.py         # hybrid retrieval: pgvector + Turkish FTS (RRF)
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
│   ├── app/(dashboard)/  # 7 protected pages: /, /monitoring, /emails, /incoming,
│   │   │                 #   /knowledge-base, /logs, /settings
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
- **Student WS** (`/api/v1/chat/ws/{session_token}`): bidirectional student ↔ bot
- **Admin monitor WS** (`/api/v1/monitor/ws?token=<jwt>`): read-only broadcast to all admin tabs

`WsContext` connects to the admin channel and fans out events to page-level subscribers via `subscribe()`. Sidebar badge counts update on specific event types (e.g., `email_pending_approval`, `incoming_email_received`).

## RAG Retrieval Architecture

`rag_engine.search()` runs **two independent retrievals** and fuses them with
Reciprocal Rank Fusion — pure vector search was weak in Turkish (measured:
recall@1 19%).

```
question → ┬→ semantic: bge-m3 embedding → pgvector cosine (HNSW index)  ─┐
           └→ lexical:  to_tsvector('turkish') → ts_rank (GIN index)     ─┴→ RRF
                                                                            ↓
                                        intent bonus → per-document diversity cap
                                                                            ↓
                                                                  top-K chunks → LLM
```

Two Alembic migrations back this: `0005` creates the Turkish FTS GIN index,
`0006` moves embeddings to 1024 dims for bge-m3.

**Tuning constants live in two places** and both carry measurement tables in
comments — read them before changing anything:
- `config.py`: `EMBEDDING_*`, `RAG_CHUNK_*`, `RAG_TOP_K`, `RAG_MAX_DISTANCE`
- `rag_engine.py` module constants: `CANDIDATE_POOL`, `RRF_K`, `INTENT_BONUS`,
  `FTS_NORMALIZATION`, `MAX_CHUNKS_PER_DOC`

Those comments record what was tried and rejected (e.g. 150-word chunks dropped
recall@3 from 70% to 50%). Do not silently overwrite them.

**After changing the embedding model, its dimensions, or chunk size:** write a
migration for `document_chunks.embedding` if the dimension changed, then run
`scripts/reindex_documents.py`. Skipping the reindex makes RAG return nothing.

## Frontend API Proxy (BFF Pattern)

Browser API calls go to `NEXT_PUBLIC_API_URL=http://localhost:3000/api/backend`, which Next.js proxies to `BACKEND_URL=http://localhost:8000` server-side. This hides the backend from the browser and avoids CORS. Do not point `NEXT_PUBLIC_API_URL` directly at FastAPI.

## KVKK Compliance

- `collected_fields_enc`: student info JSON, Fernet encrypted, **nulled after SENT/REJECTED**
- `IncomingEmail.sender_email_enc`: Fernet encrypted; SHA-256 hash stored for dedup only
- `anonymizer.py` masks TCKN, phone, and name patterns before LLM calls
- `anonymizer.sanitize_draft_body()` deterministically strips PII requests and
  unfilled `[placeholders]` from generated draft bodies. The prompt forbids them
  too, but small models violate that instruction regularly — **do not rely on the
  prompt alone for KVKK**
- Retention: conversations 90 days, email logs 180 days — enforced by `tasks/retention.py`
- Student right-to-erasure: `DELETE /api/v1/chat/session/{token}`

## Environment Variables

Three env files, all gitignored:

| File | Read by | Contents |
|---|---|---|
| `backend/.env` | FastAPI (`config.py`) | everything below |
| `.env` (repo root) | `docker compose` | only `POSTGRES_PASSWORD` |
| `frontend/.env.local` | Next.js | `BACKEND_URL`, `NEXT_PUBLIC_*` |

`.env.example` is the authoritative template for `backend/.env` — keep it in
sync when adding a setting to `config.py`.

| Variable | Default | Notes |
|---|---|---|
| `FERNET_KEY` | (required) | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Losing it makes all encrypted rows unreadable — never regenerate on a live DB |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Must use asyncpg. Password must match root `.env` |
| `UNIBOX_LLM_BACKEND` | `ollama` | `ollama` or `llama_cpp` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host Ollama by default; the compose container is on `:11435`. `bge-m3` must exist wherever this points |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `bge-m3` / `1024` | Changing either requires a migration + reindex |
| `RAG_MAX_DISTANCE` | `0.60` | Out-of-scope cutoff; calibration table in `config.py` |
| `SMTP_BACKEND` | `console` | `console` prints to stdout; `smtp` sends real email (MailHog on :1025 in dev) |
| `IMAP_BACKEND` | `disabled` | `disabled` or `imap` |
| `APP_ENV` | `development` | `production` disables `/docs` and `/redoc` |
