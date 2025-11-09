# re-ink Project Structure

Complete overview of the re-ink application architecture.

## High-Level Architecture

```
re-ink/
├── backend/          # FastAPI REST API
├── frontend/         # React SPA
├── CLAUDE.md         # Development guidance
└── README.md         # Project overview
```

## Backend Architecture (FastAPI)

### Directory Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── endpoints/
│   │   │   ├── contracts.py      # Contract CRUD endpoints
│   │   │   ├── parties.py        # Party CRUD endpoints
│   │   │   ├── documents.py      # Document upload/extraction
│   │   │   └── review.py         # Review workflow endpoints
│   │   └── __init__.py           # API router configuration
│   ├── core/
│   │   ├── config.py             # Application settings
│   │   └── __init__.py
│   ├── db/
│   │   ├── database.py           # Database connection
│   │   └── __init__.py
│   ├── models/
│   │   ├── contract.py           # Contract SQLAlchemy model
│   │   ├── party.py              # Party SQLAlchemy model
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── contract.py           # Contract Pydantic schemas
│   │   ├── party.py              # Party Pydantic schemas
│   │   ├── document.py           # Document schemas
│   │   └── __init__.py
│   ├── services/
│   │   ├── landingai_service.py  # LandingAI integration
│   │   ├── document_service.py   # File handling
│   │   └── __init__.py
│   └── main.py                   # FastAPI application
├── alembic/                      # Database migrations
├── tests/                        # Test files
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
└── alembic.ini                   # Alembic configuration
```

### Key Components

**Models** (SQLAlchemy ORM)
- `Contract`: Reinsurance contract with dates, terms, parties
- `Party`: Organizations/individuals (cedent, reinsurer, broker)
- Many-to-many relationship via `contract_parties` association table

**Services**
- `LandingAIService`: Integrates with LandingAI API for document extraction
- `DocumentService`: Handles file upload, validation, storage

**API Endpoints**
- Documents: Upload → Extract → Status → Results
- Contracts: CRUD + party associations
- Parties: CRUD + search
- Review: Approve/reject extracted data

## Frontend Architecture (React)

### Directory Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── FileUpload.tsx        # Drag-and-drop upload
│   │   ├── ExtractionStatus.tsx  # Status polling
│   │   ├── ReviewForm.tsx        # Data review/edit
│   │   └── Layout.tsx            # App layout/navigation
│   ├── pages/
│   │   ├── Dashboard.tsx         # Main dashboard
│   │   ├── UploadPage.tsx        # Upload workflow
│   │   ├── ContractsPage.tsx     # Contract listing
│   │   └── PartiesPage.tsx       # Party listing
│   ├── services/
│   │   └── api.ts                # Axios API client
│   ├── types/
│   │   └── index.ts              # TypeScript types
│   ├── styles/
│   │   └── App.css               # Application styles
│   ├── App.tsx                   # Main app component
│   └── main.tsx                  # Entry point
├── public/                       # Static assets
├── package.json                  # Dependencies
├── tsconfig.json                 # TypeScript config
├── vite.config.ts                # Vite configuration
└── index.html                    # HTML template
```

### Component Hierarchy

```
App
└── Layout
    ├── Sidebar (Navigation)
    └── Main Content
        ├── Dashboard
        │   ├── Stats Cards
        │   ├── Recent Contracts Table
        │   └── Recent Parties Grid
        ├── UploadPage
        │   ├── Workflow Steps
        │   ├── FileUpload
        │   ├── ExtractionStatus
        │   └── ReviewForm
        ├── ContractsPage
        │   ├── Filters/Search
        │   └── Contracts Table
        └── PartiesPage
            ├── Filters/Search
            └── Parties Grid
```

### Data Flow

1. **Upload Workflow**:
   - User uploads file → FileUpload component
   - POST /api/documents/upload
   - Background extraction starts
   - ExtractionStatus polls GET /api/documents/status/{job_id}
   - When complete, ReviewForm displays results
   - User reviews/edits → POST /api/review/approve
   - Creates Contract + Parties

2. **State Management**:
   - React Query for server state
   - Local state with useState for UI
   - React Router for navigation

## Database Schema

### Tables

**contracts**
- Primary key: id
- Unique: contract_number
- Foreign keys: None (uses association table)
- Key fields: dates, financial terms, coverage details, status

**parties**
- Primary key: id
- Unique: registration_number
- Key fields: contact info, business details

**contract_parties** (association)
- Composite primary key: (contract_id, party_id)
- Additional field: role (relationship type)

## Workflow

### Document Processing Workflow

```
1. Upload
   ↓
2. Save to disk
   ↓
3. Submit to LandingAI API
   ↓
4. Poll for status
   ↓
5. Retrieve results
   ↓
6. Display for review
   ↓
7. User approves/rejects
   ↓
8. Create records in database
```

### Technology Decisions

**Backend**
- FastAPI: Modern, fast, automatic API docs
- SQLAlchemy: Robust ORM with migrations
- Pydantic: Data validation and serialization
- PostgreSQL: Reliable relational database

**Frontend**
- React: Component-based UI
- TypeScript: Type safety
- Vite: Fast development experience
- React Query: Server state management
- Axios: HTTP client

## Configuration

### Environment Variables

**Backend** (.env)
- Database connection
- LandingAI API credentials
- File upload settings
- Security settings

**Frontend** (.env)
- API base URL

### Port Configuration

- Backend: 8000
- Frontend: 3000
- Frontend proxies `/api` to backend in development
