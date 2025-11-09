# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**re-ink** is a full-stack web application for automated reinsurance contract and party management. It allows insurance companies to upload complex reinsurance documents (PDF, DOCX), automatically extract contract details and party information using LandingAI's Agentic Document Extraction API, review the extracted data, and create structured records in the system.

### Technology Stack

**Backend**: Python 3.9+, FastAPI, SQLAlchemy, PostgreSQL, LandingAI API
**Frontend**: React 18, TypeScript, Vite, React Router, React Query, Axios

## Development Commands

### Backend (FastAPI)

Navigate to `backend/` directory for all backend commands.

**Setup**:
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Configure environment variables
```

**Database**:
```bash
# Initialize database
createdb reink_db

# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

**Run Server**:
```bash
# Development mode with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python
python -m app.main
```

**Testing**:
```bash
pytest
pytest --cov=app tests/  # With coverage
```

### Frontend (React)

Navigate to `frontend/` directory for all frontend commands.

**Setup**:
```bash
npm install
cp .env.example .env  # Configure API URL
```

**Run Development Server**:
```bash
npm run dev  # Starts on http://localhost:3000
```

**Build**:
```bash
npm run build        # Production build
npm run preview      # Preview production build
```

**Linting**:
```bash
npm run lint
```

## Architecture

### Backend Architecture

The backend follows a layered architecture pattern:

1. **API Layer** (`app/api/endpoints/`): Route handlers organized by resource
   - `documents.py`: Document upload and extraction workflow
   - `contracts.py`: Contract CRUD operations
   - `parties.py`: Party CRUD operations
   - `review.py`: Review and approval workflow

2. **Service Layer** (`app/services/`): Business logic and external integrations
   - `landingai_service.py`: Integration with LandingAI API for document extraction
   - `document_service.py`: File upload handling, validation, storage

3. **Data Layer** (`app/models/`, `app/schemas/`):
   - SQLAlchemy models define database schema
   - Pydantic schemas handle validation and serialization
   - Many-to-many relationship between Contracts and Parties via `contract_parties` association table

4. **Core** (`app/core/`): Configuration and shared utilities
   - `config.py`: Centralized settings using pydantic-settings

### Frontend Architecture

The frontend uses component-based architecture:

1. **Pages** (`src/pages/`): Top-level route components
   - `Dashboard.tsx`: Main overview with stats and recent items
   - `UploadPage.tsx`: Complete document upload workflow (upload → processing → review)
   - `ContractsPage.tsx`: List/search contracts
   - `PartiesPage.tsx`: List/search parties

2. **Components** (`src/components/`): Reusable UI components
   - `FileUpload.tsx`: Drag-and-drop file upload with validation
   - `ExtractionStatus.tsx`: Real-time status polling during extraction
   - `ReviewForm.tsx`: Review and edit extracted data before creation
   - `Layout.tsx`: Application layout with sidebar navigation

3. **Services** (`src/services/`): API integration layer
   - `api.ts`: Axios-based API client with typed endpoints for all backend operations

4. **Types** (`src/types/`): TypeScript type definitions matching backend schemas

### Key Workflows

**Document Processing Workflow**:
1. User uploads document via `FileUpload` component
2. POST to `/api/documents/upload` - saves file and triggers extraction
3. `ExtractionStatus` polls `/api/documents/status/{job_id}` for updates
4. When complete, `ReviewForm` displays extracted data
5. User reviews/edits data
6. POST to `/api/review/approve` creates Contract and Party records

**Data Relationships**:
- Each Contract can have multiple Parties
- Each Party can be associated with multiple Contracts
- The `contract_parties` association table stores the many-to-many relationship with a `role` field (e.g., "cedent", "reinsurer", "broker")

## Database Models

### Contract Model (`backend/app/models/contract.py`)
Stores reinsurance contract details including:
- Identification: contract_number (unique), contract_name, contract_type
- Dates: effective_date, expiration_date, inception_date
- Financial: premium_amount, currency, limit_amount, retention_amount, commission_rate
- Coverage: line_of_business, coverage_territory, coverage_description
- Workflow: status, review_status, extraction metadata
- Relationships: Many-to-many with Party model

### Party Model (`backend/app/models/party.py`)
Stores party (organization/individual) information:
- Basic: name, party_type (cedent/reinsurer/broker/other)
- Contact: email, phone, address fields
- Business: registration_number (unique), license_number
- Metadata: notes, is_active, timestamps

## Important Implementation Details

### LandingAI Integration (`backend/app/services/landingai_service.py`)

