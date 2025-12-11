"""
Test script for reading Telegram messages
Run this to verify your Telegram integration is working correctly
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
sys.path.insert(0, os.path.dirname(__file__))

from services.telegram_service import TelegramService

async def test_telegram_messages():
    """Test reading Telegram messages"""
    print("=" * 60)
    print("Testing Telegram Message Reading")
    print("=" * 60)
    print()
    
    # Initialize service
    telegram_service = TelegramService()
    
    # Check configuration
    if not telegram_service.is_configured:
        print("[ERROR] Telegram is not properly configured")
        print("\nPlease check your .env file has:")
        print("  - TELEGRAM_API_ID")
        print("  - TELEGRAM_API_HASH")
        print("\nSee TELEGRAM_SETUP.md for instructions")
        return False
    
    print("[OK] Configuration check passed")
    print()
    
    # Initialize connection
    print("Initializing Telegram connection...")
    try:
        await telegram_service.initialize()
        print("[OK] Connection initialized")
    except Exception as e:
        print(f"[ERROR] Failed to initialize connection: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Make sure you have authenticated (run authenticate_telegram.py)")
        print("2. Check that your session file exists in telegram_session/")
        print("3. If you see AUTH_KEY_UNREGISTERED, delete the session file and re-authenticate")
        return False
    
    print()
    
    # Test fetching messages
    print("Fetching messages (limit: 10)...")
    try:
        messages, total_count = await telegram_service.get_messages(limit=10)
        print(f"[OK] Successfully fetched {len(messages)} messages (total available: {total_count})")
        print()
        
        if len(messages) == 0:
            print("[WARNING] No messages found. This could mean:")
            print("   - You don't have any recent messages")
            print("   - Your account is new")
            print("   - There's an issue with message retrieval")
        else:
            print("Sample messages:")
            print("-" * 60)
            for i, msg in enumerate(messages[:5], 1):  # Show first 5
                chat_name = msg.chat_name or "Unknown"
                sender = msg.sender_name or "Unknown"
                is_sent = "→" if msg.is_sent else "←"
                preview = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                print(f"{i}. {is_sent} [{chat_name}] {sender}: {preview}")
            
            if len(messages) > 5:
                print(f"\n... and {len(messages) - 5} more messages")
        
        print()
        print("-" * 60)
        print("[OK] Test completed successfully!")
        print("=" * 60)
        
        # Clean up
        await telegram_service.cleanup()
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch messages: {str(e)}")
        print("\nTroubleshooting:")
        if "AUTH_KEY_UNREGISTERED" in str(e) or "invalid or expired" in str(e):
            print("1. Delete the session file: telegram_session/telegram_session.session")
            print("2. Run: python authenticate_telegram.py")
            print("3. Try this test again")
        elif "not authorized" in str(e) or "authenticate" in str(e):
            print("1. Run: python authenticate_telegram.py")
            print("2. Follow the authentication steps")
            print("3. Try this test again")
        else:
            print("1. Check your internet connection")
            print("2. Verify your API credentials in .env")
            print("3. Check TELEGRAM_SETUP.md for detailed instructions")
        
        try:
            await telegram_service.cleanup()
        except:
            pass
        
        return False

if __name__ == "__main__":
    success = asyncio.run(test_telegram_messages())
    sys.exit(0 if success else 1)

