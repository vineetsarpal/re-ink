# re-ink

**Automated Reinsurance Contracts & Parties creation using Agentic Document Extraction**

re-ink is a full-stack web application that streamlines reinsurance contract management by automatically extracting contract details and party information from uploaded documents using AI-powered document extraction.

## Recognition

**Finalist** in the [LandingAI Financial AI Hackathon Championship 2025](https://community.landing.ai/c/events-ade/financial-ai-hackathon-championship-2025)

## Features

- 📄 **Document Upload**: Upload PDF and DOCX reinsurance contract documents
- 🤖 **AI Extraction**: Automatic extraction of contract terms and parties using LandingAI
- ✅ **Review Workflow**: Review and edit AI-extracted data before creating records
- 📊 **Contract Management**: Full CRUD operations for reinsurance contracts
- 👥 **Party Management**: Manage parties (cedents, reinsurers, brokers)
- 🔍 **Search & Filter**: Find contracts and parties quickly
- 📈 **Dashboard**: Overview of contracts and parties with statistics
- 🧪 **Sample Extraction Mode**: Seed mock data to test the workflow without LandingAI
- 🤝 **AI Agent Guidance**: LangChain/LangGraph agents surface intake insights and automated reviews

## UI Preview

![re-ink home page](assets/screenshots/home-pg.png)

## Sample Documents

- Browse curated sample files in `sample_documents/` to exercise the ingestion workflow end to end.
- Documents are sourced from public SEC EDGAR filings (https://www.sec.gov/edgar/search/) and trimmed to the excerpts needed for development and QA.
- To upload a sample through the app, remove the `.example` suffix (or convert back to a standard PDF/DOCX) so the file matches the expected format.
- When committing binary samples, rename them with `.pdf.example` or `.docx.example` suffixes so they bypass the `.gitignore` filters while preserving their original format.

## Technology Stack

### Backend
- **FastAPI**: Modern Python web framework
- **SQLAlchemy**: ORM for database operations
- **PostgreSQL**: Relational database
- **LandingAI**: Agentic document extraction API
- **Alembic**: Database migrations

### Frontend
- **React 18**: UI framework
- **TypeScript**: Type-safe JavaScript
- **Vite**: Fast build tool
- **React Router**: Client-side routing
- **React Query**: Server state management
- **Axios**: HTTP client

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              USER / BROWSER                                │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │     React Frontend    │
                    │  - Upload & Review UI │
                    │  - AI Insight Panels  │
                    └───────────┬───────────┘
                                │  HTTP/REST
                    ┌───────────▼───────────┐
                    │     FastAPI Backend   │
                    │                       │
                    │ /api/documents        │
                    │ /api/review           │
                    │ /api/agents           │
                    └───┬──────────────┬────┘
                        │              │
                ┌───────▼───┐      ┌───▼───────────────┐
                │ Document  │      │ Agent Service     │
                │ Service   │      │ (LangChain/Graph) │
                │ (LandingAI│      │ - Guided Intake   │
                │  workflow)│      │ - Contract Review │
                └────┬──────┘      └────┬──────────────┘
                     │                  │
      ┌──────────────▼──────────┐       │
      │ Extraction Job Store    │       │
      │ (status + parsed data)  │       │
      └──────────────┬──────────┘       │
                     │                  │
        ┌────────────▼────────┐         │
        │ LandingAI ADE API   │         │
        │ Parse & Extract     │         │
        └────────────┬────────┘         │
                     │                  │
        ┌────────────▼────────┐         │            ┌─────────────────┐
        │ PostgreSQL          │◄────────┼────────────┤ LangChain LLM   │
        │ Contracts & Parties │         │  prompts   │  (OpenAI, etc.) │
        └─────────────────────┘         │            └─────────────────┘
                                        │
                                        │
                            (insights returned to frontend)

```

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

Use `make backend-dev` or `make frontend-dev` if you want to run either side individually, and `make backend-install` / `make frontend-install` to refresh dependencies.

### Prerequisites

- Python 3.9+
- Node.js 18+
- PostgreSQL 12+
- LandingAI API key

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Set up database
createdb reink_db
alembic upgrade head

# Run server
uvicorn app.main:app --reload
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

## Project Structure

```
re-ink/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── core/        # Configuration
│   │   ├── db/          # Database setup
│   │   ├── models/      # Database models
│   │   ├── schemas/     # Pydantic schemas
│   │   ├── services/    # Business logic
│   │   └── main.py      # Application entry
│   ├── alembic/         # Database migrations
│   └── requirements.txt
├── frontend/            # React frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── pages/       # Page components
│   │   ├── services/    # API client
│   │   ├── types/       # TypeScript types
│   │   └── styles/      # CSS styles
│   └── package.json
└── README.md
```

## Workflow

1. **Upload**: User uploads a reinsurance contract document (PDF or DOCX)
2. **Extract**: System sends document to LandingAI for AI-powered extraction
3. **Process**: AI extracts contract details, dates, financial terms, and party information
4. **Review**: User reviews and edits the extracted data in a user-friendly form
5. **Approve**: User approves the data, creating Contract and Party records
6. **Manage**: Contracts and parties can be viewed, searched, and managed

## API Endpoints

### Documents
- `POST /api/documents/upload` - Upload a document and start extraction in the background
- `GET /api/documents/status/{job_id}` - Check extraction status (supports `processing`, `completed`, `failed`)
- `GET /api/documents/results/{job_id}` - Retrieve parsed extraction results when a job is complete

### Contracts
- `GET /api/contracts/` - List contracts (supports `status`, `contract_type`, `skip`, `limit` filters)
- `POST /api/contracts/` - Create a contract
- `GET /api/contracts/{id}` - Get contract details with associated parties
- `PUT /api/contracts/{id}` - Update contract fields
- `DELETE /api/contracts/{id}` - Soft delete a contract
- `POST /api/contracts/{id}/parties/{party_id}` - Link a party to a contract with a role
- `DELETE /api/contracts/{id}/parties/{party_id}` - Remove a party association from a contract

### Parties
- `GET /api/parties/` - List parties (supports `party_type`, `is_active`, `skip`, `limit`)
- `POST /api/parties/` - Create a party
- `GET /api/parties/{id}` - Get party details
- `PUT /api/parties/{id}` - Update party fields
- `DELETE /api/parties/{id}` - Soft delete a party
- `GET /api/parties/search/by-name` - Search parties by partial name match

### Review
- `POST /api/review/approve` - Approve extracted data
- `POST /api/review/reject/{job_id}` - Reject extraction

### Agents
- `POST /api/agents/intake` - Run the guided intake LangChain agent for an extraction job
- `POST /api/agents/review` - Generate an automated review for a contract

### System
- `GET /api/system/config` - Return agent configuration flags (e.g., offline mode) for the frontend

## Development

 See detailed development guides:
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [CLAUDE.md](CLAUDE.md) - Development guidance for Claude Code

## Configuration

### Backend (.env)
```env
APP_NAME=re-ink
APP_VERSION=1.0.0
DEBUG=false
SECRET_KEY=your_secret_key
DATABASE_URL=postgresql://user:password@localhost:5432/reink_db
LANDINGAI_API_KEY=your_landingai_api_key
LANDINGAI_PARSE_URL=https://api.va.landing.ai/v1/ade/parse
LANDINGAI_EXTRACT_URL=https://api.va.landing.ai/v1/ade/extract
LANDINGAI_PARSE_MODEL=dpt-2-latest
LANDINGAI_EXTRACT_MODEL=extract-latest
MAX_UPLOAD_SIZE=52428800
UPLOAD_DIR=./uploads
ALLOWED_EXTENSIONS=.pdf,.docx
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
ACCESS_TOKEN_EXPIRE_MINUTES=30
LOG_LEVEL=INFO
OPENAI_API_KEY=your_openai_key
AGENT_MODEL=gpt-4o-mini
AGENT_TEMPERATURE=0.1
AGENT_OFFLINE_MODE=false
```

- `OPENAI_API_KEY` is only needed when LangChain/LangGraph agents should call OpenAI; set `AGENT_OFFLINE_MODE=true` to bypass those calls locally.
- `ALLOWED_ORIGINS` supports JSON array notation (shown above) or a comma-separated list.
- Adjust `MAX_UPLOAD_SIZE`, `ALLOWED_EXTENSIONS`, and `UPLOAD_DIR` if you need to support additional file formats.

### Frontend (.env)
```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## License

See [LICENSE](LICENSE) file for details.

## Contributing

This project is designed for insurance and reinsurance companies to streamline contract management workflows. Contributions are welcome!

## Support

For issues, questions, or feature requests, please open an issue on the project repository.