The `LandingAIService` class handles all interactions with LandingAI's API:
- `submit_document_for_extraction()`: Uploads document and initiates extraction
- `get_extraction_status()`: Polls for job status
- `get_extraction_results()`: Retrieves completed extraction data
- `parse_extraction_results()`: Transforms API response into application format

**Note**: The current implementation includes placeholder logic for LandingAI API integration. You'll need to adjust the API calls according to LandingAI's actual API specification.

### File Upload Security (`backend/app/services/document_service.py`)

The `DocumentService` implements security best practices:
- File type validation (only PDF and DOCX allowed)
- File size limits (configurable via `MAX_UPLOAD_SIZE`)
- Filename sanitization to prevent directory traversal
- Chunked reading to prevent memory issues with large files

### Frontend State Management

- **Server State**: React Query manages all API data fetching, caching, and synchronization
- **UI State**: Local component state using `useState` for forms and UI interactions
- **Routing**: React Router handles navigation with client-side routing

### API Response Format

All API endpoints follow consistent patterns:
- Success responses return data directly or with appropriate status codes
- Error responses include `detail` field with error message
- List endpoints support pagination via `skip` and `limit` query parameters
- Filter endpoints accept optional query parameters

## Environment Configuration

### Backend Environment Variables (backend/.env)
- `DATABASE_URL`: PostgreSQL connection string
- `LANDINGAI_API_KEY`: API key for LandingAI
- `LANDINGAI_API_URL`: LandingAI API endpoint
- `SECRET_KEY`: Application secret for security
- `MAX_UPLOAD_SIZE`: Maximum file size in bytes (default: 50MB)
- `UPLOAD_DIR`: Directory for uploaded files
- `ALLOWED_ORIGINS`: CORS allowed origins

### Frontend Environment Variables (frontend/.env)
- `VITE_API_BASE_URL`: Backend API base URL (default: http://localhost:8000/api)

## Common Development Tasks

### Adding a New API Endpoint

1. Create/update route handler in `backend/app/api/endpoints/`
2. Define Pydantic schemas in `backend/app/schemas/`
3. Implement business logic in `backend/app/services/` if needed
4. Add endpoint to router in `backend/app/api/__init__.py`
5. Update frontend API client in `frontend/src/services/api.ts`
6. Add TypeScript types in `frontend/src/types/index.ts`

### Database Schema Changes

1. Modify SQLAlchemy models in `backend/app/models/`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `backend/alembic/versions/`
4. Apply migration: `alembic upgrade head`
5. Update Pydantic schemas to match new model structure

### Adding a New React Component

1. Create component file in appropriate directory (`pages/` or `components/`)
2. Define prop types using TypeScript interfaces
3. Import and use API functions from `services/api.ts`
4. Add routing in `App.tsx` if it's a page component
5. Update navigation in `components/Layout.tsx` if needed

## Testing Strategy

### Backend Testing
- Unit tests for service layer logic
- Integration tests for API endpoints
- Database fixture setup for consistent test data
- Mock external API calls (LandingAI)

### Frontend Testing
- Component testing with React Testing Library (not yet implemented)
- API integration testing with mock server
- E2E testing for critical workflows (not yet implemented)

## Deployment Considerations

### Backend
- Use production WSGI server (e.g., Gunicorn with Uvicorn workers)
- Set up proper database connection pooling
- Configure file storage (consider cloud storage for production)
- Set appropriate CORS origins
- Use environment-specific configuration
- Set up proper logging and monitoring

### Frontend
- Build with `npm run build`
- Serve static files via CDN or web server
- Configure environment-specific API URLs
- Enable compression and caching headers

## Code Style and Standards

### Backend (Python)
- Follow PEP 8 style guide
- Use type hints for function signatures
- Document complex business logic with docstrings
- Keep route handlers thin, move logic to services
- Use async/await for I/O operations

### Frontend (TypeScript/React)
- Use functional components with hooks
- Define explicit TypeScript types (avoid `any`)
- Keep components focused and single-responsibility
- Use meaningful variable and function names
- Organize imports: React → third-party → local

## Troubleshooting

### Backend Issues
- **Database connection errors**: Check `DATABASE_URL` and PostgreSQL service
- **File upload failures**: Verify `UPLOAD_DIR` exists and has write permissions
- **LandingAI errors**: Validate API key and check API response format
- **CORS errors**: Add frontend URL to `ALLOWED_ORIGINS`

### Frontend Issues
- **API connection errors**: Verify backend is running and `VITE_API_BASE_URL` is correct
- **Type errors**: Ensure types in `src/types/` match backend schemas
- **Build errors**: Clear node_modules and reinstall dependencies
