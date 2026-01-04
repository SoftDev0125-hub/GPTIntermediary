"""
Simple script to get Gmail OAuth tokens for testing
Run this to authorize your Gmail account and get real tokens
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import os
from dotenv import load_dotenv
import sys

load_dotenv()

# Ensure stdout is using UTF-8 where possible to avoid UnicodeEncodeError
try:
    if hasattr(sys, 'stdout') and (sys.stdout is None or sys.stdout.encoding is None or 'utf' not in sys.stdout.encoding.lower()):
        # Python 3.7+: reconfigure stdout encoding
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
except Exception:
    pass

# Gmail API scopes (must match backend email_service.py)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

def get_gmail_credentials():
    """Get Gmail OAuth credentials"""
    
    # Create credentials dict from environment
    client_config = {
        "installed": {
            "client_id": os.getenv('GOOGLE_CLIENT_ID'),
            "client_secret": os.getenv('GOOGLE_CLIENT_SECRET'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://72.62.162.44:8085/", "urn:ietf:wg:oauth:2.0:oob"]
        }
    }
    
    # Create flow
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    
    # Run local server for OAuth
    print("\n🔐 Opening browser for Gmail authorization...")
    print("📧 Please log in with the Gmail account you want to use")
    print("⚠️  IMPORTANT: You may see a 'Grant access again' prompt - this is normal!")
    print("    This ensures the app has ALL required permissions.\n")
    
    creds = flow.run_local_server(port=8085, 
                                   prompt='consent',
                                   access_type='offline',
                                   include_granted_scopes='false',
                                   success_message='✅ Authorization successful! You can close this window.')
    
    # Save tokens
    print("\n✅ Got credentials!")
    print(f"\n📝 Access Token: {creds.token[:50]}...")
    print(f"📝 Refresh Token: {creds.refresh_token[:50]}..." if creds.refresh_token else "📝 Refresh Token: (none)")
    
    # Update .env file
    env_path = '.env'
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    with open(env_path, 'w') as f:
        for line in lines:
            if line.startswith('USER_ACCESS_TOKEN='):
                f.write(f'USER_ACCESS_TOKEN={creds.token}\n')
            elif line.startswith('USER_REFRESH_TOKEN='):
                if creds.refresh_token:
                    f.write(f'USER_REFRESH_TOKEN={creds.refresh_token}\n')
                else:
                    f.write(line)
            else:
                f.write(line)
    
    print(f"\n✅ Tokens saved to .env file!")
    print("\n🚀 Now restart your chat server to use the new tokens")
    print("   Then try: 'send \"hi\" to test@example.com'")
    
    return creds

if __name__ == '__main__':
    try:
        get_gmail_credentials()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure:")
        print("1. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are in .env")
        print("2. You have internet connection")
        print("3. Port 8080 is available")
