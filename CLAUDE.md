# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**re-ink** is a full-stack web application for automated reinsurance contract and party management. Users upload PDF/DOCX reinsurance documents, which are processed via a BYOK (bring-your-own-key) extraction system supporting four backends: LandingAI, OpenAI, Anthropic (Claude), or Free (local Ollama). Extracted data is reviewed and approved to create structured Contract and Party records. A LangChain/LangGraph agent layer provides guided intake and automated contract review.

**Stack**: FastAPI + SQLAlchemy + PostgreSQL (backend) · React 18 + TypeScript + Vite (frontend)

## Development Commands

### Quickstart (Makefile)

```bash
make setup          # Install backend + frontend dependencies
make dev            # Launch both dev servers concurrently (Ctrl+C stops both)
make backend-dev    # Backend only (uvicorn --reload, port 8000)
make frontend-dev   # Frontend only (vite --host, port 3000)
```

### Backend (from `backend/`)

```bash
uv sync --group dev                                          # Install / sync dependencies
uv run alembic upgrade head                                  # Apply migrations
uv run alembic revision --autogenerate -m "description"      # New migration
uv run pytest                                                # Run tests
uv run uvicorn app.main:app --reload                         # Dev server
```

### Frontend (from `frontend/`)

```bash
npm run dev     # Dev server
npm run build   # Production build
npm run lint    # ESLint check (required before PR)
```

## Architecture

### Backend

Layered FastAPI service under `backend/app/`:

- **`api/endpoints/`**: Thin route handlers per resource — `documents.py`, `contracts.py`, `parties.py`, `review.py`, `agents.py`, `system.py`
- **`services/`**: Business logic — `landingai_service.py` (LandingAI ADE), `free_extraction_service.py` (local Ollama / OpenAI), `anthropic_extraction_service.py` (Claude PDF vision), `document_service.py` (upload/validation), `agent_service.py` (LangChain/LangGraph agents), `extraction_store.py` (in-memory job store for extraction status)
- **`models/`**: SQLAlchemy ORM models; `contract_parties` association table links Contracts ↔ Parties with a `role` field
- **`schemas/`**: Pydantic schemas for request/response validation
- **`core/config.py`**: All settings via `pydantic-settings`

### Frontend

Vite + React under `frontend/src/`:

- **`pages/`**: `Dashboard.tsx`, `UploadPage.tsx` (full upload→extract→review flow), `ContractsPage.tsx`, `PartiesPage.tsx`
- **`components/`**: `FileUpload.tsx`, `ExtractionStatus.tsx` (polls job status), `ReviewForm.tsx`, `Layout.tsx`
- **`services/api.ts`**: Axios client — single source of truth for all backend calls
- **`types/`**: TypeScript types mirroring backend Pydantic schemas
- Use `@/*` path alias for imports instead of relative paths

### Key Workflow

1. `POST /api/documents/upload` — saves file, starts extraction (accepts `extraction_backend` + `api_key` form fields for BYOK)
2. `GET /api/documents/status/{job_id}` — polled by `ExtractionStatus` until `completed`/`failed`
3. `GET /api/documents/results/{job_id}` — returns parsed extraction data
4. `POST /api/review/approve` — creates Contract + Party records from reviewed data
5. `POST /api/agents/intake` / `POST /api/agents/review` — optional LangChain agent passes (requires `OPENAI_API_KEY`)

## Environment Variables

### Backend (`backend/.env`)

```env
DATABASE_URL=postgresql://user:password@localhost:5432/reink_db
EXTRACTION_BACKEND=free            # "landingai", "openai", "anthropic", or "free" (server default; users override via UI)
LANDINGAI_API_KEY=                 # Only needed for landingai backend
OPENAI_API_KEY=                    # Needed for openai backend and agent endpoints
ANTHROPIC_API_KEY=                 # Needed for anthropic backend
FREE_PARSE_BACKEND=pypdf           # "pypdf" or "glm-ocr" (for free backend)
FREE_OLLAMA_BASE_URL=http://localhost:11434
UPLOAD_DIR=./uploads
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
AGENT_MODEL=gpt-4o-mini
AGENT_OFFLINE_MODE=false
```

### Frontend (`frontend/.env`)

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## Sample Documents

`sample_documents/` contains trimmed SEC EDGAR filings for testing. Files use `.pdf.example` / `.docx.example` suffixes to bypass `.gitignore`; remove the `.example` suffix before uploading through the app. When committing new samples, add the suffix back.

## Testing

```bash
cd backend && uv run pytest                               # All backend tests
cd backend && uv run pytest tests/test_mock_agents.py    # Single file
```

No frontend test runner is bundled. Keep `npm run lint` clean; document manual verification in PRs.

## API Surface

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` | Upload doc, start extraction |
| GET | `/api/documents/status/{job_id}` | Poll extraction status |
| GET | `/api/documents/results/{job_id}` | Fetch extraction results |
| GET/POST | `/api/contracts/` | List / create contracts |
| GET/PUT/DELETE | `/api/contracts/{id}` | Contract detail ops |
| POST/DELETE | `/api/contracts/{id}/parties/{party_id}` | Link/unlink party |
| GET/POST | `/api/parties/` | List / create parties |
| GET/PUT/DELETE | `/api/parties/{id}` | Party detail ops |
| GET | `/api/parties/search/by-name` | Name search |
| POST | `/api/review/approve` | Approve extraction → create records |
| POST | `/api/review/reject/{job_id}` | Reject extraction |
| POST | `/api/agents/intake` | Guided intake agent |
| POST | `/api/agents/review` | Automated contract review agent |
| GET | `/api/system/config` | Config flags + available backends for frontend |

API docs available at `http://localhost:8000/docs` when the backend is running.
