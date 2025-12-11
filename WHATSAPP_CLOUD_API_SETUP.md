# WhatsApp Cloud API Setup Guide

## Overview

This app now uses **WhatsApp Cloud API** (Meta's official API) instead of browser automation. This is more reliable and doesn't require Chrome/Selenium.

## Prerequisites

1. **Meta Developer Account**
   - Go to [Meta for Developers](https://developers.facebook.com/)
   - Create or log in with your Facebook account

2. **WhatsApp Business Account**
   - You need a WhatsApp Business Account (WABA)
   - Or use Meta's test environment

## Step-by-Step Setup

### Step 1: Create Meta App

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Click **"My Apps"** → **"Create App"**
3. Select **"Business"** as app type
4. Fill in app details and create

### Step 2: Add WhatsApp Product

1. In your app dashboard, go to **"Add Product"**
2. Find **"WhatsApp"** and click **"Set Up"**
3. Follow the setup wizard

### Step 3: Get Your Credentials

You'll need these values from Meta:

1. **Access Token** (Permanent Token)
   - Go to **WhatsApp** → **API Setup**
   - Copy the **"Temporary access token"** (for testing)
   - Or create a **System User** for permanent token

2. **Phone Number ID**
   - Found in **WhatsApp** → **API Setup**
   - Looks like: `123456789012345`

3. **Business Account ID** (Optional)
   - Found in **Business Settings** → **Accounts** → **WhatsApp Accounts**

4. **App ID** and **App Secret** (Optional, for webhooks)
   - Found in **Settings** → **Basic**

### Step 4: Configure Your App

Add these to your `.env` file:

```env
# WhatsApp Cloud API Configuration
WHATSAPP_ACCESS_TOKEN=your_access_token_here
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id_here
WHATSAPP_BUSINESS_ACCOUNT_ID=your_business_account_id_here
WHATSAPP_APP_ID=your_app_id_here
WHATSAPP_APP_SECRET=your_app_secret_here
```

**Minimum Required:**
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`

### Step 5: Test Your Setup

1. Start your app: `python app.py`
2. Go to **WhatsApp tab**
3. Click **"Refresh"**
4. Your messages should appear!

## Getting Messages

WhatsApp Cloud API uses **webhooks** to receive messages in real-time. For this app:

- **Current implementation**: Fetches conversations and latest messages
- **Future enhancement**: Can add webhook endpoint to receive real-time messages

## API Endpoints Used

- `GET /{phone-number-id}/conversations` - Get conversations
- `GET /{conversation-id}/messages` - Get messages in conversation

## Troubleshooting

### "WhatsApp Cloud API not configured"
- Make sure you added credentials to `.env` file
- Restart the app after adding credentials

### "Connection failed"
- Check that your access token is valid
- Verify phone number ID is correct
- Make sure your app has WhatsApp product added

### "Invalid access token"
- Your token may have expired (temporary tokens expire)
- Create a System User for permanent token
- Or regenerate token in Meta dashboard

## Creating Permanent Access Token

1. Go to **Business Settings** → **Users** → **System Users**
2. Create a new System User
3. Assign your app to this user
4. Generate token with permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`

## Test Phone Number

Meta provides a test phone number for development:
- Go to **WhatsApp** → **API Setup**
- You'll see a test phone number
- Use this for testing without a real WhatsApp Business number

## Documentation

- [WhatsApp Cloud API Docs](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Meta for Developers](https://developers.facebook.com/)

## Benefits of Cloud API

✅ No browser automation needed  
✅ More reliable and stable  
✅ Official Meta support  
✅ Real-time webhooks  
✅ Better for production use  
✅ No Chrome/Selenium dependencies  

