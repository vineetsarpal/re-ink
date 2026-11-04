# re-ink

**Automated Reinsurance Contracts & Parties creation using Agentic Document Extraction**

re-ink is a full-stack web application that streamlines reinsurance contract management by automatically extracting contract details and party information from uploaded documents using AI-powered document extraction.

## Recognition

**Finalist** in the [LandingAI Financial AI Hackathon Championship 2025](https://community.landing.ai/c/events-ade/financial-ai-hackathon-championship-2025)

## Demo
 [![Watch the demo](https://img.youtube.com/vi/ylZ9jSDByLQ/maxresdefault.jpg)](https://www.youtube.com/watch?v=ylZ9jSDByLQ)

## Features

- 📄 **Document Upload**: Upload PDF and DOCX reinsurance contract documents
- 🤖 **AI Extraction**: Automatic extraction of contract terms and parties through a separately hosted n8n workflow
- ✅ **Review Workflow**: Review and edit AI-extracted data before creating records
- 🔎 **Source-Grounded Review**: Available citations link fields to real passages; fields without evidence require manual checking. PDF supports page highlights; DOCX uses original download
- 🔐 **WorkOS Authentication**: AuthKit sign-in, org-scoped API access, and automatic organization provisioning for new users
- 📊 **Contract Management**: Full CRUD operations for reinsurance contracts
- 👥 **Party Management**: Manage parties (cedants, reinsurers, brokers)
- 🔁 **Party Deduplication**: Fuzzy-match extracted party names to existing records before approval
- 🔍 **Search & Filter**: Find contracts and parties quickly
- 📈 **Dashboard**: Overview of contracts and parties with statistics


## Sample Documents

Use the synthetic evaluation corpus and expected manifest in `scripts/` and `docs/integration/`. Upload originals through the configured workflow. Deterministic fixtures are not live extraction evidence.


## Technology Stack

### Backend
- **FastAPI**: Modern Python web framework
- **SQLAlchemy**: ORM for database operations
- **PostgreSQL**: Relational database
- **WorkOS**: Authentication, organizations, and account widgets
- **Alembic**: Database migrations

### Frontend
- **React 18**: UI framework
- **TypeScript**: Type-safe JavaScript
- **Vite**: Fast build tool
- **React Router**: Client-side routing
- **TanStack React Query**: Server state management
- **Axios**: HTTP client
- **WorkOS AuthKit & Widgets**: Hosted auth and self-service account UI
- **pdf.js**: Source document preview with field-level bounding boxes
- **React Hook Form**: Review form state management
- **Lucide React**: Icon library

## Architecture

The browser uploads to FastAPI, which stores the original privately and commits a workflow job, attempt, and outbox intent. A separate dispatcher calls n8n. The workflow claims its attempt, retrieves the original with a scoped service credential, calls its configured provider, and posts a validated normalized result. PostgreSQL persists lifecycle state; human review and permission-gated approval remain in re-ink.

This is a simulated customer environment with synthetic documents. The app/database and n8n/dispatcher are separately hosted; external providers receive document content. It is not a private or production-certified customer deployment. Guided intake and automated review are disabled.

## Quick Start

### Rapid Start via Makefile

The repo includes a Makefile so you can bootstrap both services quickly:

```bash
# Install backend + frontend dependencies
make setup

# Copy and edit environment files (run once)
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Launch both dev servers (Ctrl+C stops both)
make dev
```

Use `make backend-dev` or `make frontend-dev` to run either side individually, and `make backend-install` / `make frontend-install` to refresh dependencies. `make sync-version` copies the root `VERSION` file into `backend/` (included automatically in `make setup`).

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package & project manager)
- Python 3.13+ (uv can install this for you)
- Node.js 18+
- PostgreSQL 12+
- WorkOS AuthKit application/client ID
- Private R2 original storage, configured n8n workflow/dispatcher, separate scoped service credentials (see [storage/access](docs/integration/storage-access.md))

### Backend Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`). `uv sync` creates the `.venv` and installs the locked dependencies; `uv run` executes commands inside it, so there's no virtualenv to activate manually.

```bash
cd backend

# Install dependencies (creates .venv; dev group included by default)
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Set up database
createdb reink_db
uv run alembic upgrade head   # builds schema from migrations on a fresh DB

# For an existing DB previously created by create_all() — stamp it first (one-time):
# uv run alembic stamp 0001_baseline && uv run alembic upgrade head

# Run server (auto-reload; entrypoint is configured in pyproject.toml)
uv run fastapi dev
# or use: make backend-dev
```

Backend will be available at http://localhost:8000
API docs at http://localhost:8000/docs

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment
cp .env.example .env
# Edit .env with backend URL

# Run development server
npm run dev
# or use: make frontend-dev
```

Frontend will be available at http://localhost:3000

### WorkOS RBAC configuration (one-time)

Roles and permissions are defined **environment-level in the WorkOS dashboard**, not in code — the API only enforces the permission claims WorkOS puts on the access token. Configure this once per WorkOS environment before role enforcement works:

1. **Create permissions**: `contract:read`, `contract:write`, `contract:delete`, `party:read`, `party:write`, `party:delete`, `document:upload`, `review:approve`, `member:manage`, `sso:manage`.
2. **Create roles** and assign permissions:
   - `viewer` — all `*.read`
   - `member` — `viewer` + all `*:write` + `document:upload` + `review:approve`
   - `admin` — `member` + all `*:delete` + `member:manage` + `sso:manage`
3. **Set `viewer` as the environment default role** (applied to domain-claim auto-joins and SSO/JIT users).
4. **(Deferred) Enable directory group role assignment** — only needed once a customer connects a SCIM/Google Workspace directory, so their IdP groups can map to roles. Turn on when the first such tenant onboards; note that IdP group→role mappings override roles assigned via the API or dashboard.

Use the exact permission slugs above — enforcement matches on them, and a typo fails closed (silent deny).

## Project Structure

```
re-ink/
├── VERSION                   # Single source of truth for app version
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── api/             # API endpoints
│   │   ├── core/            # Configuration (reads VERSION file)
│   │   ├── db/              # Database setup
│   │   ├── models/          # SQLAlchemy models (Contract, Party, ExtractionJob)
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # Business logic
│   │   └── main.py          # Application entry
│   ├── alembic/             # Database migrations
│   ├── scripts/             # Utility scripts
│   ├── tests/               # Backend test suite
│   └── pyproject.toml
├── frontend/                 # React frontend
│   ├── public/
│   │   └── samples/         # Bundled sample PDFs (selectable in UI)
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── pages/           # Page components
│   │   ├── services/        # API client
│   │   ├── types/           # TypeScript types
│   │   └── styles/          # CSS styles
│   └── package.json

```

## Workflow

1. **Sign in**: User authenticates through WorkOS AuthKit; API requests are scoped to the active organization
2. **Upload**: User uploads a reinsurance contract document (PDF or DOCX), or selects a bundled sample
3. **Extract**: A durable workflow attempt dispatches to n8n; provider configuration and credentials live in n8n. No provider fallback runs inside re-ink.
4. **Process**: AI extracts contract details, dates, financial terms, party information, and source evidence
5. **Review**: User reviews and edits extracted data, verifies grounded fields against the source PDF, and links likely duplicate parties
6. **Approve**: User approves the data, creating Contract and Party records
7. **Manage**: Contracts and parties can be viewed, searched, and managed

## API Endpoints

Browser resource endpoints require a WorkOS Bearer token; machine workflow endpoints use separate scoped service authentication (see the integration contract). `/api/system/config` exposes public booleans. The `/api/onboarding/provision-organization` endpoint accepts an authenticated user before they have an organization so it can provision one. Public health endpoints are available at `/` and `/health`.

### Documents
- `POST /api/documents/upload` - Persist an original and queue a durable workflow attempt
- `GET /api/documents/status/{job_id}` - Check extraction status (`queued`, `processing`, `completed`, `failed`, `timed_out`)
- `GET /api/documents/results/{job_id}` - Retrieve parsed extraction results when a job is complete
- `GET /api/documents/file/{job_id}` - Stream the original uploaded document for the review preview panel
- `POST /api/documents/{job_id}/retry` - Permission-gated retry for eligible failed/timed-out workflow jobs
- `DELETE /api/documents/{job_id}` - Delete a document and its extraction job

### Contracts
- `GET /api/contracts/` - List contracts (supports `status`, `contract_type`, `skip`, `limit` filters)
- `POST /api/contracts/` - Create a contract
- `GET /api/contracts/{id}` - Get contract details with associated parties
- `PUT /api/contracts/{id}` - Update contract fields
- `DELETE /api/contracts/{id}` - Soft delete a contract
- `POST /api/contracts/{id}/parties/{party_id}` - Link a party to a contract with a role
- `PATCH /api/contracts/{id}/parties/{party_id}` - Update a linked party's contract role
- `DELETE /api/contracts/{id}/parties/{party_id}` - Remove a party association from a contract

### Parties
- `GET /api/parties/` - List parties (supports `is_active`, `skip`, `limit`)
- `POST /api/parties/` - Create a party
- `POST /api/parties/match` - Fuzzy-match extracted party names against existing parties
- `GET /api/parties/{id}` - Get party details
- `PUT /api/parties/{id}` - Update party fields
- `DELETE /api/parties/{id}` - Soft delete a party
- `GET /api/parties/search/by-name` - Search parties by partial name match

### Review
- `POST /api/review/approve` - Approve extracted data
- `POST /api/review/reject/{job_id}` - Reject extraction

### Agents
- `POST /api/agents/intake` - Disabled (503); existing upload permission remains enforced
- `POST /api/agents/review` - Disabled (503); existing contract-read permission remains enforced

### System
- `GET /api/system/config` - Return public workflow extraction/retry and disabled agent capabilities

### Widgets
- `POST /api/widgets/user-profile/token` - Mint a WorkOS User Profile widget token for the signed-in user

### Onboarding
- `POST /api/onboarding/provision-organization` - Ensure a signed-in user belongs to an organization, creating one if needed

## Development

 See detailed development guides:
- [User Guide](docs/user-guide/README.md)
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [CLAUDE.md](CLAUDE.md) - Development guidance for Claude Code

## Configuration

### Backend (.env)
```env
DATABASE_URL=postgresql://user:password@localhost:5432/reink_db
WORKOS_CLIENT_ID=client_...
WORKOS_API_KEY=sk_...             # Required for account widgets and org provisioning; not needed for access-token validation
MAX_UPLOAD_SIZE=52428800
UPLOAD_DIR=./uploads
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
LOG_LEVEL=INFO
```

- `WORKOS_CLIENT_ID` drives WorkOS issuer and JWKS validation for protected API routes.
- `WORKOS_API_KEY` is required for server-side WorkOS calls, including User Profile widget tokens and automatic organization provisioning.
- `ALLOWED_ORIGINS` supports JSON array notation (shown above) or a comma-separated list. In production, set this to your deployed frontend URL.
- The app version is read from the `VERSION` file at the repo root — do not set `APP_VERSION` in `.env`.
- **CI/CD**: The deploy workflow runs `uv run alembic upgrade head` before deploying. The GitHub Actions secret `DATABASE_URL` must be configured in the repository settings for migrations to run in CI.

Workflow variables and secret placeholders are listed in [backend/.env.example](backend/.env.example). Uploads start disabled. Supply `WORKFLOW_CUSTOMER_ORG_ID`, trusted HTTPS `WORKFLOW_WEBHOOK_URL`, distinct dispatch/service tokens, worker database credentials, and private R2 configuration through the deployment secret manager. Provider credentials belong only in n8n. Follow the [cutover runbook](docs/integration/cutover.md) before enabling uploads; do not commit secrets.

### Frontend (.env)
```env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_WORKOS_CLIENT_ID=client_...
VITE_WORKOS_REDIRECT_URI=http://localhost:3000/auth/callback
# Optional when using a WorkOS custom authentication domain
VITE_WORKOS_API_HOSTNAME=auth.example.com
```

## License

See [LICENSE](LICENSE) file for details.

## Contributing

This project is designed for insurance and reinsurance companies to streamline contract management workflows. Contributions are welcome!

## Support

For issues, questions, or feature requests, please open an issue on the project repository.
