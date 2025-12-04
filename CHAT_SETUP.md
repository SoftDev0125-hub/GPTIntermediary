# ChatGPT Assistant - Quick Start Guide

## 🎉 You now have a ChatGPT-like interface with email & app control!

### Setup Instructions:

#### 1. Install Additional Dependencies
```powershell
pip install -r requirements.txt
```

#### 2. Get Your OpenAI API Key
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Copy the key and add it to your `.env` file:
   ```
   OPENAI_API_KEY=sk-your-actual-key-here
   ```

#### 3. Start Both Servers

**Terminal 1 - Backend Server:**
```powershell
python main.py
```
This runs on http://localhost:8000

**Terminal 2 - Chat Server:**
```powershell
python chat_server.py
```
This runs on http://localhost:5000

#### 4. Open the Chat Interface
Simply open `chat_interface.html` in your web browser:
```powershell
start chat_interface.html
```

### 🎯 What You Can Do:

**App Launching:**
- "Open Notepad"
- "Launch Chrome"
- "Open Calculator"
- "Start VS Code"

**Email Management (requires real OAuth tokens):**
- "Show me my unread emails"
- "Send an email to john@example.com saying hello"
- "Reply to the email from boss@company.com"

### 📁 Architecture:

```
┌─────────────────┐
│  Browser        │
│  (HTML/JS)      │ ← You interact here
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Chat Server    │
│  (port 5000)    │ ← Connects to OpenAI
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Backend API    │
│  (port 8000)    │ ← Executes actions
└─────────────────┘
```

### 🔧 Troubleshooting:

**"OpenAI API key not configured"**
- Add your OpenAI API key to `.env` file

**"Chat server not running"**
- Make sure `python chat_server.py` is running

**"Connection error"**
- Ensure backend is running: `python main.py`

### 💡 Tips:

- The chat interface works locally on your computer
- App launching works immediately
- Email features need real Gmail OAuth tokens (currently mocked)
- You can customize the UI by editing `chat_interface.html`
- Add more apps in `services/app_launcher.py`

Enjoy your AI-powered assistant! 🚀
