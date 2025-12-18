"""
Connect to existing PostgreSQL database
Configures connection to gptintermediarydb database
"""
import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text


def configure_connection():
    """Configure connection to existing database"""
    print("\n" + "="*60)
    print("  Connect to Existing PostgreSQL Database")
    print("="*60)
    
    print("\n[*] You have database: gptintermediarydb")
    print("[*] Let's configure the connection...\n")
    
    # Get connection details
    host = input("Host [localhost]: ").strip() or "localhost"
    port = input("Port [5432]: ").strip() or "5432"
    username = input("Username [postgres]: ").strip() or "postgres"
    password = input("Password: ").strip()
    
    if not password:
        print("[-] Password is required!")
        return False
    
    db_name = "gptintermediarydb"  # Your existing database
    
    # URL-encode credentials
    username_encoded = quote_plus(username)
    password_encoded = quote_plus(password)
    
    # Test connection
    print(f"\n[*] Testing connection to database '{db_name}'...")
    database_url = f"postgresql://{username_encoded}:{password_encoded}@{host}:{port}/{db_name}"
    
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"[+] Connected successfully!")
            print(f"[*] PostgreSQL version: {version.split(',')[0]}")
            
            # Check if database exists
            result = conn.execute(text("SELECT current_database();"))
            current_db = result.fetchone()[0]
            print(f"[*] Connected to database: {current_db}")
            
            # List existing tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """))
            tables = [row[0] for row in result.fetchall()]
            
            if tables:
                print(f"\n[*] Existing tables in database:")
                for table in tables:
                    print(f"   - {table}")
            else:
                print("\n[*] No tables found in database (will be created)")
            
            # Update .env file
            print(f"\n[*] Updating .env file...")
            env_content = ""
            env_file = ".env"
            
            # Read existing .env if it exists
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if not line.strip().startswith('DATABASE_URL='):
                            env_content += line
            
            # Add DATABASE_URL
            env_content += f"DATABASE_URL={database_url}\n"
            
            # Write .env file
            with open(env_file, 'w', encoding='utf-8') as f:
                f.write(env_content)
            
            print(f"[+] .env file updated!")
            print(f"\n[*] Connection string saved:")
            print(f"    DATABASE_URL=postgresql://{username}:****@{host}:{port}/{db_name}")
            
            print("\n" + "="*60)
            print("[+] Configuration complete!")
            print("="*60)
            print("\nNext steps:")
            print("  1. python test_connection.py  - Test connection")
            print("  2. python init_tables.py      - Create missing tables")
            print("  3. python main.py             - Start your app")
            print()
            
            return True
            
    except Exception as e:
        print(f"\n[-] Connection failed: {e}")
        print("\nPlease check:")
        print("  1. PostgreSQL server is running")
        print("  2. Database 'gptintermediarydb' exists")
        print("  3. Username and password are correct")
        print("  4. Host and port are correct")
        print("  5. You have permission to access the database")
        return False


if __name__ == "__main__":
    try:
        success = configure_connection()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[-] Configuration cancelled")
        exit(1)

