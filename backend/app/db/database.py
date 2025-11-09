"""
Database connection and session management.
Provides SQLAlchemy engine, session factory, and base class for models.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Ensure DATABASE_URL uses psycopg driver (for psycopg 3.x)
database_url = settings.DATABASE_URL
if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
    # Replace postgresql:// with postgresql+psycopg:// for psycopg 3.x
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

# Create database engine
engine = create_engine(
    database_url,
    pool_pre_ping=True,  # Enable connection health checks
    echo=settings.DEBUG,  # Log SQL queries in debug mode
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """
    Dependency function to get database session.
    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
