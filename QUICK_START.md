# Quick Start - PostgreSQL Integration

## Connect to Your Existing Database

Your application is now ready to connect to your existing PostgreSQL database `gptintermediarydb`.

### Step 1: Configure Connection

```bash
python connect_database.py
```

Enter your database connection details when prompted:
- Host: `localhost` (or your server IP)
- Port: `5432` (default)
- Username: Your PostgreSQL username
- Password: Your PostgreSQL password

This will save your connection string to `.env` file.

### Step 2: Test Connection

```bash
python test_connection.py
```

This verifies the connection and shows existing tables.

### Step 3: Initialize Tables (Optional)

```bash
python init_tables.py
```

This creates any missing tables (won't modify your existing `users` table).

### Step 4: Start Application

```bash
python main.py
```

The application will:
- Connect to your database automatically
- Enable authentication endpoints
- Ready for user registration and login

## What Works Now

✅ **User Registration** - `/api/auth/register`
   - Saves new users to your existing `users` table
   - Stores: name, email, hashed password, create_at

✅ **User Login** - `/api/auth/login`
   - Authenticates against existing users
   - Returns JWT token for session management

✅ **Database Integration**
   - Works with your existing table structure
   - Preserves all existing data
   - Adds new tables only if they don't exist

## File Structure

```
database.py              # Database connection and session management
db_models.py             # Database models (User, Conversation, etc.)
connect_database.py      # Interactive connection setup
test_connection.py       # Test database connectivity
init_tables.py           # Create missing tables
DATABASE_CONNECTION_GUIDE.md  # Detailed documentation
```

## Need Help?

See `DATABASE_CONNECTION_GUIDE.md` for:
- Detailed setup instructions
- Troubleshooting guide
- Manual configuration options

