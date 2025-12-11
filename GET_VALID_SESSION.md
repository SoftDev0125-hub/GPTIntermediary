# How to Get a Valid Telegram Session

## Quick Guide

To get a valid Telegram session, you need to complete the authentication process. Here's how:

## Step 1: Wait for Rate Limit (If Applicable)

If you see the error "You have tried logging in too many times":
- **Wait 24 hours** from your last authentication attempt
- Telegram will then allow new verification code requests

## Step 2: Prepare for Authentication

1. **Stop your backend server** (if running):
   - Find the terminal where `main.py` is running
   - Press `Ctrl+C` to stop it

2. **Delete the invalid session file**:
   ```powershell
   Remove-Item -Force telegram_session\telegram_session.session
   ```

## Step 3: Run Authentication Script

Run the authentication script:
```powershell
python authenticate_telegram.py
```

## Step 4: Complete Authentication

Follow the prompts:

### 4.1 Enter Phone Number
- If you have `TELEGRAM_PHONE_NUMBER` in your `.env` file, it will use that
- Otherwise, enter your phone number with country code (e.g., `+380953543305`)

### 4.2 Enter Verification Code
- Check your Telegram app (on your phone) for a verification code
- Enter the code when prompted
- **Important**: Enter it correctly on the first try to avoid rate limits

### 4.3 Enter 2FA Password (If You Have It)
- If your account has Two-Step Verification enabled, you'll be prompted for your 2FA password
- This is the password you set in Telegram Settings → Privacy and Security → Two-Step Verification
- **Note**: This is different from your Telegram account password
- You'll have 3 attempts to enter it correctly

## Step 5: Verify Authentication

After successful authentication, you should see:
```
✓ Authentication successful!

============================================================
Authentication complete! You can now use Telegram in the app.
============================================================
```

A valid session file will be created at:
```
telegram_session/telegram_session.session
```

## Step 6: Restart Your Backend Server

1. Start your backend server:
   ```powershell
   python main.py
   ```

2. Open the web interface

3. Go to the Telegram tab

4. Click "Refresh"

5. Your Telegram messages should now appear!

## Troubleshooting

### "You have tried logging in too many times"
- **Solution**: Wait 24 hours, then try again
- **Prevention**: Enter verification codes correctly on the first try

### "Two-steps verification is enabled and a password is required"
- **Solution**: Enter your 2FA password
- **If you forgot it**: Go to Telegram Settings → Privacy and Security → Two-Step Verification → Forgot Password

### "Invalid verification code"
- **Solution**: Make sure you're entering the code from your Telegram app (not SMS)
- Check that the code hasn't expired (codes expire after a few minutes)

### Session file still invalid after authentication
- **Solution**: 
  1. Stop the server
  2. Delete the session file again
  3. Run authentication again
  4. Make sure to complete ALL steps (phone, code, and 2FA if needed)

## What is a Valid Session?

A valid Telegram session file contains:
- Your authentication credentials
- Encrypted session data
- Authorization tokens

This allows the app to:
- Connect to Telegram without re-authenticating
- Fetch your messages
- Access your chats

**Important**: Keep your session file secure - it contains your authentication credentials!

## Session File Location

The session file is stored at:
```
telegram_session/telegram_session.session
```

This file is automatically created after successful authentication.

