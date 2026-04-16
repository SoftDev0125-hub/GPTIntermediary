# GPT Intermediary - AI-Powered Automation Platform

A comprehensive desktop application that combines AI chat capabilities with real-time messaging integrations, document management, and system automation. Built with Python (FastAPI), Node.js, and modern web technologies.

## 🚀 Features

### 🤖 AI Chat Interface
- **OpenAI GPT Integration**: Chat with GPT-3.5/GPT-4 through a modern web interface
- **Function Calling**: AI can execute system commands, send emails, manage documents, and more
- **Conversation History**: Persistent chat history with database storage
- **Context-Aware Responses**: Intelligent context analysis for better conversations

### 📧 Email Management
- **Gmail Integration**: Send, receive, and manage emails through Gmail API
- **Dual Gmail Accounts**: Use two Gmail accounts at once (primary + second/EMAIL2 tab), each with its own Google Cloud OAuth client
- **OAuth 2.0 Authentication**: Secure authentication using Google OAuth
- **Unread Email Retrieval**: View and manage unread emails
- **Email Replies**: Quick reply functionality
- **User-Specific Operations**: Each user's emails are handled separately

### 💬 Real-Time Messaging Platforms

#### Telegram Integration
- **Telegram Bot API**: Connect via Telegram Bot API
- **Message Retrieval**: Get messages from chats and groups
- **Send Messages**: Send messages to contacts and groups
- **Session Management**: Persistent Telegram session

#### Slack Integration
- **Slack API Integration**: Connect to Slack workspaces
- **Channel Messages**: View messages from public and private channels
- **Direct Messages**: Access DM conversations
- **Send Messages**: Post messages to channels and DMs

### 📄 Document Management

#### Microsoft Word
- **Create Documents**: Create new Word documents
- **Open Documents**: Open existing Word files
- **Text Editing**: Add, format, and edit text
- **Advanced Features**:
  - Headings and paragraphs
  - Lists (bulleted and numbered)
  - Tables
  - Find and replace
  - Page setup
  - Save as HTML
- **Windows COM Automation**: Full Word application control

#### Microsoft Excel
- **Create Spreadsheets**: Create new Excel workbooks
- **Open Spreadsheets**: Open existing Excel files
- **Sheet Management**: Add, delete, and manage worksheets
- **Data Operations**: Read and write cell data
- **Save Functionality**: Save workbooks in various formats
- **Windows COM Automation**: Full Excel application control

### 🚀 Application Launcher
- **Cross-Platform Support**: Launch applications on Windows, macOS, and Linux
- **Common Apps**: Pre-configured shortcuts for popular applications
- **Custom Paths**: Launch applications from custom paths
- **Command Arguments**: Pass arguments to launched applications

### 🔐 Authentication & Security
- **User Registration**: Create user accounts with secure password hashing
- **JWT Tokens**: Secure authentication using JSON Web Tokens
- **Session Management**: Persistent user sessions
- **Password Requirements**: Enforced password security policies
- **Email Verification**: Optional email verification system

### 💾 Database Support
- **PostgreSQL**: Full PostgreSQL database support
- **SQLite**: Lightweight SQLite for development
- **User Management**: Store user accounts and sessions
- **Chat History**: Persistent conversation storage
- **Message Logging**: Track all operations and messages

### 🎨 Modern UI
- **Web-Based Interface**: Beautiful, responsive web interface
- **Tab-Based Navigation**: Easy switching between features
- **Real-Time Updates**: Live updates via WebSocket
- **Dark Theme**: Modern dark theme design
- **Responsive Design**: Works on different screen sizes

## 📋 Prerequisites

