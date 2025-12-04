# ChatGPT Backend Broker

A scalable Python backend service that enables ChatGPT to perform email operations and launch applications **using the email account logged into ChatGPT**. This service acts as a broker between ChatGPT and your system.

## Features

- 📧 **Email Management via User's Gmail Account**
  - Send emails using the ChatGPT user's Gmail account
  - Retrieve unread emails from the user's inbox
  - Reply to emails from the user's account
  - **No separate OAuth flow needed** - uses credentials from ChatGPT
  
- 🚀 **Application Launcher**
  - Launch applications on Windows, macOS, and Linux
  - Support for common apps (Chrome, VS Code, Notepad, etc.)
  
- 🔌 **ChatGPT Integration**
  - Function calling definitions for seamless ChatGPT integration
  - RESTful API endpoints
  - Operates on the user's email account logged into ChatGPT
  
- 📊 **Scalable Architecture**
  - Built with FastAPI for high performance
  - Async/await support
  - Clean separation of concerns

## Prerequisites

- Python 3.8 or higher
- Google Cloud Platform project with Gmail API enabled
- OAuth 2.0 Client ID and Secret (for ChatGPT to authenticate users)

## How It Works

1. **User authenticates with Gmail in ChatGPT** - The user logs into their Gmail account through ChatGPT
2. **ChatGPT receives OAuth tokens** - ChatGPT gets the user's access token and refresh token
3. **ChatGPT calls this backend** - When the user requests an email operation, ChatGPT calls this API with the user's tokens
4. **Backend performs operation** - This service uses the provided tokens to access the user's Gmail account
5. **Results returned to ChatGPT** - The operation results are sent back to ChatGPT and displayed to the user

## Setup Instructions

### 1. Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Gmail API" and enable it
4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Configure OAuth consent screen if needed
   - Choose application type (Web application for ChatGPT integration)
   - Add authorized redirect URIs for ChatGPT
   - Save the **Client ID** and **Client Secret**

### 2. Install Dependencies

```powershell
# Create a virtual environment (recommended)
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install required packages
pip install -r requirements.txt
```

### 3. Configure Environment

```powershell
# Copy the example environment file
Copy-Item .env.example .env

# Edit .env and add your Google OAuth credentials
# GOOGLE_CLIENT_ID=your_client_id_here
# GOOGLE_CLIENT_SECRET=your_client_secret_here
```

### 4. Run the Application

```powershell
# Start the FastAPI server
python main.py
```

The server will start at `http://localhost:8000`

## API Endpoints

### Email Operations

**Important:** All email endpoints now require user credentials from ChatGPT's OAuth flow.

#### Send Email
```http
POST /api/email/send
Content-Type: application/json

{
  "user_credentials": {
    "access_token": "user_oauth_access_token_from_chatgpt",
    "refresh_token": "user_oauth_refresh_token",
    "email": "user@gmail.com"
  },
  "to": "recipient@gmail.com",
  "subject": "Hello from ChatGPT",
  "body": "This is the email content"
}
```

#### Get Unread Emails
```http
POST /api/email/unread
Content-Type: application/json

{
  "user_credentials": {
    "access_token": "user_oauth_access_token_from_chatgpt",
    "refresh_token": "user_oauth_refresh_token"
  },
  "limit": 10
}
```

#### Reply to Email
```http
POST /api/email/reply
Content-Type: application/json

{
  "user_credentials": {
    "access_token": "user_oauth_access_token_from_chatgpt",
    "refresh_token": "user_oauth_refresh_token"
  },
  "sender_email": "sender@gmail.com",
  "body": "Thank you for your email!"
}
```

### Application Launcher

#### Launch App
```http
POST /api/app/launch
Content-Type: application/json

{
  "app_name": "notepad",
  "args": []
}
```

Common app names:
- Windows: `notepad`, `calc`, `chrome`, `vscode`, `excel`, `word`
- macOS: `Safari`, `Chrome`, `TextEdit`
- Linux: `firefox`, `gedit`, `nautilus`

### ChatGPT Functions

#### Get Function Definitions
```http
GET /api/chatgpt/functions
```

Returns OpenAI-compatible function definitions for ChatGPT integration.

## ChatGPT Integration

This service is designed to work with ChatGPT's function calling feature, **using the email account that the user has logged into ChatGPT**.

### How It Works:

1. **User logs into Gmail via ChatGPT** - User authenticates their Gmail account in ChatGPT
2. **ChatGPT receives OAuth tokens** - ChatGPT gets access_token and refresh_token for the user
3. **User makes requests** - User asks ChatGPT to perform email operations
4. **ChatGPT calls your API** - ChatGPT includes the user's OAuth tokens in the API call
5. **Backend uses user's account** - This service performs operations on the user's Gmail account
6. **Results returned** - Email operation results are sent back to ChatGPT and shown to the user

### Example ChatGPT Conversation:
```
User: Send an email to john@example.com saying "Meeting at 3 PM"
ChatGPT: [Calls send_email function with user's OAuth tokens]
System: Email sent successfully from your account!

User: Show me my unread emails
ChatGPT: [Calls get_unread_emails function with user's OAuth tokens]
System: You have 5 unread emails:
  1. From: boss@company.com - Subject: Q4 Report
  2. From: friend@gmail.com - Subject: Weekend plans
  ...

User: Reply to the email from my boss saying "I'll have it ready by Friday"
ChatGPT: [Calls reply_to_email function with user's OAuth tokens]
System: Reply sent successfully from your account!

User: Launch Chrome
ChatGPT: [Calls launch_app function]
System: Chrome launched successfully!
```

### Integration Notes:

- **No separate authentication required** - Uses the user's ChatGPT-authenticated Gmail account
- **Secure** - OAuth tokens are passed directly from ChatGPT, never stored by this service
- **User-specific** - Each request operates on the specific user's email account
- **Scalable** - Can handle multiple users simultaneously, each with their own credentials

## Project Structure

```
GPTIntermediary/
├── main.py                 # FastAPI application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .gitignore            # Git ignore rules
├── credentials.json      # Gmail API credentials (not in git)
├── token.json           # Gmail API token (generated, not in git)
├── models/
│   ├── __init__.py
│   └── schemas.py       # Pydantic models for request/response
├── services/
│   ├── __init__.py
│   ├── email_service.py # Gmail API operations
│   └── app_launcher.py  # Application launching logic
├── config/
│   ├── __init__.py
│   └── chatgpt_functions.py # ChatGPT function definitions
└── .github/
    └── copilot-instructions.md
```

## Security Considerations

- **OAuth tokens are transient** - Tokens are passed per-request and not stored by the backend
- **User-specific operations** - Each user's tokens only access their own Gmail account
- Keep your `.env` file secure with your Google OAuth Client ID and Secret
- Use environment-specific configurations for production
- Consider implementing rate limiting for production use
- Restrict CORS origins in production
- **Never log or store user access tokens**
- Validate token expiration and handle refresh tokens securely

## Troubleshooting

### Gmail API Authentication Issues
- Ensure your Google Cloud project has Gmail API enabled
- Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set in `.env`
- Check that OAuth consent screen is properly configured
- Ensure ChatGPT is providing valid access tokens

### Application Launch Issues
- Verify the application name or path is correct
- Check if the application is installed on your system
- On Windows, some apps may require full paths

## License

This project is open source and available for personal and commercial use.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.
