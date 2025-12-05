# Gmail Setup Instructions

## First Time Setup

If you don't have a Gmail account registered in the app, you must run the OAuth authorization script first:

### Step 1: Authorize Gmail Access

Run this command from the project directory:

```bash
python get_gmail_token.py
```

This will:
1. Open your browser automatically
2. Ask you to sign in to your Gmail account
3. Ask you to grant permissions to the app
4. Save your OAuth tokens to `.env` file

### Step 2: Start the App

After authorization completes, start the app:

```bash
python app.py
```

## Troubleshooting

### "OAuth scope mismatch" Error
If you get an `invalid_scope` error when clicking "Unread Mail":
- Run `python get_gmail_token.py` again
- This time it will ask you to reauthorize with the correct scopes
- Restart the app

### "Gmail credentials not found" Error
The `.env` file is missing Gmail tokens. Run `python get_gmail_token.py` to authorize.

### Browser doesn't open automatically
- Manually copy the authorization URL from the terminal
- Paste it into your browser
- Complete the authorization process

## What Permissions Are Needed?

The app requests these Gmail permissions:
- **Read emails**: To show unread emails
- **Send emails**: To send emails from commands
- **Modify emails**: To mark emails as read/archived

These are standard Gmail API scopes required for the app to function.

## Resetting Authorization

To authorize with a different Gmail account:
1. Delete the current tokens from `.env` (or rename the file)
2. Run `python get_gmail_token.py` again
3. Sign in with the new account

