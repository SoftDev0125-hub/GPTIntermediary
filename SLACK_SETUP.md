# Slack Integration Setup Guide

This guide will help you set up Slack integration for the GPTIntermediary application.

## Prerequisites

1. A Slack workspace
2. Admin access to your Slack workspace (or permission to install apps)
3. Python 3.8 or higher
4. Internet connection

## Step 1: Create a Slack App

1. **Visit the Slack API Website:**
   - Go to https://api.slack.com/apps
   - Sign in with your Slack account

2. **Create a New App:**
   - Click "Create New App"
   - Choose "From scratch"
   - Enter an app name (e.g., "GPTIntermediary")
   - Select your workspace
   - Click "Create App"

## Step 2: Configure OAuth & Permissions

1. **Navigate to OAuth & Permissions:**
   - In your app's settings, go to "OAuth & Permissions" in the left sidebar

2. **Add Bot Token Scopes:**
   - Scroll down to "Bot Token Scopes"
   - Add the following scopes:
     - `channels:history` - View messages in public channels
     - `groups:history` - View messages in private channels
     - `im:history` - View messages in direct messages
     - `mpim:history` - View messages in group direct messages
     - `channels:read` - View basic information about public channels
     - `groups:read` - View basic information about private channels
     - `im:read` - **REQUIRED** - List direct message conversations
     - `mpim:read` - List group direct message conversations (optional)
     - `chat:write` - **REQUIRED** - Send messages to channels and DMs
     - `users:read` - View people in a workspace
     - `users:read.email` - View email addresses of people in a workspace (optional)

3. **Add User Token Scopes (RECOMMENDED - for accessing all your messages):**
   - Scroll up to "User Token Scopes"
   - Add the following scopes:
     - `channels:history` - View messages in public channels
     - `groups:history` - View messages in private channels
     - `im:history` - View messages in direct messages
     - `mpim:history` - View messages in group direct messages
     - `channels:read` - View basic information about public channels
     - `groups:read` - View basic information about private channels
     - `im:read` - **REQUIRED** - List direct message conversations
     - `mpim:read` - List group direct message conversations (optional)
     - `chat:write` - **REQUIRED** - Send messages to channels and DMs
     - `users:read` - View people in a workspace
     - `users:read.email` - View email addresses of people in a workspace (optional)
   - **IMPORTANT:** User tokens have access to all channels you are in, while bot tokens only have access to channels the bot is invited to
   - **For seeing your real Slack account messages, use a USER TOKEN (SLACK_USER_TOKEN)**

## Step 3: Install the App to Your Workspace

1. **Install the App:**
   - Scroll to the top of the "OAuth & Permissions" page
   - Click "Install to Workspace"
   - Review the permissions and click "Allow"

2. **Copy Your Bot Token:**
   - After installation, you'll see "Bot User OAuth Token"
   - It starts with `xoxb-`
   - **Copy this token** - you'll need it for the next step

3. **Optional - Get User Token:**
   - If you prefer to use a user token, scroll to "User OAuth Token"
   - Click "Reinstall to Workspace" and authorize
   - Copy the token starting with `xoxp-`

## Step 4: Configure Environment Variables

1. **Open the `.env` file** in the project root directory

2. **Add the following variables:**
   
   **For accessing all your Slack account messages (RECOMMENDED):**
   ```env
   SLACK_USER_TOKEN=xoxp-your-user-token-here
   ```
   
   **Or if using a bot token (limited access):**
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token-here
   ```
   
   **Note:** 
   - The service will prefer `SLACK_USER_TOKEN` if both are provided
   - **User tokens (SLACK_USER_TOKEN) are recommended** to see all messages from your Slack account
   - Bot tokens only have access to channels where the bot has been invited

   Example:
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token-here
   ```

## Step 5: Install Dependencies

Install the required Python package:

```bash
python -m pip install slack_sdk
```

Or if you're installing all requirements:

```bash
python -m pip install -r requirements.txt
```

## Step 6: Invite Bot to Channels (If Using Bot Token)

If you're using a bot token, you need to invite the bot to channels you want to access:

1. **In Slack:**
   - Go to the channel you want the bot to access
   - Type `/invite @YourAppName` (replace with your app's name)
   - Or use the channel settings to add the bot

2. **For Direct Messages:**
   - Bot tokens can access DMs without invitation
   - User tokens have access to all channels the user is in

## Step 7: Using Slack Integration

1. **Open the application** and navigate to the **Slack** tab

2. **Click the "View" button** to load your Slack messages

3. **View Messages:**
   - Messages from all accessible channels and DMs will be displayed in a Slack-like interface
   - Select a channel from the sidebar to view its messages
   - The interface shows:
     - Sender name/ID with avatars
     - Message content
     - Timestamp
     - Channel name (with indicators for private channels and DMs)

4. **Send Messages:**
   - Select a channel from the sidebar
   - Type your message in the input area at the bottom
   - Press Enter or click the send button to send
   - Your message will appear in the channel after sending
   - **Note:** Requires `chat:write` scope to send messages

## Troubleshooting

### Issue: "slack_sdk not installed"
**Solution:** Install slack_sdk:
```bash
python -m pip install slack_sdk
```

### Issue: "Slack API token not configured"
**Solution:** Make sure you've added `SLACK_BOT_TOKEN` or `SLACK_USER_TOKEN` to your `.env` file

### Issue: "not_in_channel" error
**Solution:** 
- If using a bot token, invite the bot to the channel
- Or switch to a user token which has access to all channels the user is in

### Issue: "missing_scope" error
**Solution:**
- Go back to your Slack app settings
- Add the missing scope in "OAuth & Permissions"
- Reinstall the app to your workspace

### Issue: "invalid_auth" error
**Solution:**
- Verify your token is correct in the `.env` file
- Make sure there are no extra spaces or quotes
- Regenerate the token in Slack app settings if needed

### Issue: "channel_not_found" error
**Solution:**
- The channel might be private and the bot/user doesn't have access
- Try using a user token instead of a bot token
- Or invite the bot to the private channel

## Security Notes

1. **Keep your tokens secure:**
   - Never share your Slack tokens
   - Don't commit them to version control
   - Keep your `.env` file private
   - If a token is compromised, regenerate it immediately in Slack app settings

2. **Token Types:**
   - **User Token (`xoxp-`) - RECOMMENDED:** Has access to all channels you are in, shows your real account messages
   - **Bot Token (`xoxb-`):** Limited to channels the bot is invited to, may not show all your messages

3. **Rate Limits:**
   - Slack has rate limits on API calls
   - The app respects these limits automatically
   - If you hit rate limits, wait a few minutes and try again

## Additional Information

- **Slack API Documentation:** https://api.slack.com/
- **Slack SDK for Python:** https://slack.dev/python-slack-sdk/
- **Slack App Management:** https://api.slack.com/apps

## Support

If you encounter any issues:
1. Check the application logs for error messages
2. Verify your `.env` file configuration
3. Ensure all dependencies are installed
4. Verify your Slack app has the correct scopes
5. Make sure the bot is invited to channels (if using bot token)

