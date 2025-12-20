# WhatsApp Node.js Backend Setup

This guide explains how to set up and use the WhatsApp Node.js backend for QR code authentication.

## Overview

The WhatsApp functionality now uses a Node.js backend server (running on port 3000) instead of the Python backend. This provides better QR code generation and session management using the `whatsapp-web.js` library.

## Architecture

```
┌─────────────────┐
│  Frontend       │
│  (HTML/JS)      │ ← You interact here
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Node.js Server │
│  (port 3000)    │ ← WhatsApp QR code & operations
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  whatsapp-web.js│
│  (Puppeteer)    │ ← Interacts with WhatsApp Web
└─────────────────┘
```

## Setup Instructions

### 1. Install Dependencies

The required Node.js packages are already installed in `node_modules`. If you need to reinstall:

```powershell
npm install
```

Required packages:
- `whatsapp-web.js` - WhatsApp Web API library
- `qrcode` - QR code generation
- `express` - Web server
- `cors` - CORS middleware

### 2. Start the Node.js WhatsApp Server

**Terminal 1 - WhatsApp Node.js Server:**
```powershell
node whatsapp_server.js
```

Or using npm:
```powershell
npm start
```

This runs on http://localhost:3000

### 3. Start Other Servers (if needed)

**Terminal 2 - Python Backend Server:**
```powershell
python main.py
```
This runs on http://localhost:8000 (for other services like email, Word, Excel, etc.)

**Terminal 3 - Chat Server:**
```powershell
python chat_server.py
```
This runs on http://localhost:5000 (for ChatGPT functionality)

### 4. Open the Chat Interface

Simply open `chat_interface.html` in your web browser:
```powershell
start chat_interface.html
```

## How It Works

### First Time Authentication (QR Code Scan)

1. **Click on WhatsApp Tab**: When you click the WhatsApp tab, the frontend calls `/api/whatsapp/initialize` on the Node.js server.

2. **QR Code Generation**: The Node.js server initializes the WhatsApp client using `whatsapp-web.js`. If no session exists, it generates a QR code.

3. **Display QR Code**: The QR code is displayed in the WhatsApp tab as a base64-encoded image.

4. **Scan QR Code**: Open WhatsApp on your phone, go to Settings > Linked Devices, and scan the QR code displayed in the app.

5. **Authentication Complete**: Once scanned, the WhatsApp client detects authentication and saves the session automatically.

6. **Session Persistence**: The session is saved to `whatsapp_session_node/.wwebjs_auth/` directory using LocalAuth strategy.

### Subsequent App Launches (Auto-Connect)

1. **Session Detection**: When the app starts and you click the WhatsApp tab, the server checks for an existing session in `whatsapp_session_node/.wwebjs_auth/`.

2. **Auto-Connect**: If a valid session exists, the WhatsApp client automatically restores the connection without requiring a QR code scan.

3. **Connected State**: The app shows "Connected" status and you can immediately use WhatsApp features.

## API Endpoints

### `GET /api/whatsapp/status`
Check WhatsApp connection status.

**Response:**
```json
{
  "success": true,
  "is_connected": true,
  "is_authenticated": true,
  "has_session": true,
  "message": "Connected to WhatsApp"
}
```

### `GET /api/whatsapp/qr-code?force_refresh=true`
Get QR code for authentication.

**Query Parameters:**
- `force_refresh` (optional): Set to `true` to force a new QR code

**Response:**
```json
{
  "success": true,
  "qr_code": "data:image/png;base64,iVBORw0KGgo...",
  "is_authenticated": false,
  "message": "Scan the QR code with WhatsApp to connect"
}
```

### `POST /api/whatsapp/initialize`
Initialize WhatsApp service (lazy initialization).

**Response:**
```json
{
  "success": true,
  "message": "WhatsApp service initialized. QR code authentication required."
}
```

### `POST /api/whatsapp/contacts`
Get WhatsApp contacts/chats.

**Request Body:**
```json
{
  "limit": 100
}
```

**Response:**
```json
{
  "success": true,
  "count": 10,
  "contacts": [
    {
      "contact_id": "1234567890@c.us",
      "name": "John Doe",
      "is_group": false,
      "last_message": "Hello!",
      "last_message_time": 1234567890,
      "unread_count": 0
    }
  ]
}
```

### `POST /api/whatsapp/send`
Send a WhatsApp message.

**Request Body:**
```json
{
  "contact_id": "1234567890@c.us",
  "text": "Hello, this is a test message"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Message sent successfully",
  "message_id": "3EB0123456789ABCDEF"
}
```

## Session Management

### Session Storage

Sessions are stored in:
```
whatsapp_session_node/
  └── .wwebjs_auth/
      └── (session files)
```

### Session Persistence

- **LocalAuth Strategy**: Uses `whatsapp-web.js` LocalAuth to automatically save and restore sessions
- **Automatic Save**: Session is saved automatically after successful authentication
- **Auto-Restore**: On app restart, if a valid session exists, it's automatically restored

### Session Expiration

If a session expires (e.g., logged out from phone), the app will:
1. Detect the expired session
2. Clear the old session files
3. Generate a new QR code for re-authentication

## Troubleshooting

### "QR code not available yet"
- **Cause**: The WhatsApp client is still initializing
- **Solution**: Wait a few seconds and the QR code will appear automatically

### "Session exists - connecting..."
- **Cause**: A session file exists but the client is still restoring the connection
- **Solution**: Wait for the connection to restore (usually 10-30 seconds)

### "Authentication failure"
- **Cause**: The session may have expired or been logged out
- **Solution**: The app will automatically clear the session and show a new QR code

### Server won't start
- **Check**: Make sure port 3000 is not already in use
- **Check**: Ensure all dependencies are installed (`npm install`)
- **Check**: Verify Node.js is installed (`node --version`)

### QR code doesn't appear
- **Check**: Open browser console (F12) and look for errors
- **Check**: Verify the Node.js server is running on port 3000
- **Check**: Try refreshing the QR code manually using the "Refresh QR Code" button

## Notes

- **QR Code Expiration**: WhatsApp QR codes expire after approximately 20 seconds. The app automatically refreshes them every 20 seconds until authenticated.
- **Headless Mode**: The WhatsApp client runs in headless mode (no visible browser window) for better performance.
- **Session Security**: Session files contain authentication tokens. Keep them secure and don't share them.
- **Multiple Devices**: WhatsApp Web allows multiple devices. Each session is independent.

## Ports Used

- **3000**: Node.js WhatsApp Server
- **8000**: Python Backend Server (other services)
- **5000**: Python Chat Server (ChatGPT functionality)

Make sure all three ports are available when running the full application.

