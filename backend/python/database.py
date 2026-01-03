"""
Database configuration and session management for PostgreSQL
Connects to existing gptintermediarydb database
"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Load environment variables from multiple possible locations
# 1. Try current directory (backend/python/.env)
# 2. Try parent directory (root .env)
current_dir = Path(__file__).parent
root_dir = current_dir.parent.parent

# Try loading from both locations
env_loaded = False
if (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
    env_loaded = True
if (root_dir / ".env").exists():
    load_dotenv(dotenv_path=root_dir / ".env", override=not env_loaded)
    env_loaded = True

# If no .env file found, try default load_dotenv() behavior
if not env_loaded:
    load_dotenv()

# Get database URL from environment variable
# Format: postgresql://user:password@host:port/database
# Example: postgresql://postgres:password@localhost:5432/gptintermediarydb
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:password@localhost:5432/gptintermediarydb"
)

# Log the DATABASE_URL (with password masked for security)
if DATABASE_URL and DATABASE_URL != "postgresql://postgres:password@localhost:5432/gptintermediarydb":
    # Mask password in URL for logging
    import re
    masked_url = re.sub(r':([^:@]+)@', r':****@', DATABASE_URL)
    print(f"[DATABASE] Loaded DATABASE_URL: {masked_url}")
else:
    print(f"[DATABASE] WARNING: Using default DATABASE_URL (environment variable not found)")

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Works better with connection pooling
    echo=False,  # Set to True for SQL query debugging
    pool_pre_ping=True,  # Verify connections before using them
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()


def get_db():
    """
    Dependency function for FastAPI to get database session.
    Usage in FastAPI route:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database - create all tables that don't exist.
    This will only create tables that are defined in db_models but don't exist yet.
    """
    import db_models  # Import models to register them
    Base.metadata.create_all(bind=engine)
    print("[DATABASE] Tables checked/created successfully!")

