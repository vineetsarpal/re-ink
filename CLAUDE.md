# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**re-ink** is a full-stack web application for automated reinsurance contract and party management. Users upload PDF/DOCX reinsurance documents, which are processed by LandingAI's Agentic Document Extraction API. Extracted data is reviewed and approved to create structured Contract and Party records. A LangChain/LangGraph agent layer provides guided intake and automated contract review.

**Stack**: FastAPI + SQLAlchemy + PostgreSQL + LandingAI (backend) · React 18 + TypeScript + Vite + React Query (frontend)

## Development Commands

### Quickstart (Makefile)

```bash
make setup          # Install backend + frontend dependencies (also runs sync-version)
make dev            # Launch both dev servers concurrently (Ctrl+C stops both)
make backend-dev    # Backend only (uvicorn --reload, port 8000)
make frontend-dev   # Frontend only (vite --host, port 3000)
make sync-version   # Copy root VERSION → backend/VERSION (needed for local dev)
make bump-version V=1.2.3  # Bump version across VERSION, backend/VERSION, package.json
```

### Backend (from `backend/`)

```bash
source venv/bin/activate
alembic upgrade head                              # Apply migrations
alembic revision --autogenerate -m "description" # New migration
pytest                                            # Run tests
uvicorn app.main:app --reload                     # Dev server
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
- **`services/`**: Business logic — `landingai_service.py` (ADE API calls), `document_service.py` (upload/validation), `agent_service.py` (LangChain/LangGraph agents)
- **`models/`**: SQLAlchemy ORM models; `ExtractionJob` persists extraction job state (status, parsed results) in PostgreSQL; `contract_parties` association table links Contracts ↔ Parties with a `role` field
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

1. `POST /api/documents/upload` — saves file, starts LandingAI extraction job
2. `GET /api/documents/status/{job_id}` — polled by `ExtractionStatus` until `completed`/`failed`
3. `GET /api/documents/results/{job_id}` — returns parsed extraction data
4. `POST /api/review/approve` — creates Contract + Party records from reviewed data
5. `POST /api/agents/intake` / `POST /api/agents/review` — optional LangChain agent passes (requires `LLM_PROVIDER` config)

## Environment Variables

### Backend (`backend/.env`)

```env
DATABASE_URL=postgresql://user:password@localhost:5432/reink_db
LANDINGAI_API_KEY=your_key
LANDINGAI_PARSE_URL=https://api.va.landing.ai/v1/ade/parse
LANDINGAI_EXTRACT_URL=https://api.va.landing.ai/v1/ade/extract
LANDINGAI_PARSE_MODEL=dpt-2-latest
LANDINGAI_EXTRACT_MODEL=extract-latest
UPLOAD_DIR=./uploads
MAX_UPLOAD_SIZE=52428800
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
LLM_PROVIDER=openai               # "openai" or "ollama"
OPENAI_API_KEY=your_openai_key    # Only needed when LLM_PROVIDER=openai
AGENT_MODEL=gpt-4o-mini           # Model name for OpenAI provider
OLLAMA_BASE_URL=http://localhost:11434  # Only needed when LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1             # Model name for Ollama provider
AGENT_OFFLINE_MODE=false          # Set true to skip LLM calls entirely
```

### Frontend (`frontend/.env`)

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## Sample Documents

Two sample PDFs are bundled with the frontend at `frontend/public/samples/` and are selectable directly in the Upload page UI — no setup needed.

`sample_documents/` contains additional trimmed SEC EDGAR filings for manual upload testing. Files use `.pdf.example` / `.docx.example` suffixes to bypass `.gitignore`; remove the `.example` suffix before uploading through the app. When committing new samples, add the suffix back.

## Version Management

The root `VERSION` file is the single source of truth for the app version.

- **Frontend**: `vite.config.ts` reads `../VERSION` at build time and injects it as `__APP_VERSION__` (displayed in the sidebar)
- **Backend**: `config.py` reads `backend/VERSION`; this file is generated by the CI deploy workflow (`cp VERSION backend/VERSION`) and excluded from git
- **Local dev**: run `make sync-version` once after cloning (or `make setup` which includes it)
- **Bumping**: `make bump-version V=x.y.z` updates `VERSION`, `backend/VERSION`, and `frontend/package.json` atomically

## Testing

```bash
cd backend && pytest                    # All backend tests
cd backend && pytest tests/test_mock_agents.py  # Single file
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
| GET | `/api/system/config` | Agent config flags for frontend |

API docs available at `http://localhost:8000/docs` when the backend is running.
