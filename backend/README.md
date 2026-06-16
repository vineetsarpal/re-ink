# re-ink Backend

FastAPI backend for the re-ink reinsurance contract management system.

## Features

- **Document Processing**: Upload and process PDF/DOCX contract documents
- **AI Extraction**: Integration with LandingAI's Agentic Document Extraction API
- **Contract Management**: Full CRUD operations for reinsurance contracts
- **Party Management**: Manage parties (cedants, reinsurers, brokers)
- **Review Workflow**: Review and approve AI-extracted data before creation

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package & project manager)
- Python 3.13+ (uv can install this for you)
- PostgreSQL 12+

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
│   ├── agents/           # LangChain/LangGraph agent implementations
│   ├── core/             # Core configuration
│   ├── db/               # Database setup
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # Business logic
│   └── main.py           # FastAPI application
├── alembic/              # Database migrations
├── tests/                # Test files
├── pyproject.toml        # Project metadata & dependencies (uv)
└── uv.lock               # Pinned dependency lockfile
```

## API Endpoints

### Documents
- `POST /api/documents/upload` - Upload a document for extraction
- `GET /api/documents/status/{job_id}` - Get extraction status
- `GET /api/documents/results/{job_id}` - Get extraction results
- `DELETE /api/documents/{job_id}` - Delete a document

### Contracts
- `GET /api/contracts/` - List all contracts
- `POST /api/contracts/` - Create a new contract
- `GET /api/contracts/{id}` - Get contract details
- `PUT /api/contracts/{id}` - Update a contract
- `DELETE /api/contracts/{id}` - Delete a contract

### Parties
- `GET /api/parties/` - List all parties
- `POST /api/parties/` - Create a new party
- `GET /api/parties/{id}` - Get party details
- `PUT /api/parties/{id}` - Update a party
- `DELETE /api/parties/{id}` - Delete a party
- `GET /api/parties/search/by-name` - Search parties by name

### Review
- `POST /api/review/approve` - Approve and create extracted data
- `POST /api/review/reject/{job_id}` - Reject extraction

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
- `WORKOS_API_KEY` - Optional WorkOS API key for server-side WorkOS calls; not required for access-token validation
- `LANDINGAI_API_KEY` - LandingAI API key
- `LANDINGAI_PARSE_URL` - LandingAI Parse API endpoint (default: https://api.va.landing.ai/v1/ade/parse)
- `LANDINGAI_EXTRACT_URL` - LandingAI Extract API endpoint (default: https://api.va.landing.ai/v1/ade/extract)
- `LANDINGAI_PARSE_MODEL` - Parse model version (default: dpt-2-latest)
- `LANDINGAI_EXTRACT_MODEL` - Extract model version (default: extract-latest)
- `DEBUG` - Enable debug mode (default: False)
- `LOG_LEVEL` - Logging level (default: INFO)
- `MAX_UPLOAD_SIZE` - Maximum file upload size (bytes)
- `UPLOAD_DIR` - Directory for storing uploaded files

### Troubleshooting

**Environment Variable Conflicts**: If you encounter a Pydantic validation error about `DEBUG` being an invalid boolean, you may have a conflicting system-level `DEBUG` environment variable. The `run_debug.py` script automatically handles this, but if using other methods to start the server:

```bash
# Check for conflicting environment variables
env | grep DEBUG

# If found, unset it before running
unset DEBUG
uv run fastapi dev
```
