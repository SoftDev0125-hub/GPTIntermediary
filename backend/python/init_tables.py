"""
Initialize database tables
Creates tables that don't exist yet (won't modify existing tables)
"""
from database import Base, engine, init_db
from sqlalchemy import inspect, text


def initialize_tables():
    """Create tables that don't exist yet"""
    print("\n" + "="*60)
    print("  Initialize Database Tables")
    print("="*60)
    
    try:
        # Check existing tables
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        if existing_tables:
            print(f"\n[*] Found {len(existing_tables)} existing table(s):")
            for table in existing_tables:
                print(f"   - {table}")
        
        # Create all tables (SQLAlchemy will skip existing ones)
        print("\n[*] Creating missing tables...")
        init_db()
        
        # Check what tables exist now
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        
        new_tables = [t for t in all_tables if t not in existing_tables]
        
        if new_tables:
            print(f"\n[+] Created {len(new_tables)} new table(s):")
            for table in new_tables:
                print(f"   - {table}")
        else:
            print("\n[*] All tables already exist - no new tables created")
        
        print(f"\n[*] Total tables in database: {len(all_tables)}")
        print("\n" + "="*60)
        print("[+] Database initialization complete!")
        print("="*60)
        print("\nYour database is ready to use!")
        return True
        
    except Exception as e:
        print(f"\n[-] Error: {e}")
        print("\nPlease check:")
        print("  1. Database connection is working")
        print("  2. You have CREATE TABLE permissions")
        return False


if __name__ == "__main__":
    initialize_tables()

