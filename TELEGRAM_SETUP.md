# Telegram Integration Setup Guide

This guide will help you set up Telegram integration for the GPTIntermediary application.

## Prerequisites

1. A Telegram account
2. Python 3.8 or higher
3. Internet connection

## Step 1: Get Telegram API Credentials

To use Telegram's API, you need to obtain API credentials from Telegram:

1. **Visit the Telegram API Development Platform:**
   - Go to https://my.telegram.org/apps
   - Log in with your phone number

2. **Create a New Application:**
   - Click "Create application" or use an existing one
   - Fill in the required information:
     - **App title:** GPTIntermediary (or any name you prefer)
     - **Short name:** GPTIntermediary (or any short name)
     - **Platform:** Desktop
     - **Description:** Optional description

3. **Get Your Credentials:**
   - After creating the app, you'll see:
     - **api_id:** A numeric ID (e.g., 12345678)
     - **api_hash:** A string hash (e.g., abcdef1234567890abcdef1234567890)
   - **Save these credentials** - you'll need them for the next step

## Step 2: Configure Environment Variables

1. **Open the `.env` file** in the project root directory

2. **Add the following variables:**
   ```env
   TELEGRAM_API_ID=your_api_id_here
   TELEGRAM_API_HASH=your_api_hash_here
   TELEGRAM_PHONE_NUMBER=your_phone_number_here
   ```

   Replace:
   - `your_api_id_here` with your actual API ID (numeric)
   - `your_api_hash_here` with your actual API hash (string)
   - `your_phone_number_here` with your phone number in international format (e.g., +1234567890)

   Example:
   ```env
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   TELEGRAM_PHONE_NUMBER=+1234567890
   ```

## Step 3: Install Dependencies

Install the required Python package:

```bash
python -m pip install telethon
```

Or if you're installing all requirements:

```bash
python -m pip install -r requirements.txt
```

## Step 4: First-Time Authentication

When you first run the application with Telegram integration:

1. **Start the application:**
   ```bash
   python app.py
   ```

2. **Authentication Process:**
   - The first time you use Telegram, you'll need to authenticate
   - The application will prompt you for:
     - **Phone number:** Enter your Telegram phone number (with country code, e.g., +1234567890)
     - **Verification code:** Telegram will send you a code via Telegram (not SMS). Check your Telegram app for the code
     - **Password (if 2FA enabled):** If you have two-factor authentication enabled, enter your password

3. **Session Storage:**
   - After successful authentication, a session file will be created in the `telegram_session/` directory
   - This session file allows the app to stay logged in without re-authenticating
   - **Keep this session file secure** - it contains your authentication credentials

## Step 5: Using Telegram Integration

1. **Open the application** and navigate to the **Telegram** tab

2. **Click the "SHOW" button** to load your Telegram messages

3. **View Messages:**
   - Messages from all your chats will be displayed
   - Click on any message to see full details
   - The interface shows:
     - Sender name/ID
     - Message content
     - Timestamp
     - Chat name

## Troubleshooting

### Issue: "Telethon not installed"
**Solution:** Install Telethon:
```bash
python -m pip install telethon
```

### Issue: "Telegram API credentials not configured"
**Solution:** Make sure you've added `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` to your `.env` file

### Issue: "Telegram client not authorized"
**Solution:** 
- Delete the session file in `telegram_session/` directory
- Restart the app and authenticate again

### Issue: "Connection timeout" or "Network error"
**Solution:**
- Check your internet connection
- Make sure Telegram is not blocked by your firewall
- Try again after a few moments

### Issue: "Phone number invalid"
**Solution:**
- Make sure you're using the international format (e.g., +1234567890)
- Include the country code (e.g., +1 for US, +44 for UK)

## Security Notes

1. **Keep your API credentials secure:**
   - Never share your `api_id` and `api_hash`
   - Don't commit them to version control
   - Keep your `.env` file private

2. **Protect your session file:**
   - The `telegram_session/` directory contains authentication data
   - Keep it secure and don't share it
   - If compromised, delete it and re-authenticate

3. **Two-Factor Authentication:**
   - If you have 2FA enabled on Telegram, you'll need to enter your password during authentication
   - This is a one-time process (unless you delete the session file)

## Additional Information

- **Telethon Documentation:** https://docs.telethon.dev/
- **Telegram API:** https://core.telegram.org/api
- **Rate Limits:** Telegram has rate limits on API calls. The app respects these limits automatically.

## Support

If you encounter any issues:
1. Check the application logs for error messages
2. Verify your `.env` file configuration
3. Ensure all dependencies are installed
4. Try re-authenticating by deleting the session file