### Required Software
- **Python 3.8+**: [Download Python](https://www.python.org/downloads/)
- **Node.js 16+**: [Download Node.js](https://nodejs.org/)
- **npm**: Comes with Node.js
- **PostgreSQL** (optional): For production database
- **Microsoft Office** (optional): For Word/Excel features on Windows

### Required Accounts & APIs
- **OpenAI API Key**: [Get API Key](https://platform.openai.com/api-keys)
- **Google Cloud Project**: For Gmail API access
- **Telegram Bot Token**: [Create Bot](https://core.telegram.org/bots/tutorial)
- **Slack App** (optional): For Slack integration
## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/SoftDev0125-hub/GPTIntermediary.git
cd GPTIntermediary
```

### 2. Install Python Dependencies
```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Install Node.js Dependencies
```bash
npm install
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory:

```env
# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here

# Google OAuth (for Gmail – primary account)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Second Gmail account (optional – for EMAIL2 tab)
# GOOGLE_CLIENT_ID_2=your-second-google-client-id
# GOOGLE_CLIENT_SECRET_2=your-second-google-client-secret

# Telegram Configuration
TELEGRAM_API_ID=your-telegram-api-id
TELEGRAM_API_HASH=your-telegram-api-hash
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Database Configuration (optional)
DATABASE_URL=postgresql://user:password@localhost:5432/gptintermediary
# Or for SQLite:
# DATABASE_URL=sqlite:///./gptintermediary.db

# JWT Secret (generate a random string)
JWT_SECRET=your-random-secret-key-here

# Server Configuration
BACKEND_PORT=8000
CHAT_SERVER_PORT=5000
WHATSAPP_NODE_PORT=3000
DJANGO_PORT=8001
```

### 5. Set Up Gmail API (Optional)
Run the Gmail token setup to authorize one or two Gmail accounts. Tokens are saved to `.env`.

**Option A – From project root (Python):**
```bash
# Obtain tokens for BOTH accounts (primary then second). You will sign in twice.
python backend/python/get_gmail_token.py

# Or use the batch file (uses get_gmail_token.exe from dist if built, else Python)
run_get_gmail_token.bat
```

**Option B – Standalone exe (e.g. copied `dist` folder):**  
Put `.env` in the **same folder** as `get_gmail_token.exe`, with at least `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (and for the second account, `GOOGLE_CLIENT_ID_2` and `GOOGLE_CLIENT_SECRET_2`). Then run:
```bash
get_gmail_token.exe
```
Running with no arguments obtains tokens for **both** accounts (first Gmail → first Cloud client, second Gmail → second Cloud client). Sign in twice when prompted.

**What the script does:**
1. Opens your browser for the primary Gmail (port 8085)
2. Optionally opens again for the second Gmail (port 8086)
3. Saves `USER_ACCESS_TOKEN` / `USER_REFRESH_TOKEN` and (if used) `USER_ACCESS_TOKEN_2` / `USER_REFRESH_TOKEN_2` to `.env`

**Two Gmail accounts:** Use two OAuth 2.0 Client IDs (one per Gmail/Cloud project). Add `http://localhost:8085/` to the first client’s redirect URIs and `http://localhost:8086/` to the second client’s redirect URIs in Google Cloud Console.

### 6. Set Up Database (Optional)
```bash
# Initialize database tables
python backend/python/init_tables.py

# Or connect to existing database
python backend/python/connect_database.py
```

## 📦 Build Portable Windows App (No Python/Node install on target PC)

You can create a portable Windows bundle that runs on other PCs without installing Python or Node.js.

### Build on your development machine

```bash
python build.py
```

If the project has a `venv` folder, `build.py` automatically switches to `venv\Scripts\python.exe` so PyInstaller bundles the same libraries you installed with `pip install -r requirements.txt`. If you see `ModuleNotFoundError` inside `backend.exe` after copying the app, rebuild from a venv that has all requirements installed (or run `.\venv\Scripts\python.exe build.py` explicitly).

This runs `tools/build_exe.py` and creates:

- `dist/GPTIntermediary/GPTIntermediary.exe` (desktop launcher)
- `dist/GPTIntermediary/backend.exe`
- `dist/GPTIntermediary/chat.exe`
- `dist/GPTIntermediary/django.exe` (optional; see smaller builds below)
- bundled Node runtime in `dist/GPTIntermediary/node_runtime`
- `frontend`, `backend/node`, and `node_modules` (production-only npm install; pruned copy)

### Smaller portable builds (optional)

The portable folder is large mainly because of **multiple PyInstaller exes**, **`node_modules`**, and optionally **Puppeteer’s Chromium** and **PostgreSQL**. To shrink the bundle while keeping the chat + API stack working:

| Environment variable | Effect |
|----------------------|--------|
| `PORTABLE_INCLUDE_PUPPETEER_CHROME=1` | **Include** Puppeteer’s downloaded Chromium (large). **Default:** omitted — target PC should have **Google Chrome** (or Edge) for WhatsApp Web, or set `PUPPETEER_EXECUTABLE_PATH`. |
| `PORTABLE_SKIP_DJANGO_EXE=1` | Do not build or ship `django.exe` if you do not use the Django service. |
| `PORTABLE_SKIP_GMAIL_EXE=1` | Do not build or ship `get_gmail_token.exe` if OAuth was done on another machine. |

Example (PowerShell) before `python build.py`:

```powershell
$env:PORTABLE_SKIP_DJANGO_EXE="1"
$env:PORTABLE_SKIP_GMAIL_EXE="1"
python build.py
```

Do **not** set `POSTGRES_RUNTIME_DIR` if you want the smallest layout and are fine with **SQLite** on the target PC.

`python build.py` runs **`npm ci --omit=dev`** when `package-lock.json` exists, so your root `node_modules` is production-only after a build. Run `npm install` again locally if you still need dev-only packages for development.

### Optional: bundle PostgreSQL runtime too

If you want PostgreSQL included (portable, no install required on target PC), set an environment variable before build:

```powershell
$env:POSTGRES_RUNTIME_DIR="C:\path\to\portable-postgres"
python build.py
```

`POSTGRES_RUNTIME_DIR` must point to a folder containing `bin\pg_ctl.exe`.

When present, the app auto-starts bundled PostgreSQL on launch (default `127.0.0.1:5433`) and stops it when app closes.

#### Quick helper (auto-download portable PostgreSQL)

Use the included script to download and extract portable PostgreSQL binaries, then copy/paste the printed path:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup_portable_postgres.ps1
```

Then run:

```powershell
$env:POSTGRES_RUNTIME_DIR="C:\full\path\printed\by\script"
python build.py
```

Optional parameters:

```powershell
# Different PostgreSQL binary package version
powershell -ExecutionPolicy Bypass -File .\tools\setup_portable_postgres.ps1 -Version "16.8-1"

# Custom output folder
powershell -ExecutionPolicy Bypass -File .\tools\setup_portable_postgres.ps1 -OutputRoot "D:\portable-deps"
```

### Deploy to another computer

1. Copy the whole `dist/GPTIntermediary` folder (not only `.exe`)
2. Put `.env` in that same folder (next to `GPTIntermediary.exe`)
3. Run `GPTIntermediary.exe`

If PostgreSQL runtime is not bundled or fails to start, the backend automatically falls back to SQLite (`data/gptintermediary.sqlite3`).

## 🎯 Quick Start

### Option 1: All-in-One Launcher (Recommended)
```bash
python app.py
```

This will:
- Start the FastAPI backend server (port 8000)
- Start the chat server (port 5000)
- Start the Node.js Telegram and Slack servers (ports 3001, 3002)
- Start Django service if available (port 8001)
- Open the application in your default browser

### Option 2: Manual Start

**Terminal 1 - Backend Server:**
```bash
python backend/python/main.py
```

**Terminal 2 - Chat Server:**
```bash
python backend/python/chat_server.py
```

**Terminal 3 - Telegram/Slack (optional):**
```bash
npm run telegram   # or: node backend/node/telegram_server.js
npm run slack      # or: node backend/node/slack_server.js
```

**Terminal 4 - Django Service (Optional):**
```bash
cd backend/django_app
python manage.py runserver 8001
```

Then open `frontend/chat_interface.html` (or `http://72.62.162.44:5000/chat_interface.html`).

## 📖 Usage Guide

### AI Chat
1. Click on the **Chat** tab
2. Type your message or command
3. The AI will respond and can execute functions like:
   - "Launch Chrome"
   - "Send an email to john@example.com"
   - "Show me my unread emails"
   - "Create a Word document"

### Telegram
1. Click on the **Telegram** tab
2. Click **Refresh** to load chats
3. Select a chat to view messages
4. Send messages to contacts or groups

### Slack
1. Click on the **Slack** tab
2. Configure your Slack app credentials
3. Click **Refresh** to load channels
4. Select a channel to view messages
5. Send messages to channels or DMs

### Word Documents
1. Click on the **Word** tab
2. Create a new document or open an existing one
3. Use the editor to add and format text
4. Save your document

### Excel Spreadsheets
1. Click on the **Excel** tab
2. Create a new spreadsheet or open an existing one
3. Manage worksheets and data
4. Save your spreadsheet

### Email Management
1. Set up Gmail API credentials in `.env` (and optionally second account: `GOOGLE_CLIENT_ID_2`, `GOOGLE_CLIENT_SECRET_2`)
2. Run `run_get_gmail_token.bat` or `python backend/python/get_gmail_token.py` to authorize (one or both accounts)
3. Use the AI chat or the **EMAIL** / **EMAIL2** tabs to send and read emails:
   - "Send an email to user@example.com saying Hello"
   - "Show me my unread emails"
   - "Reply to the email from boss@company.com"

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Browser)                   │
│              chat_interface.html + styles.css           │
└───────────────┬─────────────────────────────────────────┘
                │
                ├─────────────────┬─────────────────┬──────────────┐
                │                 │                 │              │
        ┌───────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐   ┌───▼──────┐
        │  Chat Server │   │ Backend API │   │ Telegram    │   │ Django   │
        │  (Port 5000) │   │ (Port 8000) │   │ Node Server │   │ (8001)   │
        │              │   │             │   │ (Port 3000) │   │          │
        └───────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────────┘
                │                 │                 │
                ├─────────────────┴─────────────────┤
                │                                   │
        ┌───────▼────────┐                ┌────────▼────────┐
        │   OpenAI API   │                │  External APIs  │
        │   (GPT-3.5/4)  │                │  Gmail/Telegram │
        └────────────────┘                │  Slack/Telegram │
                                          └─────────────────┘
```

## 📁 Project Structure

```
GPTIntermediary/
├── app.py                      # Main application launcher
├── frontend/                    # UI (HTML/CSS)
│   ├── chat_interface.html      # Main interface
│   ├── styles.css               # Styles
│   ├── login.html               # Login UI
│   └── admin_panel.html         # Admin UI
│
├── backend/
│   ├── python/                  # Python services (FastAPI + chat server)
│   │   ├── main.py              # FastAPI backend server
│   │   ├── chat_server.py       # Chat server with OpenAI
│   │   ├── services/            # Service modules
│   │   ├── models/              # Data models
│   │   └── config/              # Configuration
│   │
│   ├── node/                    # Node.js messaging backends
│   │   ├── telegram_server.js
│   │   └── slack_server.js
│   │
│   └── django_app/              # Django service (optional)
│       ├── manage.py
│       └── djproject/
│
├── package.json                 # Node.js dependencies
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables (create this)
├── run_get_gmail_token.bat      # Run Gmail OAuth (both accounts); uses dist\get_gmail_token.exe if present
│
├── dist/                        # Optional: get_gmail_token.exe (build from backend/python/get_gmail_token.py)
├── telegram_session/           # Telegram session files
└── logs/                        # Application logs
```

## 🔌 API Endpoints

### Chat & AI
- `POST /chat` - Send chat message to AI
- `GET /api/chatgpt/functions` - Get ChatGPT function definitions

### Email
- `POST /api/email/send` - Send email via Gmail
- `POST /api/email/unread` - Get unread emails
- `POST /api/email/reply` - Reply to email

### Telegram
- `POST /api/telegram/messages` - Get Telegram messages
- `POST /api/telegram/send` - Send Telegram message

### Slack
- `POST /api/slack/messages` - Get Slack messages
- `POST /api/slack/send` - Send Slack message

### Word Documents
- `POST /api/word/create` - Create Word document
- `POST /api/word/open` - Open Word document
- `POST /api/word/add-text` - Add text to document
- `POST /api/word/format` - Format paragraph
- `POST /api/word/add-heading` - Add heading
- `POST /api/word/add-list` - Add list
- `POST /api/word/add-table` - Add table
- `POST /api/word/find-replace` - Find and replace
- `POST /api/word/save` - Save document

### Excel Spreadsheets
- `POST /api/excel/create` - Create Excel spreadsheet
- `POST /api/excel/open` - Open Excel spreadsheet
- `POST /api/excel/add-sheet` - Add worksheet
- `POST /api/excel/delete-sheet` - Delete worksheet
- `POST /api/excel/save` - Save spreadsheet

### Application Launcher
- `POST /api/app/launch` - Launch application

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `GET /api/auth/me` - Get current user info

## 🔒 Security Considerations

- **Environment Variables**: Never commit `.env` file to version control
- **API Keys**: Keep all API keys secure and rotate them regularly
- **OAuth Tokens**: Tokens are passed per-request, not stored permanently
- **Password Hashing**: Passwords are hashed using bcrypt
- **JWT Tokens**: Use strong JWT secrets in production
- **CORS**: Configure CORS properly for production
- **Rate Limiting**: Implement rate limiting for production use
- **HTTPS**: Use HTTPS in production environments

## 🐛 Troubleshooting

### Telegram Connection Issues
- **Authentication failed**: Check `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env`
- **Session expired**: Delete `telegram_session/telegram_session.session` and re-authenticate

### Email Issues
- **Gmail API errors**: Verify OAuth credentials and re-run `run_get_gmail_token.bat` or `python backend/python/get_gmail_token.py`
- **Token expired**: Refresh tokens are handled automatically
- **Second account (EMAIL2)**: Ensure `http://localhost:8086/` is in the second OAuth client’s Authorized redirect URIs in Google Cloud Console
- **Copied dist folder**: Put `.env` (with client IDs/secrets) in the same folder as `get_gmail_token.exe`; run the exe once to get tokens for both accounts

### Database Issues
- **Connection failed**: Check `DATABASE_URL` in `.env`
- **Tables not created**: Run `python init_tables.py`

### General Issues
- **Port already in use**: Stop other services using ports 5000, 8000, 3001, 3002, or 8001
- **Module not found**: Run `pip install -r requirements.txt` and `npm install`
- **OpenAI errors**: Verify `OPENAI_API_KEY` is set correctly


## 📝 Development

### Adding New Features
1. Create service in `backend/python/services/`
2. Add API endpoints in `backend/python/main.py`
3. Update `backend/python/config/chatgpt_functions.py` for AI integration
4. Add frontend UI in `frontend/chat_interface.html`
5. Update styles in `frontend/styles.css`

### Code Style
- Follow PEP 8 for Python code
- Use async/await for I/O operations
- Add type hints where possible
- Document functions and classes

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

This project is open source and available for personal and commercial use.

## 🙏 Acknowledgments

- OpenAI for GPT API
- FastAPI for the backend framework
- All contributors and users

## 📞 Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check existing documentation
- Review the codebase

---

**Made with ❤️ for automation and productivity**

