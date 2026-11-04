# re-ink Backend

FastAPI backend for the re-ink reinsurance contract management system.

## Features

- **Document Processing**: Upload and process PDF/DOCX contract documents
- **AI Extraction**: Durable n8n extraction with validated provider-independent results
- **Contract Management**: Full CRUD operations for reinsurance contracts
- **Party Management**: Manage parties (cedants, reinsurers, brokers)
- **Review Workflow**: Review and approve AI-extracted data before creation
- **Source Grounding**: Return available real source text/page/box evidence; absent evidence remains explicit
- **WorkOS Auth & Tenancy**: Validate AuthKit access tokens and scope resource queries to the caller's organization
- **Capabilities**: Guided intake and automated review are disabled (503)

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package & project manager)
- Python 3.13+ (uv can install this for you)
- PostgreSQL 12+
- WorkOS AuthKit client ID
- Private R2 storage and configured n8n/dispatcher service credentials; see [storage/access](../docs/integration/storage-access.md)

### Installation

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`). `uv sync` creates the `.venv` and installs the locked dependencies; `uv run` runs commands inside it, so there's no virtualenv to activate manually.

1. Install dependencies:
```bash
uv sync   # creates .venv and installs deps (dev group included by default)
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. Initialize the database:
```bash
# Create PostgreSQL database
createdb reink_db

# Apply migrations (builds schema on a fresh DB)
uv run alembic upgrade head

# For an existing DB previously created by create_all() — stamp it first (one-time):
# uv run alembic stamp 0001_baseline && uv run alembic upgrade head
```

### Running the Server

Development mode with auto-reload (entrypoint is configured under `[tool.fastapi]` in `pyproject.toml`):
```bash
uv run fastapi dev
```

Production mode (no reload, binds 0.0.0.0):
```bash
uv run fastapi run
```

Debugging with breakpoints:
```bash
# Start debug server
uv run python run_debug.py

# Then attach debugger from VS Code/Cursor (F5)
```

The API will be available at:
- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

## Project Structure

```
backend/
├── app/
│   ├── api/              # API endpoints
│   │   └── endpoints/    # Route handlers
│   ├── core/             # Core configuration
│   ├── db/               # Database setup
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # Business logic
│   └── main.py           # FastAPI application
├── alembic/              # Database migrations
├── scripts/              # Utility scripts
├── tests/                # Test files
├── pyproject.toml        # Project metadata & dependencies (uv)
└── uv.lock               # Pinned dependency lockfile
```

## API Endpoints

Browser resource endpoints require a WorkOS Bearer token; machine workflow endpoints use separate scoped service authentication (see the integration contract). `/api/system/config` exposes public booleans. The `/api/onboarding/provision-organization` endpoint authenticates a signed-in user before they have an organization so it can provision one.

### Documents
- `POST /api/documents/upload` - Persist an original and queue a durable workflow attempt
- `GET /api/documents/status/{job_id}` - Get extraction status
- `GET /api/documents/results/{job_id}` - Get extraction results with field source evidence
- `GET /api/documents/file/{job_id}` - Stream the original uploaded document for preview
- `POST /api/documents/{job_id}/retry` - Permission-gated retry for eligible failed/timed-out workflow jobs
- `DELETE /api/documents/{job_id}` - Delete a document

### Contracts
- `GET /api/contracts/` - List all contracts, with `status`, `contract_type`, `skip`, and `limit` filters
- `POST /api/contracts/` - Create a new contract
- `GET /api/contracts/{id}` - Get contract details
- `PUT /api/contracts/{id}` - Update a contract
- `DELETE /api/contracts/{id}` - Soft delete a contract
- `POST /api/contracts/{id}/parties/{party_id}` - Link a party to a contract with a role
- `PATCH /api/contracts/{id}/parties/{party_id}` - Update a linked party's role
- `DELETE /api/contracts/{id}/parties/{party_id}` - Remove a party association from a contract

### Parties
- `GET /api/parties/` - List all parties, with `is_active`, `skip`, and `limit` filters
- `POST /api/parties/` - Create a new party
- `POST /api/parties/match` - Fuzzy-match extracted party names against existing parties
- `GET /api/parties/{id}` - Get party details
- `PUT /api/parties/{id}` - Update a party
- `DELETE /api/parties/{id}` - Soft delete a party
- `GET /api/parties/search/by-name` - Search parties by name

