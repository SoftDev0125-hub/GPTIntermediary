"""
Database configuration and session management for PostgreSQL
Connects to existing gptintermediarydb database
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Project root: when running as PyInstaller exe, use exe directory; otherwise backend/python/../..
if getattr(sys, "frozen", False):
    root_dir = Path(sys.executable).resolve().parent
else:
    current_dir = Path(__file__).parent
    root_dir = current_dir.parent.parent
if (root_dir / ".env").exists():
    load_dotenv(dotenv_path=root_dir / ".env")
else:
    load_dotenv()

# Get database URL from environment variable
# Prefer a configured DATABASE_URL (Postgres). If missing or using the dev default,
# fall back to a local SQLite file so the app can run standalone without PostgreSQL.
_env_db_url = os.getenv("DATABASE_URL", "").strip()
_force_sqlite = os.getenv("DATABASE_USE_SQLITE", "").strip().lower() in ("1", "true", "yes")
raw_db_url = "" if _force_sqlite else _env_db_url
try:
    _pg_connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT", "10"))
except ValueError:
    _pg_connect_timeout = 10

# When running as standalone .exe (frozen), avoid requiring PostgreSQL on the target PC:
# use SQLite if DATABASE_URL is missing or points to localhost (no Postgres installed there).
is_frozen = getattr(sys, "frozen", False)

def _is_localhost_postgres(url):
    if not url or not url.strip():
        return False
    u = url.strip().lower()
    if u.startswith("sqlite:"):
        return False
    return "localhost" in u or "127.0.0.1" in u

USE_SQLITE = False
if not raw_db_url:
    USE_SQLITE = True
elif raw_db_url.startswith("sqlite:"):
    # Explicit SQLite URL: use as-is (don't overwrite with default path)
    USE_SQLITE = False
    DATABASE_URL = raw_db_url
else:
    # Postgres URL: use SQLite when standalone and URL points to localhost (PC likely has no Postgres)
    if is_frozen and _is_localhost_postgres(raw_db_url):
        USE_SQLITE = True
    elif raw_db_url.startswith("postgresql://postgres:password@localhost"):
        USE_SQLITE = True
    elif "postgres" not in raw_db_url:
        USE_SQLITE = True
    else:
        DATABASE_URL = raw_db_url

if USE_SQLITE:
    # Place SQLite database in repo root 'data' directory
    data_dir = root_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = data_dir / 'gptintermediary.sqlite3'
    DATABASE_URL = f"sqlite:///{sqlite_path.as_posix()}"
    if _force_sqlite:
        print(f"[DATABASE] DATABASE_USE_SQLITE enabled - using SQLite at {sqlite_path}")
    else:
        print(f"[DATABASE] No valid DATABASE_URL - using SQLite at {sqlite_path}")
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
    _pg_connect_args = {}
    # psycopg2 (default for postgresql://); asyncpg uses different args - skip timeout there
    if DATABASE_URL.startswith("postgresql") and "+asyncpg" not in DATABASE_URL:
        _pg_connect_args["connect_timeout"] = _pg_connect_timeout
    _pg_engine_kw = dict(
        poolclass=NullPool,
        echo=False,
        pool_pre_ping=True,
    )
    if _pg_connect_args:
        _pg_engine_kw["connect_args"] = _pg_connect_args
    engine = create_engine(DATABASE_URL, **_pg_engine_kw)
    # Test connection; if PostgreSQL is not running or unreachable, fall back to SQLite
    try:
        with engine.connect():
            pass
    except (OperationalError, Exception) as e:
        _pg_fail_msg = str(e)
        engine.dispose()
        data_dir = root_dir / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        sqlite_path = data_dir / 'gptintermediary.sqlite3'
        DATABASE_URL = f"sqlite:///{sqlite_path.as_posix()}"
        print("[DATABASE] PostgreSQL connection failed - falling back to SQLite.")
        print(f"[DATABASE] Reason: {_pg_fail_msg}")
        print(f"[DATABASE] Using SQLite at: {sqlite_path}")
        print("[DATABASE] To use PostgreSQL: start the server, ensure the DB exists, and set DATABASE_URL in .env")
        print("[DATABASE] Or set DATABASE_USE_SQLITE=1 to skip PostgreSQL without waiting for connect.")
        engine = create_engine(
            DATABASE_URL, poolclass=NullPool, echo=False,
            connect_args={'check_same_thread': False}
        )

# So code and subprocesses that read os.environ see the URL actually in use (including SQLite fallback).
os.environ["DATABASE_URL"] = DATABASE_URL

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

