# re-ink

**Automated Reinsurance Contracts & Parties creation using Agentic Document Extraction**

re-ink is a full-stack web application that streamlines reinsurance contract management by automatically extracting contract details and party information from uploaded documents using AI-powered document extraction.

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
- `POST /api/documents/upload` - Upload document
- `GET /api/documents/status/{job_id}` - Get extraction status
- `GET /api/documents/results/{job_id}` - Get extraction results

### Contracts
- `GET /api/contracts/` - List contracts
- `POST /api/contracts/` - Create contract
- `GET /api/contracts/{id}` - Get contract details
- `PUT /api/contracts/{id}` - Update contract
- `DELETE /api/contracts/{id}` - Delete contract

### Parties
- `GET /api/parties/` - List parties
- `POST /api/parties/` - Create party
- `GET /api/parties/{id}` - Get party details
- `PUT /api/parties/{id}` - Update party

### Review
- `POST /api/review/approve` - Approve extracted data
- `POST /api/review/reject/{job_id}` - Reject extraction

## Development

See detailed development guides:
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [Project Structure](PROJECT_STRUCTURE.md)
- [CLAUDE.md](CLAUDE.md) - Development guidance for Claude Code

## Configuration

### Backend (.env)
```env
DATABASE_URL=postgresql://user:password@localhost:5432/reink_db
LANDINGAI_API_KEY=your_api_key
LANDINGAI_API_URL=https://api.landing.ai/v1/agent/document-extraction
SECRET_KEY=your_secret_key
MAX_UPLOAD_SIZE=52428800
UPLOAD_DIR=./uploads
ALLOWED_ORIGINS=http://localhost:3000
```

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
