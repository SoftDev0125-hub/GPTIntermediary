"""
Telegram Authentication Script
Run this script to authenticate your Telegram account interactively
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API credentials
api_id = os.getenv('TELEGRAM_API_ID', '')
api_hash = os.getenv('TELEGRAM_API_HASH', '')
phone_number = os.getenv('TELEGRAM_PHONE_NUMBER', '')

if not api_id or not api_hash:
    print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env file")
    print("See TELEGRAM_SETUP.md for instructions on how to get these credentials")
    sys.exit(1)

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    print("ERROR: Telethon is not installed. Install it with: pip install telethon")
    sys.exit(1)

# Session file location
session_dir = os.path.join(os.path.dirname(__file__), 'telegram_session')
os.makedirs(session_dir, exist_ok=True)
session_file = os.path.join(session_dir, 'telegram_session')

async def authenticate():
    """Authenticate Telegram client interactively"""
    try:
        api_id_int = int(api_id)
    except ValueError:
        print(f"ERROR: TELEGRAM_API_ID must be a number, got: {api_id}")
        sys.exit(1)
    
    client = TelegramClient(session_file, api_id_int, api_hash)
    
    print("=" * 60)
    print("Telegram Authentication")
    print("=" * 60)
    print()
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("Starting authentication process...")
            print()
            
            # Get phone number
            if not phone_number:
                phone = input("Enter your phone number (with country code, e.g., +1234567890): ").strip()
            else:
                phone = phone_number
                print(f"Using phone number from .env: {phone}")
            
            # Send code request
            print("\nSending verification code...")
            await client.send_code_request(phone)
            
            # Get verification code
            code = input("\nEnter the verification code you received in Telegram: ").strip()
            
            try:
                # Sign in with code
                await client.sign_in(phone, code)
                print("\n✓ Authentication successful!")
            except SessionPasswordNeededError:
                # 2FA password required
                print("\n2FA password is required for your account.")
                max_password_attempts = 3
                for attempt in range(max_password_attempts):
                    password = input(f"\nEnter your 2FA password (attempt {attempt + 1}/{max_password_attempts}): ").strip()
                    if not password:
                        print("Password cannot be empty. Please try again.")
                        continue
                    
                    try:
                        # When 2FA is required, call sign_in with password only
                        # The phone and code were already processed
                        await client.sign_in(password=password)
                        print("\n✓ Authentication successful!")
                        break
                    except SessionPasswordNeededError:
                        if attempt < max_password_attempts - 1:
                            print("Incorrect password. Please try again.")
                        else:
                            print("\nERROR: Maximum password attempts reached.")
                            print("The 2FA password you entered is incorrect.")
                            print("\nTroubleshooting:")
                            print("1. Make sure you're entering the correct password you set in Telegram Settings")
                            print("2. Check if you have caps lock enabled")
                            print("3. If you forgot your password, you may need to reset it:")
                            print("   Telegram Settings → Privacy and Security → Two-Step Verification")
                            raise
                    except Exception as password_error:
                        error_msg = str(password_error)
                        print(f"\nERROR: 2FA password authentication failed: {error_msg}")
                        if "password" in error_msg.lower() or "invalid" in error_msg.lower():
                            if attempt < max_password_attempts - 1:
                                print("The password appears to be incorrect. Please try again.")
                            else:
                                print("\nThe 2FA password is incorrect.")
                                print("If you forgot your password, reset it in Telegram Settings → Privacy and Security → Two-Step Verification")
                        raise
            except Exception as signin_error:
                error_msg = str(signin_error)
                # Check if it's a 2FA password error
                if "password" in error_msg.lower() or "two-step" in error_msg.lower() or "2FA" in error_msg.upper() or "two-steps" in error_msg.lower():
                    # 2FA password required - this shouldn't happen if SessionPasswordNeededError was caught, but handle it anyway
                    print("\n2FA password is required for your account.")
                    password = input("\nEnter your 2FA password: ").strip()
                    try:
                        await client.sign_in(password=password)
                        print("\n✓ Authentication successful!")
                    except Exception as password_error:
                        error_msg_pwd = str(password_error)
                        print(f"\nERROR: 2FA password authentication failed: {error_msg_pwd}")
                        if "password" in error_msg_pwd.lower() or "invalid" in error_msg_pwd.lower():
                            print("\nThe 2FA password you entered is incorrect.")
                            print("Please make sure you're entering the correct password you set in Telegram Settings.")
                            print("If you forgot your password, reset it in Telegram Settings → Privacy and Security → Two-Step Verification")
                        raise
                else:
                    # Re-raise if it's not a password error
                    raise
        else:
            print("Already authenticated!")
            me = await client.get_me()
            print(f"Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'no username'})")
        
        await client.disconnect()
        print("\n" + "=" * 60)
        print("Authentication complete! You can now use Telegram in the app.")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nERROR: Authentication failed: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Make sure your phone number is correct (include country code)")
        print("2. Check that you entered the verification code correctly")
        print("3. If you have 2FA, make sure you enter the correct password")
        print("4. Delete the session file and try again if needed")
        await client.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(authenticate())

