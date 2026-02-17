"""
Simple script to get Gmail OAuth tokens for testing
Run this to authorize your Gmail account and get real tokens
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import os
from pathlib import Path
from dotenv import load_dotenv
import sys

# Use project root .env only (GPTIntermediary/.env)
_project_root = Path(__file__).resolve().parent.parent.parent
ENV_PATH = str(_project_root / '.env')
if Path(ENV_PATH).exists():
    load_dotenv(ENV_PATH)
else:
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
    client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip()
    client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip()

    if not client_id or not client_secret:
        print("\n❌ GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET is missing in .env")
        print("   Add them from Google Cloud Console: https://console.cloud.google.com/apis/credentials")
        print("   Create an OAuth 2.0 Client ID (Desktop app or Web application).")
        sys.exit(1)
    if 'your_google_client' in client_id.lower() or 'your_google_client' in client_secret.lower():
        print("\n❌ Replace placeholder values in .env with real OAuth credentials from Google Cloud Console.")
        print("   https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    # Ports to try (8085 may be in use by another app)
    PORTS_TO_TRY = [8085, 8086, 8087, 8088, 8089]

    for port in PORTS_TO_TRY:
        redirect_uris = [
            f"http://localhost:{port}/",
            f"http://127.0.0.1:{port}/",
            "urn:ietf:wg:oauth:2.0:oob",
        ]
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": redirect_uris,
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        if port != 8085:
            print("\n⚠️  Using port", port, "(8085 was in use). You MUST add this redirect URI in Google Cloud Console:")
            print("    →", f"http://localhost:{port}/")
            print("    Go to: https://console.cloud.google.com/apis/credentials")
            print("    Open your OAuth 2.0 Client ID → Authorized redirect URIs → Add URI → Save.")
            print("    Then press Enter here to open the browser.\n")
            input("    Press Enter to continue... ")
        print("\n🔐 Opening browser for Gmail authorization...")
        print("📧 Please log in with the Gmail account you want to use")
        print("⚠️  IMPORTANT: You may see a 'Grant access again' prompt - this is normal!")
        print("    This ensures the app has ALL required permissions.\n")
        try:
            creds = flow.run_local_server(
                port=port,
                prompt='consent',
                access_type='offline',
                include_granted_scopes='false',
                success_message='✅ Authorization successful! You can close this window.',
            )
            if port != 8085:
                print(f"\n   (Used port {port} because 8085 was in use. Add http://localhost:{port}/ to Google Console if you use this port again.)")
            break
        except OSError as e:
            err_msg = str(e).lower()
            errno = getattr(e, 'errno', None)
            # Windows: 10048 (WSAEADDRINUSE); Linux: 98 (EADDRINUSE); "address ... permitted" / "in use"
            is_port_in_use = (
                errno in (10048, 98, 48)
                or "address" in err_msg and ("in use" in err_msg or "permitted" in err_msg or "10048" in str(e) or "18848" in str(e))
            )
            if is_port_in_use:
                if port == PORTS_TO_TRY[-1]:
                    print(f"\n❌ All ports {PORTS_TO_TRY} are in use. Close other apps using these ports or try again later.")
                    raise
                print(f"   Port {port} in use, trying next port...")
                continue
            raise
    else:
        raise RuntimeError("No available port found for OAuth callback.")
    
    # Save tokens
    print("\n✅ Got credentials!")
    print(f"\n📝 Access Token: {creds.token[:50]}...")
    if creds.refresh_token:
        print(f"📝 Refresh Token: {creds.refresh_token[:50]}...")
    else:
        print("📝 Refresh Token: (none) - see note below")
    
    if not creds.refresh_token:
        print("\n⚠️  No refresh token from Google (common if you already authorized before).")
        print("   To get one: go to https://myaccount.google.com/permissions")
        print("   → Remove this app's access → run this script again and sign in.")
    
    # Update .env file (same file we loaded)
    env_path = ENV_PATH
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    replaced_access = False
    replaced_refresh = False
    with open(env_path, 'w') as f:
        for line in lines:
            if line.startswith('USER_ACCESS_TOKEN='):
                f.write(f'USER_ACCESS_TOKEN={creds.token}\n')
                replaced_access = True
            elif line.startswith('USER_REFRESH_TOKEN='):
                if creds.refresh_token:
                    f.write(f'USER_REFRESH_TOKEN={creds.refresh_token}\n')
                    replaced_refresh = True
                else:
                    f.write(line)
            else:
                f.write(line)
        # If .env had no lines for these, append them so tokens are never lost
        if not replaced_access:
            f.write(f'\n# User OAuth Tokens (from get_gmail_token.py)\nUSER_ACCESS_TOKEN={creds.token}\n')
        if not replaced_refresh and creds.refresh_token:
            f.write(f'USER_REFRESH_TOKEN={creds.refresh_token}\n')
        elif not replaced_refresh:
            f.write('USER_REFRESH_TOKEN=\n')
    
    print(f"\n✅ Tokens saved to .env file!")
    print("\n🚀 Now restart your chat server to use the new tokens")
    print("   Then try: 'send \"hi\" to test@example.com'")
    
    return creds

if __name__ == '__main__':
    try:
        get_gmail_credentials()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        err_str = str(e).lower()
        if "401" in err_str or "invalid_client" in err_str:
            print("\n  → OAuth client not found / invalid_client usually means:")
            print("    1. Wrong or old credentials: Get new Client ID & Secret from Google Cloud Console")
            print("       https://console.cloud.google.com/apis/credentials")
            print("    2. Add authorized redirect URI: http://localhost:8085/ (and/or http://127.0.0.1:8085/)")
            print("       In Console: your OAuth client → Edit → Authorized redirect URIs → Add the above")
        if "address" in str(e).lower() or "port" in str(e).lower() or "10048" in str(e) or "18848" in str(e):
            print("\n  → Port in use: Add these to Google Console → Authorized redirect URIs:")
            print("     http://localhost:8085/  http://localhost:8086/  http://localhost:8087/")
            print("     Then run the script again; it will try the next free port.")
        print("\nAlso check:")
        print("  • GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are correct in .env")
        print("  • Internet connection and one of ports 8085–8089 available")
