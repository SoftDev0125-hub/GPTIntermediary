"""
One-time migration: allow multiple Gmail accounts per user.

- Drops the unique constraint on gmail_info.user_id (if present)
- Adds is_primary and account_label columns if missing
- Sets is_primary = true for all existing rows (so current single account stays primary)

Run from backend/python: python migrate_gmail_multi_account.py
Uses DATABASE_URL from environment or .env.
"""
import os
import sys
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent.parent
_env = _root / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

def run():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        print("DATABASE_URL not set. Skipping migration.")
        return
    if db_url.startswith("sqlite"):
        # SQLite: no named unique constraint to drop; just add columns
        import sqlite3
        db_path = db_url.replace("sqlite:///", "")
        if not Path(db_path).exists():
            print("SQLite DB not found. Run the app first to create tables.")
            return
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(gmail_info)")
            cols = {row[1] for row in cur.fetchall()}
            if "is_primary" not in cols:
                cur.execute("ALTER TABLE gmail_info ADD COLUMN is_primary BOOLEAN DEFAULT 1")
                print("Added is_primary column (SQLite).")
            if "account_label" not in cols:
                cur.execute("ALTER TABLE gmail_info ADD COLUMN account_label VARCHAR(100)")
                print("Added account_label column (SQLite).")
            cur.execute("UPDATE gmail_info SET is_primary = 1 WHERE is_primary IS NULL")
            conn.commit()
            print("SQLite migration done.")
        finally:
            conn.close()
        return

    # PostgreSQL
    try:
        import psycopg2
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            dbname=parsed.path.lstrip("/").split("?")[0],
            user=parsed.username,
            password=parsed.password,
        )
        conn.autocommit = False
        cur = conn.cursor()
        try:
            # Find unique constraint on user_id (e.g. gmail_info_user_id_key)
            cur.execute("""
                SELECT conname FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                WHERE t.relname = 'gmail_info' AND c.contype = 'u'
            """)
            for (name,) in cur.fetchall():
                if "user_id" in (name or ""):
                    cur.execute(f"ALTER TABLE gmail_info DROP CONSTRAINT IF EXISTS {name}")
                    print(f"Dropped constraint: {name}")
                    break
            # Add columns if not exist (PostgreSQL 9.5+)
            cur.execute("""
                ALTER TABLE gmail_info
                ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT true
            """)
            cur.execute("""
                ALTER TABLE gmail_info
                ADD COLUMN IF NOT EXISTS account_label VARCHAR(100)
            """)
            cur.execute("UPDATE gmail_info SET is_primary = true WHERE is_primary IS NULL")
            conn.commit()
            print("PostgreSQL migration done.")
        except Exception as e:
            conn.rollback()
            print(f"Migration error: {e}")
            raise
        finally:
            cur.close()
            conn.close()
    except ImportError:
        print("psycopg2 not installed. For PostgreSQL run: pip install psycopg2-binary")
        sys.exit(1)

if __name__ == "__main__":
    run()
