"""
Simple script to get Gmail OAuth tokens for testing
Run this to authorize your Gmail account and get real tokens
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import os
from pathlib import Path
from dotenv import load_dotenv
import sys

# When run as standalone .exe (PyInstaller), .env is next to the exe. Otherwise use project root.
if getattr(sys, 'frozen', False):
    _project_root = Path(sys.executable).resolve().parent
else:
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

# Gmail API scopes (must match backend email_service.py; mail.google.com required for permanent delete)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://mail.google.com/',  # Full access, required for "delete all emails" / permanent deletion
]

def get_gmail_credentials(use_second_account=False, start_port=None):
    """Get Gmail OAuth credentials. If use_second_account is True, use _2 client vars and save to _2 token vars.
    start_port: first port to try (e.g. 8086 for second account when running both, to avoid CSRF state mix-up)."""
    if use_second_account:
        client_id = (os.getenv('GOOGLE_CLIENT_ID_2') or '').strip()
        client_secret = (os.getenv('GOOGLE_CLIENT_SECRET_2') or '').strip()
        token_key_access = 'USER_ACCESS_TOKEN_2'
        token_key_refresh = 'USER_REFRESH_TOKEN_2'
        account_label = "second (EMAIL2)"
    else:
        client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip()
        client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip()
        token_key_access = 'USER_ACCESS_TOKEN'
        token_key_refresh = 'USER_REFRESH_TOKEN'
        account_label = "primary"

    if not client_id or not client_secret:
        key_id = 'GOOGLE_CLIENT_ID_2' if use_second_account else 'GOOGLE_CLIENT_ID'
        key_sec = 'GOOGLE_CLIENT_SECRET_2' if use_second_account else 'GOOGLE_CLIENT_SECRET'
        print(f"\n❌ {key_id} or {key_sec} is missing in .env")
        print("   Add them from Google Cloud Console: https://console.cloud.google.com/apis/credentials")
        print("   Create an OAuth 2.0 Client ID (Desktop app or Web application).")
        sys.exit(1)
    if 'your_google_client' in client_id.lower() or 'your_google_client' in client_secret.lower():
        print("\n❌ Replace placeholder values in .env with real OAuth credentials from Google Cloud Console.")
        print("   https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    # Ports to try (use start_port when running both accounts so second flow uses a different port and avoids CSRF state mix-up)
    all_ports = [8085, 8086, 8087, 8088, 8089]
    if start_port and start_port in all_ports:
        PORTS_TO_TRY = [start_port] + [p for p in all_ports if p != start_port]
    else:
        PORTS_TO_TRY = all_ports

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
        print(f"📧 Please log in with the {account_label} Gmail account")
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
            if line.startswith(token_key_access + '='):
                f.write(f'{token_key_access}={creds.token}\n')
                replaced_access = True
            elif line.startswith(token_key_refresh + '='):
                if creds.refresh_token:
                    f.write(f'{token_key_refresh}={creds.refresh_token}\n')
                    replaced_refresh = True
                else:
                    f.write(line)
            else:
                f.write(line)
        if not replaced_access:
            f.write(f'\n# OAuth tokens for {account_label} account (from get_gmail_token.py)\n{token_key_access}={creds.token}\n')
        if not replaced_refresh and creds.refresh_token:
            f.write(f'{token_key_refresh}={creds.refresh_token}\n')
        elif not replaced_refresh:
            f.write(f'{token_key_refresh}=\n')

    print(f"\n✅ Tokens saved to .env ({token_key_access}, {token_key_refresh})!")
    print("\n🚀 Restart your app, then use the EMAIL2 tab to read this account's inbox." if use_second_account else "\n🚀 Now restart your chat server to use the new tokens\n   Then try: 'send \"hi\" to test@example.com'")
    
    return creds

if __name__ == '__main__':
    # Modes: no arg / "all" / "both" = BOTH accounts (first Gmail → first Cloud, second Gmail → second Cloud); "1" = primary only; "2" = second only
    arg = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
    run_both = arg in ('all', 'both', '')  # default: no arg = both (so double-click exe in copied dist gets both tokens)
    use_second = arg == '2' or (os.getenv('GMAIL_ACCOUNT') or '').strip() == '2'

    if run_both:
        print("📧 Obtaining tokens for BOTH Gmail accounts.")
        print("   1st sign-in → first Gmail account (uses GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from .env)")
        print("   2nd sign-in → second Gmail account (uses GOOGLE_CLIENT_ID_2 / GOOGLE_CLIENT_SECRET_2 from .env)")
        print("   You will sign in twice.\n")
    elif use_second:
        print("📧 Second Gmail account (EMAIL2) – using GOOGLE_CLIENT_ID_2 / GOOGLE_CLIENT_SECRET_2")

    try:
        if run_both:
            print("——— 1/2 Primary account ———")
            get_gmail_credentials(use_second_account=False)
            print("\n——— 2/2 Second account (EMAIL2) ———")
            print("Sign in with your second Gmail; tokens will use GOOGLE_CLIENT_ID_2 / GOOGLE_CLIENT_SECRET_2 (second Gmail's Google Cloud Console).")
            print("Ensure http://localhost:8086/ is in that OAuth client's Authorized redirect URIs.\n")
            # Use port 8086 for second flow to avoid CSRF "mismatching_state" when both use 8085
            get_gmail_credentials(use_second_account=True, start_port=8086)
            print("\n✅ Done. Both token sets saved to .env. Restart your app.")
        else:
            get_gmail_credentials(use_second_account=use_second)
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
