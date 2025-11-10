# re-ink Backend

FastAPI backend for the re-ink reinsurance contract management system.

## Features

- **Document Processing**: Upload and process PDF/DOCX contract documents
- **AI Extraction**: Integration with LandingAI's Agentic Document Extraction API
- **Contract Management**: Full CRUD operations for reinsurance contracts
- **Party Management**: Manage parties (cedents, reinsurers, brokers)
- **Review Workflow**: Review and approve AI-extracted data before creation
- **Agent Workflows**: LangChain/LangGraph agents for guided intake and automated reviews

## Setup

### Prerequisites

- Python 3.9+
- PostgreSQL 12+

### Installation

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Initialize the database:
```bash
# Create PostgreSQL database
createdb reink_db

# Run migrations
alembic upgrade head
```

### Running the Server

Development mode with auto-reload:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or using Python directly:
```bash
python -m app.main
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
└── requirements.txt      # Python dependencies
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

### Agents
- `POST /api/agents/intake` - Guided intake helper over extraction jobs
- `POST /api/agents/review` - Automated compliance and risk summary for a contract
- `POST /api/documents/mock-job` - Seed a mock extraction job for offline testing

## Database Migrations

Create a new migration:
```bash
alembic revision --autogenerate -m "description"
```

Apply migrations:
```bash
alembic upgrade head
```

Rollback:
```bash
alembic downgrade -1
```

## Configuration

Key environment variables:

- `DATABASE_URL` - PostgreSQL connection string
- `LANDINGAI_API_KEY` - LandingAI API key
- `LANDINGAI_PARSE_URL` - LandingAI Parse API endpoint (default: https://api.va.landing.ai/v1/ade/parse)
- `LANDINGAI_EXTRACT_URL` - LandingAI Extract API endpoint (default: https://api.va.landing.ai/v1/ade/extract)
- `LANDINGAI_PARSE_MODEL` - Parse model version (default: dpt-2-latest)
- `LANDINGAI_EXTRACT_MODEL` - Extract model version (default: extract-latest)
- `OPENAI_API_KEY` - API key for the default chat model powering agents
- `AGENT_MODEL` - Chat model identifier (default: gpt-4o-mini)
- `AGENT_TEMPERATURE` - Creativity/variance setting for agent responses (default: 0.1)
- `AGENT_OFFLINE_MODE` - Set to `true` to bypass external LLM calls during local tests
- `SECRET_KEY` - Application secret key
- `DEBUG` - Enable debug mode (default: False)
- `LOG_LEVEL` - Logging level (default: INFO)
- `MAX_UPLOAD_SIZE` - Maximum file upload size (bytes)
- `UPLOAD_DIR` - Directory for storing uploaded files

## Offline Testing (No LandingAI Credits)

You can exercise the complete intake-to-review workflow without using LandingAI or OpenAI:

1. Enable offline mode and point the backend at a local SQLite database:
    ```bash
    export AGENT_OFFLINE_MODE=true
    export DATABASE_URL=sqlite:///./dev_agents.db
    export SECRET_KEY=test-secret
    export LANDINGAI_API_KEY=dummy
    ```
2. Seed a mock extraction job:
    ```bash
    curl -X POST http://localhost:8000/api/documents/mock-job
    ```
   The response includes `job_id`.
3. Request guided intake help (replace `<JOB_ID>`):
    ```bash
    curl -X POST http://localhost:8000/api/agents/intake \
      -H "Content-Type: application/json" \
      -d '{"job_id":"<JOB_ID>","user_input":"Review this extraction"}'
    ```
   Use the returned `suggested_review_payload` with `POST /api/review/approve`.
4. Run the automated contract review with the new `contract_id`:
    ```bash
    curl -X POST http://localhost:8000/api/agents/review \
      -H "Content-Type: application/json" \
      -d '{"contract_id":123,"user_input":"Summarise compliance posture"}'
    ```
The agents return deterministic, heuristic guidance in offline mode so you can validate the entire flow without external credits.

### Sample Extraction With Live LLM

If you still want LangChain/LangGraph to use your `OPENAI_API_KEY` but prefer not to call LandingAI, leave `AGENT_OFFLINE_MODE` unset/`false`, start the backend, and either:

- Call `POST /api/documents/mock-job` manually (returns a ready-to-review extraction), or
- Click **Use Sample Extraction** on the frontend upload page.

Both options seed the extraction store with representative contract data so the guided intake and automated review agents run against OpenAI responses while skipping LandingAI entirely.
After approving the contract, navigate to its detail page and press **Generate AI Review** to request the automated summary when needed.

### Troubleshooting

**Environment Variable Conflicts**: If you encounter a Pydantic validation error about `DEBUG` being an invalid boolean, you may have a conflicting system-level `DEBUG` environment variable. The `run_debug.py` script automatically handles this, but if using other methods to start the server:

```bash
# Check for conflicting environment variables
env | grep DEBUG

# If found, unset it before running
unset DEBUG
uvicorn app.main:app --reload
```
