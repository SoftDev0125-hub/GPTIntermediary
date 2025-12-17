"""
Database initialization script
Run this to create all database tables and setup initial data
"""
import sys
from database import init_db, drop_all_tables, engine, Base
from models import User, Conversation, Message, UserPreference, TelegramSession, ExcelFile, APIKey, SystemLog
from sqlalchemy.orm import Session
from datetime import datetime


def create_default_user(db: Session):
    """Create a default user for testing"""
    from sqlalchemy import select
    
    # Check if user already exists
    stmt = select(User).where(User.username == "admin")
    existing_user = db.execute(stmt).scalar_one_or_none()
    
    if existing_user:
        print("✓ Default user already exists")
        return existing_user
    
    # Create default user
    default_user = User(
        username="admin",
        email="admin@example.com",
        full_name="Administrator",
        is_active=True,
        is_admin=True,
        last_login=datetime.now()
    )
    db.add(default_user)
    db.commit()
    db.refresh(default_user)
    
    # Create default preferences for user
    default_prefs = UserPreference(
        user_id=default_user.id,
        default_model="gpt-4",
        default_temperature=0.7,
        theme="light",
        language="en",
        enable_notifications=True
    )
    db.add(default_prefs)
    db.commit()
    
    print(f"✅ Created default user: {default_user.username} (ID: {default_user.id})")
    return default_user


def main():
    """Main initialization function"""
    print("=" * 60)
    print("GPTIntermediary Database Initialization")
    print("=" * 60)
    
    # Check if we should drop existing tables
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        print("\n⚠️  RESETTING DATABASE - Dropping all tables...")
        response = input("Are you sure? This will delete ALL data! (yes/no): ")
        if response.lower() == "yes":
            drop_all_tables()
            print("✅ All tables dropped")
        else:
            print("❌ Reset cancelled")
            return
    
    # Create all tables
    print("\n📊 Creating database tables...")
    try:
        init_db()
        print("✅ All tables created successfully!")
        
        # List all created tables
        print("\n📋 Created tables:")
        from sqlalchemy import inspect
        inspector = inspect(engine)
        for table_name in inspector.get_table_names():
            print(f"   - {table_name}")
        
        # Create default user
        print("\n👤 Setting up default data...")
        from database import SessionLocal
        db = SessionLocal()
        try:
            create_default_user(db)
        finally:
            db.close()
        
        print("\n" + "=" * 60)
        print("✅ Database initialization completed successfully!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("1. Update your .env file with your Supabase DATABASE_URL")
        print("2. Run: python init_database.py --reset (to reset database)")
        print("3. Start your application: python app.py")
        print()
        
    except Exception as e:
        print(f"\n❌ Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

