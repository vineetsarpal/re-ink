"""
Main FastAPI application for re-ink.
Automated Reinsurance Contracts & Parties creation using Agentic Document Extraction.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.core.config import settings
from app.api import api_router
from app.db.database import engine, Base

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    re-ink API for automated reinsurance contract and party management.

    ## Features

    * **Document Upload**: Upload PDF and DOCX contract documents
    * **AI Extraction**: Automatic extraction of contract terms and parties using LandingAI
    * **Review Workflow**: Review and approve extracted data before creating records
    * **Contract Management**: Full CRUD operations for contracts
    * **Party Management**: Full CRUD operations for parties

    ## Workflow

    1. Upload a document via `/api/documents/upload`
    2. Check extraction status via `/api/documents/status/{job_id}`
    3. Review extracted data via `/api/documents/results/{job_id}`
    4. Approve and create records via `/api/review/approve`
    5. Manage contracts and parties via respective endpoints
    """,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint - API health check."""
    return {
        "message": "Welcome to re-ink API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred. Please contact support.",
            "type": "internal_error"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
