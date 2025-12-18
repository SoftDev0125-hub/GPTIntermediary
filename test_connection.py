"""
Test database connection to existing gptintermediarydb database
"""
from database import engine, DATABASE_URL
from sqlalchemy import inspect, text


def test_connection():
    """Test connection to existing database"""
    print("\n" + "="*60)
    print("  Test Database Connection")
    print("="*60)
    
    db_display = DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL
    print(f"\n[*] Database URL: {db_display}")
    
    try:
        with engine.connect() as conn:
            # Test connection
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"[+] Connected successfully!")
            print(f"[*] PostgreSQL version: {version.split(',')[0]}")
            
            # Get database name
            result = conn.execute(text("SELECT current_database();"))
            db_name = result.fetchone()[0]
            print(f"[*] Database: {db_name}")
            
            # Get database size
            result = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()));"))
            size = result.fetchone()[0]
            print(f"[*] Database size: {size}")
            
            # List existing tables
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if tables:
                print(f"\n[*] Existing tables ({len(tables)}):")
                for i, table in enumerate(tables, 1):
                    # Get row count
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.fetchone()[0]
                        print(f"   {i}. {table:<25} ({count} rows)")
                    except:
                        print(f"   {i}. {table}")
            else:
                print("\n[*] No tables found in database")
            
            print("\n" + "="*60)
            print("[+] Connection test successful!")
            print("="*60)
            return True
            
    except Exception as e:
        print(f"\n[-] Connection failed: {e}")
        print("\nPlease check:")
        print("  1. PostgreSQL server is running")
        print("  2. .env file has correct DATABASE_URL")
        print("  3. Username and password are correct")
        print("  4. Database 'gptintermediarydb' exists")
        return False


if __name__ == "__main__":
    test_connection()

