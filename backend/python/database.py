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
# Prefer a configured DATABASE_URL (Postgres). If missing or using the dev default,
# fall back to a local SQLite file so the app can run standalone without PostgreSQL.
raw_db_url = os.getenv("DATABASE_URL", "").strip()

# Detect whether the env var is a meaningful Postgres URL
USE_SQLITE = False
if not raw_db_url:
    USE_SQLITE = True
else:
    # Treat obvious placeholder as unset
    if raw_db_url.startswith("postgresql://postgres:password@localhost") or raw_db_url.startswith('sqlite:') is False and 'postgres' not in raw_db_url:
        # If it's not a postgres URL, fall back to sqlite
        USE_SQLITE = True

if USE_SQLITE:
    # Place SQLite database in repo root 'data' directory
    data_dir = root_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = data_dir / 'gptintermediary.sqlite3'
    DATABASE_URL = f"sqlite:///{sqlite_path.as_posix()}"
    print(f"[DATABASE] No valid DATABASE_URL found - falling back to SQLite at {sqlite_path}")
else:
    DATABASE_URL = raw_db_url
    # Mask password in URL for logging
    import re
    masked_url = re.sub(r':([^:@]+)@', r':****@', DATABASE_URL)
    print(f"[DATABASE] Loaded DATABASE_URL: {masked_url}")

# Create SQLAlchemy engine with appropriate args per DB type
engine_kwargs = dict(echo=False)
if DATABASE_URL.startswith('sqlite:'):
    # SQLite specific options
    engine_kwargs.update({
        'connect_args': { 'check_same_thread': False },
    })
    # Use NullPool to avoid issues in bundled executables
    engine = create_engine(DATABASE_URL, poolclass=NullPool, **engine_kwargs)
else:
    engine = create_engine(DATABASE_URL, poolclass=NullPool, echo=False, pool_pre_ping=True)

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

