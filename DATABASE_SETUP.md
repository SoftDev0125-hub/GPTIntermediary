# 🗄️ PostgreSQL Database Setup with Supabase

This guide will help you set up PostgreSQL database integration for GPTIntermediary using Supabase.

## 📋 Table of Contents

1. [Create Supabase Account](#1-create-supabase-account)
2. [Get Database Connection String](#2-get-database-connection-string)
3. [Install Required Packages](#3-install-required-packages)
4. [Configure Environment Variables](#4-configure-environment-variables)
5. [Initialize Database](#5-initialize-database)
6. [Verify Setup](#6-verify-setup)
7. [Database Models](#7-database-models)
8. [API Endpoints](#8-api-endpoints)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Create Supabase Account

1. **Go to** [https://supabase.com](https://supabase.com)
2. **Click** "Start your project" or "Sign Up"
3. **Sign up** using GitHub, Google, or email
4. **Create a new project:**
   - Click "New Project"
   - Choose an organization (or create one)
   - Fill in:
     - **Project name:** `gptintermediary` (or your preferred name)
     - **Database Password:** Generate a strong password (SAVE THIS!)
     - **Region:** Choose closest to you
     - **Pricing plan:** Free tier is sufficient for testing
   - Click "Create new project"
5. **Wait** 1-2 minutes for project setup to complete

---

## 2. Get Database Connection String

1. In your Supabase project dashboard, click **Settings** (gear icon in sidebar)
2. Click **Database** in the settings menu
3. Scroll down to **Connection String** section
4. Select **Connection pooling** tab (recommended for better performance)
5. Select **URI** format
6. Copy the connection string (it looks like this):
   ```
   postgresql://postgres.xxxxxxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres
   ```
7. **Replace** `[YOUR-PASSWORD]` with the database password you created in step 1

> 💡 **Important:** Save this connection string securely! You'll need it in the next step.

---

## 3. Install Required Packages

Open a terminal in your project directory and run:

```bash
pip install -r requirements.txt
```

This will install:
- `sqlalchemy>=2.0.0` - ORM for database operations
- `psycopg2-binary>=2.9.9` - PostgreSQL adapter
- `alembic>=1.13.0` - Database migrations (optional)
- `asyncpg>=0.29.0` - Async PostgreSQL support

---

## 4. Configure Environment Variables

### Option A: Create/Update `.env` file

Create a file named `.env` in your project root (if it doesn't exist):

```bash
# Database Configuration
DATABASE_URL=postgresql://postgres.xxxxxxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres

# Other existing variables...
OPENAI_API_KEY=your_openai_api_key_here
```

### Option B: Set Environment Variable (Windows PowerShell)

```powershell
$env:DATABASE_URL="postgresql://postgres.xxx..."
```

### Option B: Set Environment Variable (Windows CMD)

```cmd
set DATABASE_URL=postgresql://postgres.xxx...
```

> ⚠️ **Security Note:** Never commit your `.env` file to Git! It should be in `.gitignore`.

---

## 5. Initialize Database

Run the database initialization script to create all tables:

```bash
python init_database.py
```

You should see output like:

```
============================================================
GPTIntermediary Database Initialization
============================================================

📊 Creating database tables...
✅ All tables created successfully!

📋 Created tables:
   - users
   - conversations
   - messages
   - user_preferences
   - telegram_sessions
   - excel_files
   - api_keys
   - system_logs

👤 Setting up default data...
✅ Created default user: admin (ID: 1)

============================================================
✅ Database initialization completed successfully!
============================================================
```

### Reset Database (Optional)

To drop all tables and recreate them (⚠️ **WARNING: This deletes ALL data!**):

```bash
python init_database.py --reset
```

---

## 6. Verify Setup

### Test 1: Check Database Health

Start your application:

```bash
python app.py
```

In another terminal or browser, test the database health endpoint:

```bash
# Using curl
curl http://localhost:8000/api/db/health

# Or visit in browser:
# http://localhost:8000/api/db/health
```

Expected response:

```json
{
  "status": "healthy",
  "message": "Database connection successful"
}
```

### Test 2: Verify in Supabase Dashboard

1. Go to your Supabase project dashboard
2. Click **Table Editor** in the sidebar
3. You should see all the tables:
   - users
   - conversations
   - messages
   - user_preferences
   - telegram_sessions
   - excel_files
   - api_keys
   - system_logs
4. Click on `users` table - you should see the default admin user

---

## 7. Database Models

The application includes the following database models:

### 👤 **User**
- User accounts and authentication
- Fields: username, email, full_name, is_active, is_admin, etc.

### 💬 **Conversation**
- Chat conversations/threads
- Fields: user_id, title, model, system_prompt, is_archived

### 📝 **Message**
- Individual messages in conversations
- Fields: conversation_id, role (user/assistant/system), content, tokens, cost

### ⚙️ **UserPreference**
- User preferences and settings
- Fields: default_model, theme, language, settings (JSON)

### 🔐 **TelegramSession**
- Telegram authentication and session data
- Fields: phone_number, session_string, telegram_user_id, is_active

### 📊 **ExcelFile**
- Excel file metadata and history
- Fields: file_name, file_path, sheet_names, last_opened

### 🔑 **APIKey**
- Store API keys for various services
- Fields: service_name, api_key, is_active

### 📋 **SystemLog**
- System logs and audit trail
- Fields: user_id, level, action, message, metadata (JSON)

---

## 8. API Endpoints

The following database API endpoints are available:

### Conversations

- **POST** `/api/db/conversations` - Create a new conversation
  ```json
  {
    "user_id": 1,
    "title": "My Chat",
    "model": "gpt-4",
    "system_prompt": "You are a helpful assistant"
  }
  ```

- **GET** `/api/db/users/{user_id}/conversations` - Get user's conversations
  - Query params: `archived=false`, `limit=50`

### Messages

- **POST** `/api/db/messages` - Save a message
  ```json
  {
    "conversation_id": 1,
    "role": "user",
    "content": "Hello!",
    "tokens": 10,
    "cost": 0.0001
  }
  ```

- **GET** `/api/db/conversations/{conversation_id}/messages` - Get conversation messages
  - Query params: `limit=100`

### Excel Files

- **POST** `/api/db/excel/log` - Log an Excel file opened
  ```json
  {
    "user_id": 1,
    "file_path": "D:/Documents/spreadsheet.xlsx",
    "file_name": "spreadsheet.xlsx",
    "sheet_names": ["Sheet1", "Sheet2"]
  }
  ```

- **GET** `/api/db/excel/recent?user_id={user_id}&limit=10` - Get recent Excel files

### Health Check

- **GET** `/api/db/health` - Check database connection status

---

## 9. Troubleshooting

### Problem: "Database modules not available"

**Solution:** Install the required packages:
```bash
pip install sqlalchemy psycopg2-binary alembic asyncpg
```

### Problem: "Connection refused" or "Could not connect to server"

**Possible causes:**
1. **Wrong connection string** - Double-check your DATABASE_URL
2. **Password incorrect** - Make sure you replaced `[YOUR-PASSWORD]` with actual password
3. **Network/firewall issues** - Check your internet connection
4. **Supabase project not ready** - Wait a few minutes after creating project

**Solution:** Test connection manually:
```bash
python -c "from database import engine; print(engine.connect())"
```

### Problem: "relation does not exist" error

**Solution:** Run the initialization script:
```bash
python init_database.py
```

### Problem: Import errors in Python

**Solution:** Make sure you're in the correct directory:
```bash
cd D:\Project\GPTIntermediary
python init_database.py
```

### Problem: "No module named 'database'"

**Solution:** Ensure `database.py` and `models.py` are in your project root directory.

### Problem: Can't see tables in Supabase

**Solution:**
1. Refresh the Supabase dashboard (F5)
2. Run `python init_database.py` again
3. Check if DATABASE_URL is correct

---

## 🎯 Next Steps

1. ✅ **Integration:** Modify your chat interface to save conversations to database
2. ✅ **User Management:** Add user registration and login functionality
3. ✅ **History:** Display chat history from database
4. ✅ **Search:** Add search functionality for conversations and messages
5. ✅ **Analytics:** Track usage statistics (tokens, costs, etc.)
6. ✅ **Backup:** Set up automated backups in Supabase dashboard

---

## 📚 Additional Resources

- **Supabase Documentation:** https://supabase.com/docs
- **SQLAlchemy Documentation:** https://docs.sqlalchemy.org/
- **FastAPI Database Tutorial:** https://fastapi.tiangolo.com/tutorial/sql-databases/
- **Python psycopg2 Guide:** https://www.psycopg.org/docs/

---

## 🔒 Security Best Practices

1. ✅ **Never commit `.env` file** - Keep credentials secure
2. ✅ **Use environment variables** - Don't hardcode passwords
3. ✅ **Enable Row Level Security (RLS)** in Supabase for production
4. ✅ **Encrypt sensitive data** - Use encryption for API keys and session strings
5. ✅ **Regular backups** - Enable automatic backups in Supabase
6. ✅ **Use connection pooling** - Already configured in `database.py`
7. ✅ **Monitor usage** - Check Supabase dashboard for performance

---

## ✅ Checklist

- [ ] Created Supabase account
- [ ] Created new project in Supabase
- [ ] Copied database connection string
- [ ] Replaced password in connection string
- [ ] Installed required packages (`pip install -r requirements.txt`)
- [ ] Created/updated `.env` file with `DATABASE_URL`
- [ ] Ran `python init_database.py`
- [ ] Verified tables in Supabase dashboard
- [ ] Tested `/api/db/health` endpoint
- [ ] Tested creating a conversation via API

---

**Need help?** Check the [Troubleshooting](#9-troubleshooting) section or open an issue on GitHub.

**Happy coding! 🚀**

