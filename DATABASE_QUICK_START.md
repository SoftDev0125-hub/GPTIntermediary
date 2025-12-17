# 🚀 Database Quick Start Guide

## 📦 What Was Added

### New Files Created:
1. **`database.py`** - Database configuration and session management
2. **`models.py`** - Database models (User, Conversation, Message, etc.)
3. **`init_database.py`** - Database initialization script
4. **`DATABASE_SETUP.md`** - Complete setup guide with Supabase
5. **`DATABASE_QUICK_START.md`** - This file (quick reference)

### Updated Files:
1. **`requirements.txt`** - Added database packages
2. **`main.py`** - Added database initialization and API endpoints

---

## ⚡ Quick Start (3 Steps)

### Step 1: Set up Supabase

1. Go to https://supabase.com and create account
2. Create new project (save the password!)
3. Get connection string from: Settings → Database → Connection String (URI)
4. Copy the connection pooling URI

### Step 2: Configure Environment

Add to your `.env` file:

```env
DATABASE_URL=postgresql://postgres.xxx:[PASSWORD]@xxx.pooler.supabase.com:5432/postgres
```

### Step 3: Initialize Database

```bash
python init_database.py
```

Done! ✅

---

## 📊 Database Models

| Model | Purpose | Key Fields |
|-------|---------|------------|
| **User** | User accounts | username, email, is_admin |
| **Conversation** | Chat threads | user_id, title, model |
| **Message** | Chat messages | conversation_id, role, content |
| **UserPreference** | User settings | default_model, theme, language |
| **TelegramSession** | Telegram auth | phone_number, session_string |
| **ExcelFile** | File history | file_path, sheet_names, last_opened |
| **APIKey** | Service keys | service_name, api_key |
| **SystemLog** | Audit trail | level, action, message |

---

## 🔗 API Endpoints

### Health Check
```bash
GET http://localhost:8000/api/db/health
```

### Create Conversation
```bash
POST http://localhost:8000/api/db/conversations
{
  "user_id": 1,
  "title": "My Chat",
  "model": "gpt-4"
}
```

### Save Message
```bash
POST http://localhost:8000/api/db/messages
{
  "conversation_id": 1,
  "role": "user",
  "content": "Hello!"
}
```

### Get Conversation History
```bash
GET http://localhost:8000/api/db/conversations/1/messages
```

### Get User Conversations
```bash
GET http://localhost:8000/api/db/users/1/conversations
```

### Log Excel File
```bash
POST http://localhost:8000/api/db/excel/log
{
  "user_id": 1,
  "file_path": "D:/file.xlsx",
  "file_name": "file.xlsx",
  "sheet_names": ["Sheet1"]
}
```

### Get Recent Excel Files
```bash
GET http://localhost:8000/api/db/excel/recent?user_id=1&limit=10
```

---

## 🛠️ Common Commands

### Initialize Database
```bash
python init_database.py
```

### Reset Database (⚠️ Deletes all data!)
```bash
python init_database.py --reset
```

### Test Database Connection
```bash
python -c "from database import engine; print(engine.connect())"
```

### Start Application
```bash
python app.py
```

---

## 📚 Documentation

- **Full Setup Guide:** See `DATABASE_SETUP.md`
- **Supabase Docs:** https://supabase.com/docs
- **SQLAlchemy Docs:** https://docs.sqlalchemy.org/

---

## ❓ Troubleshooting

### "Database modules not available"
```bash
python -m pip install sqlalchemy psycopg2-binary alembic asyncpg
```

### "Connection refused"
- Check your `DATABASE_URL` in `.env`
- Verify password is correct
- Confirm Supabase project is running

### "relation does not exist"
```bash
python init_database.py
```

---

## 🎯 Next Steps

1. ✅ Packages installed
2. ✅ Database models created
3. ✅ API endpoints ready
4. 🔲 Set up Supabase account
5. 🔲 Configure DATABASE_URL
6. 🔲 Run init_database.py
7. 🔲 Integrate with your chat interface

---

**Ready to start?** Follow the 3 steps above or see `DATABASE_SETUP.md` for detailed instructions!