### Review
- `POST /api/review/approve` - Approve and create extracted data
- `POST /api/review/reject/{job_id}` - Reject extraction

### Agents
- `POST /api/agents/intake` - Disabled (503), upload permission still required
- `POST /api/agents/review` - Disabled (503), contract-read permission still required

### System, Widgets, and Onboarding
- `GET /api/system/config` - Return runtime flags needed by the frontend
- `POST /api/widgets/user-profile/token` - Mint a WorkOS User Profile widget token
- `POST /api/onboarding/provision-organization` - Ensure a signed-in user has an organization

## Database Migrations

Alembic is the single source of schema truth — `Base.metadata.create_all()` is no longer called at app startup.

Create a new migration:
```bash
uv run alembic revision --autogenerate -m "description"
```

Apply migrations (fresh DB, or advance to latest):
```bash
uv run alembic upgrade head
```

For an existing database that was previously created by `create_all()` (including the production Neon DB), stamp it once so Alembic records the baseline without re-running DDL:
```bash
uv run alembic stamp 0001_baseline
uv run alembic upgrade head
```

Rollback:
```bash
uv run alembic downgrade -1
```

CI/CD runs `uv run alembic upgrade head` automatically before every deploy. The GitHub Actions secret `DATABASE_URL` must be set in the repository settings for this to work.

## Testing

Run tests:
```bash
uv run pytest
```

With coverage:
```bash
uv run pytest --cov=app tests/
```

## Configuration

Key environment variables:

- `DATABASE_URL` - PostgreSQL connection string
- `WORKOS_CLIENT_ID` - WorkOS client ID used to derive token issuer and JWKS URL
- `WORKOS_API_KEY` - Required for server-side WorkOS calls such as User Profile widget tokens and organization provisioning; not required for access-token validation
- `DEBUG` - Enable debug mode (default: False)
- `LOG_LEVEL` - Logging level (default: INFO)
- `MAX_UPLOAD_SIZE` - Maximum file upload size (bytes)
- `UPLOAD_DIR` - Retired local upload directory; workflow originals use private R2
- `ALLOWED_EXTENSIONS` - Upload extensions accepted by the backend (default: `.pdf`, `.docx`)

### Troubleshooting

**Environment Variable Conflicts**: If you encounter a Pydantic validation error about `DEBUG` being an invalid boolean, you may have a conflicting system-level `DEBUG` environment variable. The `run_debug.py` script automatically handles this, but if using other methods to start the server:

```bash
# Check for conflicting environment variables
env | grep DEBUG

# If found, unset it before running
unset DEBUG
uv run fastapi dev
```

## Workflow integration

Use [.env.example](.env.example) for non-secret configuration names and inject values securely. `WORKFLOW_UPLOADS_ENABLED` defaults false; workflow extraction and retry capabilities require that flag and complete integration configuration. `/api/system/config` exposes only booleans, never URLs, customer IDs, tokens, storage credentials, or a provider selector. Model/provider SDKs and credentials are not needed in re-ink.

New extraction history contains workflow jobs only. States are `queued`, `processing`, `completed`, `failed`, `timed_out`; browser polling stops at terminal states. `POST /api/documents/{job_id}/retry` requires `document:upload` and eligible failed/timed-out work; it returns a queued upload response. No automatic fresh provider attempt, fixture fallback, or legacy adapter exists.

Review accepts useful partial results. Required identity/dates/currency and every supplied party role need explicit reviewer values before approval; missing currency/roles are not inferred. Available PDF citations remain highlightable. DOCX uses text evidence plus original download, without inline converted pages. Approval creates local records, not Core publication or a per-field verification audit.

Follow the [cutover runbook](../docs/integration/cutover.md), [contract](../docs/integration/contract.md), and [lifecycle](../docs/integration/n8n-reliability.md#application-lifecycle-and-workers). Run `TEST_DATABASE_URL=... uv run pytest -q -p no:logging` on disposable PostgreSQL and frontend `npm run build` / `npm run lint`. Live provider/deployment gates are separate from deterministic tests.
