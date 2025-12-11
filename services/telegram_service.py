"""
Telegram Service
Handles Telegram message retrieval and operations using Telegram Client API
"""

import logging
import os
import asyncio
from typing import List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

from models.schemas import TelegramMessage

# Try to import Telethon (Telegram client library)
try:
    from telethon import TelegramClient
    from telethon.tl.types import User, Chat, Channel, MessageService
    from telethon.errors import RPCError, AuthKeyUnregisteredError
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    RPCError = None
    AuthKeyUnregisteredError = None
    MessageService = None

load_dotenv()
logger = logging.getLogger(__name__)


class TelegramService:
    """Service for handling Telegram operations using Telethon"""
    
    def __init__(self):
        """Initialize Telegram service"""
        load_dotenv(override=True)
        self.api_id = os.getenv('TELEGRAM_API_ID', '')
        self.api_hash = os.getenv('TELEGRAM_API_HASH', '')
        self.phone_number = os.getenv('TELEGRAM_PHONE_NUMBER', '')
        
        self.client = None
        self.is_connected = False
        
        # Check if API ID is a valid integer (not a placeholder)
        try:
            api_id_int = int(self.api_id) if self.api_id else None
            self.is_configured = bool(api_id_int and self.api_hash and 
                                     self.api_id != 'your_api_id' and 
                                     self.api_hash != 'your_api_hash')
        except (ValueError, TypeError):
            api_id_int = None
            self.is_configured = False
        
        if not TELETHON_AVAILABLE:
            logger.warning("Telethon not available. Install with: pip install telethon")
        elif not self.is_configured:
            logger.warning("Telegram API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        else:
            # Session file to persist login
            session_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'telegram_session')
            os.makedirs(session_dir, exist_ok=True)
            session_file = os.path.join(session_dir, 'telegram_session')
            
            self.client = TelegramClient(session_file, api_id_int, self.api_hash)
            logger.info("Telegram service initialized")
    
    def _create_client(self):
        """Create or recreate Telegram client"""
        if not TELETHON_AVAILABLE:
            return False
        
        if not self.is_configured:
            return False
        
        try:
            api_id_int = int(self.api_id) if self.api_id else None
            if not api_id_int:
                return False
        except (ValueError, TypeError):
            return False
        
        # Session file to persist login
        session_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'telegram_session')
        os.makedirs(session_dir, exist_ok=True)
        session_file = os.path.join(session_dir, 'telegram_session')
        
        self.client = TelegramClient(session_file, api_id_int, self.api_hash)
        logger.info("Telegram client created/recreated")
        return True
    
    async def initialize(self):
        """Initialize Telegram client connection"""
        if not TELETHON_AVAILABLE:
            logger.warning("Telethon not installed. Install with: pip install telethon")
            return
        
        if not self.is_configured:
            logger.warning("Telegram API credentials not configured")
            return
        
        # Recreate client if it doesn't exist
        if not self.client:
            if not self._create_client():
                return
        
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.warning("Telegram client not authorized. User needs to authenticate.")
                # Disconnect to prevent automatic reconnection attempts that cause permission errors
                try:
                    await self.client.disconnect()
                except:
                    pass
            else:
                self.is_connected = True
                logger.info("Telegram client connected and authorized")
        except Exception as e:
            error_msg = str(e)
            if "Access is denied" in error_msg or "PermissionError" in error_msg or "WinError 5" in error_msg:
                logger.error("Telegram connection failed: Windows permission error. Check firewall/antivirus settings.")
            else:
                logger.error(f"Error initializing Telegram client: {str(e)}")
            # Disconnect on error to prevent reconnection attempts
            try:
                await self.client.disconnect()
            except:
                pass
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.client:
            try:
                await self.client.disconnect()
                self.is_connected = False
            except:
                pass
        logger.info("Telegram service cleanup completed")
    
    async def authenticate(self, phone_number: Optional[str] = None, code: Optional[str] = None, password: Optional[str] = None) -> Tuple[bool, str]:
        """
        Authenticate Telegram client
        
        Args:
            phone_number: Phone number (if first step)
            code: Verification code (if second step)
            password: 2FA password (if third step)
        
        Returns:
            Tuple of (is_complete, status_message)
        """
        try:
            if not TELETHON_AVAILABLE:
                return False, "Telethon not installed. Install with: pip install telethon"
            
            if not self.is_configured:
                return False, "Telegram API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env"
            
            if not self.client:
                return False, "Telegram client not initialized"
            
            await self.client.connect()
            
            if await self.client.is_user_authorized():
                self.is_connected = True
                return True, "Already authenticated"
            
            # Start authentication process
            if not phone_number:
                phone = self.phone_number or phone_number
                if not phone:
                    return False, "Phone number required. Please provide your Telegram phone number. If this app doesn't have a verification code input, run `python authenticate_telegram.py`, which will display a window for entering the verification code from the app."
                await self.client.send_code_request(phone)
                return False, "Verification code sent. Please check your Telegram app and provide the code. If this app doesn't have a verification code input, run `python authenticate_telegram.py`, which will display a window for entering the verification code from the app."
            
            if not code:
                return False, "Verification code required. If this app doesn't have a verification code input, run `python authenticate_telegram.py`, which will display a window for entering the verification code from the app."
            
            try:
                await self.client.sign_in(phone_number or self.phone_number, code, password=password)
                self.is_connected = True
                return True, "Successfully authenticated"
            except Exception as e:
                error_msg = str(e)
                if "PASSWORD_HASH_INVALID" in error_msg or "password" in error_msg.lower():
                    return False, "Two-factor authentication password required"
                elif "PHONE_CODE_INVALID" in error_msg or "code" in error_msg.lower():
                    return False, "Invalid verification code. Please try again."
                else:
                    return False, f"Authentication failed: {error_msg}"
        
        except Exception as e:
            logger.error(f"Error during Telegram authentication: {str(e)}")
            return False, f"Authentication error: {str(e)}"
    
    async def get_messages(
        self,
        limit: int = 50
    ) -> tuple[List[TelegramMessage], int]:
        """
        Retrieve Telegram messages from all chats
        
        Args:
            limit: Maximum number of messages to retrieve
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            if not TELETHON_AVAILABLE:
                raise Exception("Telethon not installed. Install with: pip install telethon")
            
            if not self.is_configured:
                raise Exception("Telegram API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
            
            # Recreate client if it doesn't exist (e.g., after session deletion)
            if not self.client:
                if not self._create_client():
                    raise Exception("Telegram client not initialized. Please ensure TELEGRAM_API_ID and TELEGRAM_API_HASH are configured in .env")
            
            # Ensure client is connected
            try:
                if not self.client.is_connected():
                    await self.client.connect()
            except Exception as conn_error:
                # If connection fails, check for specific errors
                error_msg = str(conn_error)
                
                # Check for SESSION_PASSWORD_NEEDED first (2FA password required)
                if "SESSION_PASSWORD_NEEDED" in error_msg:
                    # Disconnect to prevent reconnection attempts
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                    raise Exception(
                        "Telegram 2FA password required. "
                        "Your account has two-factor authentication enabled. "
                        "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                        "See TELEGRAM_SETUP.md for detailed instructions."
                    )
                
                # Check for invalid session/auth key errors
                if "AUTH_KEY_UNREGISTERED" in error_msg or ("401" in error_msg and "AUTH" in error_msg and "SESSION_PASSWORD" not in error_msg):
                    # Disconnect to prevent reconnection attempts
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                    raise Exception(
                        "Telegram session file is invalid or expired. "
                        "Please delete the session file in telegram_session/ directory and restart the app to re-authenticate. "
                        "See TELEGRAM_SETUP.md for detailed instructions."
                    )
                
                # Check for permission issues
                if "Access is denied" in error_msg or "PermissionError" in error_msg:
                    raise Exception(
                        "Telegram connection failed due to Windows permission error. "
                        "Please check Windows Firewall settings and ensure Python has network access. "
                        "Also verify that Telegram client is authorized. "
                        "See TELEGRAM_SETUP.md for instructions."
                    )
                raise
            
            # Check authorization - this may raise AUTH_KEY_UNREGISTERED if session is invalid
            try:
                is_authorized = await self.client.is_user_authorized()
                logger.debug(f"is_user_authorized() returned: {is_authorized}")
            except Exception as auth_error:
                error_msg = str(auth_error)
                error_type = type(auth_error).__name__
                auth_error_message_attr = None
                
                logger.debug(f"is_user_authorized() raised exception: type={error_type}, msg={error_msg}")
                
                # CRITICAL: Check for SESSION_PASSWORD_NEEDED FIRST (2FA password required)
                if (TELETHON_AVAILABLE and RPCError and isinstance(auth_error, RPCError)):
                    if hasattr(auth_error, 'error_message'):
                        auth_error_message_attr = str(auth_error.error_message)
                        logger.debug(f"RPCError error_message attribute: {auth_error_message_attr}")
                        if 'SESSION_PASSWORD_NEEDED' in auth_error_message_attr:
                            logger.info("Detected SESSION_PASSWORD_NEEDED in is_user_authorized() RPCError")
                            # Disconnect to prevent reconnection attempts
                            try:
                                await self.client.disconnect()
                            except:
                                pass
                            raise Exception(
                                "Telegram 2FA password required. "
                                "Your account has two-factor authentication enabled. "
                                "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                                "See TELEGRAM_SETUP.md for detailed instructions."
                            )
                    # Also check error code
                    if hasattr(auth_error, 'error_code') and auth_error.error_code == 401:
                        if auth_error_message_attr and 'SESSION_PASSWORD_NEEDED' in auth_error_message_attr:
                            logger.info("Detected SESSION_PASSWORD_NEEDED via is_user_authorized() error_code 401")
                            try:
                                await self.client.disconnect()
                            except:
                                pass
                            raise Exception(
                                "Telegram 2FA password required. "
                                "Your account has two-factor authentication enabled. "
                                "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                                "See TELEGRAM_SETUP.md for detailed instructions."
                            )
                
                # Check for SESSION_PASSWORD_NEEDED in error message string
                if "SESSION_PASSWORD_NEEDED" in error_msg:
                    logger.info(f"Detected SESSION_PASSWORD_NEEDED in is_user_authorized() error string: {error_msg}")
                    # Disconnect to prevent reconnection attempts
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                    raise Exception(
                        "Telegram 2FA password required. "
                        "Your account has two-factor authentication enabled. "
                        "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                        "See TELEGRAM_SETUP.md for detailed instructions."
                    )
                
                # Disconnect to prevent reconnection attempts
                try:
                    await self.client.disconnect()
                except:
                    pass
                
                # Check for AUTH_KEY_UNREGISTERED (session invalid)
                if "AUTH_KEY_UNREGISTERED" in error_msg:
                    raise Exception(
                        "Telegram session file is invalid or expired. "
                        "Please delete the session file in telegram_session/ directory and restart the app to re-authenticate. "
                        "See TELEGRAM_SETUP.md for detailed instructions."
                    )
                
                # Check for 401 error code, but only if it's not SESSION_PASSWORD_NEEDED
                if (TELETHON_AVAILABLE and RPCError and isinstance(auth_error, RPCError)):
                    if hasattr(auth_error, 'error_code') and auth_error.error_code == 401:
                        if hasattr(auth_error, 'error_message') and 'SESSION_PASSWORD_NEEDED' not in str(auth_error.error_message):
                            raise Exception(
                                "Telegram session file is invalid or expired. "
                                "Please delete the session file in telegram_session/ directory and restart the app to re-authenticate. "
                                "See TELEGRAM_SETUP.md for detailed instructions."
                            )
                
                raise Exception(f"Telegram authentication error: {error_msg}")
            
            if not is_authorized:
                # Check if we got AUTH_KEY_UNREGISTERED or SESSION_PASSWORD_NEEDED by trying API calls
                # The error might have been logged but not raised, so we try multiple API calls
                auth_key_invalid = False
                session_password_detected = False
                
                # Try get_me() first
                try:
                    me = await self.client.get_me()
                    # If get_me() returns None, session might be invalid
                    if me is None:
                        auth_key_invalid = True
                except Exception as test_error:
                    error_msg = str(test_error)
                    error_type = type(test_error).__name__
                    
                    # CRITICAL: Check for SESSION_PASSWORD_NEEDED FIRST before anything else
                    # This must be checked BEFORE checking for AUTH_KEY_UNREGISTERED
                    session_password_needed = False
                    error_message_attr = None
                    
                    if (TELETHON_AVAILABLE and RPCError and isinstance(test_error, RPCError)):
                        # Check error_message attribute (most reliable)
                        if hasattr(test_error, 'error_message'):
                            error_message_attr = str(test_error.error_message)
                            if 'SESSION_PASSWORD_NEEDED' in error_message_attr:
                                session_password_needed = True
                                logger.info(f"Detected SESSION_PASSWORD_NEEDED in error_message attribute: {error_message_attr}")
                        # Also check error code 401 with SESSION_PASSWORD_NEEDED
                        if hasattr(test_error, 'error_code') and test_error.error_code == 401:
                            if error_message_attr and 'SESSION_PASSWORD_NEEDED' in error_message_attr:
                                session_password_needed = True
                                logger.info(f"Detected SESSION_PASSWORD_NEEDED via error_code 401: {error_message_attr}")
                    
                    # Check string representation as fallback
                    if "SESSION_PASSWORD_NEEDED" in error_msg:
                        session_password_needed = True
                        logger.info(f"Detected SESSION_PASSWORD_NEEDED in error message string: {error_msg}")
                    
                    # If SESSION_PASSWORD_NEEDED, raise immediately - don't continue checking
                    if session_password_needed:
                        session_password_detected = True
                        try:
                            await self.client.disconnect()
                        except:
                            pass
                        logger.info("Raising SESSION_PASSWORD_NEEDED exception")
                        raise Exception(
                            "Telegram 2FA password required. "
                            "Your account has two-factor authentication enabled. "
                            "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                            "See TELEGRAM_SETUP.md for detailed instructions."
                        )
                    
                    # Only now check for AUTH_KEY_UNREGISTERED error
                    if (TELETHON_AVAILABLE and AuthKeyUnregisteredError and 
                        isinstance(test_error, AuthKeyUnregisteredError)):
                        auth_key_invalid = True
                        logger.info("Detected AuthKeyUnregisteredError")
                    elif (TELETHON_AVAILABLE and RPCError and 
                          isinstance(test_error, RPCError)):
                        # Check error message attribute first
                        if error_message_attr:
                            if 'AUTH_KEY_UNREGISTERED' in error_message_attr:
                                auth_key_invalid = True
                                logger.info(f"Detected AUTH_KEY_UNREGISTERED in error_message: {error_message_attr}")
                        # Check error code, but only if it's not SESSION_PASSWORD_NEEDED (already checked above)
                        if hasattr(test_error, 'error_code') and test_error.error_code == 401:
                            if error_message_attr:
                                if 'AUTH_KEY_UNREGISTERED' in error_message_attr:
                                    auth_key_invalid = True
                                    logger.info(f"Detected AUTH_KEY_UNREGISTERED via error_code 401: {error_message_attr}")
                            # If we don't have error_message attribute, be conservative
                            # Only mark as invalid if we see AUTH_KEY_UNREGISTERED in the string
                            elif 'AUTH_KEY_UNREGISTERED' in error_msg:
                                auth_key_invalid = True
                                logger.info(f"Detected AUTH_KEY_UNREGISTERED in error string: {error_msg}")
                        # Also check the string representation for AUTH_KEY_UNREGISTERED
                        elif "AUTH_KEY_UNREGISTERED" in error_msg:
                            auth_key_invalid = True
                            logger.info(f"Detected AUTH_KEY_UNREGISTERED in error string: {error_msg}")
                    elif "AUTH_KEY_UNREGISTERED" in error_msg or ("401" in error_msg and "AUTH" in error_msg and "SESSION_PASSWORD" not in error_msg):
                        auth_key_invalid = True
                        logger.info(f"Detected AUTH_KEY_UNREGISTERED via string match: {error_msg}")
                    
                    logger.debug(f"Telegram get_me() error: type={error_type}, msg={error_msg}, code={getattr(test_error, 'error_code', 'N/A')}, error_message={error_message_attr}, auth_key_invalid={auth_key_invalid}")
                
                # If get_me() didn't reveal the issue and we haven't detected SESSION_PASSWORD_NEEDED, try get_dialogs()
                if not auth_key_invalid and not session_password_detected:
                    try:
                        await self.client.get_dialogs(limit=1)
                    except Exception as dialog_error:
                        error_msg = str(dialog_error)
                        error_type = type(dialog_error).__name__
                        dialog_error_message_attr = None
                        
                        # CRITICAL: Check for SESSION_PASSWORD_NEEDED FIRST before anything else
                        session_password_needed_dialog = False
                        
                        if (TELETHON_AVAILABLE and RPCError and isinstance(dialog_error, RPCError)):
                            # Check error_message attribute (most reliable)
                            if hasattr(dialog_error, 'error_message'):
                                dialog_error_message_attr = str(dialog_error.error_message)
                                if 'SESSION_PASSWORD_NEEDED' in dialog_error_message_attr:
                                    session_password_needed_dialog = True
                                    logger.info(f"Detected SESSION_PASSWORD_NEEDED in get_dialogs() error_message: {dialog_error_message_attr}")
                            # Also check error code 401 with SESSION_PASSWORD_NEEDED
                            if hasattr(dialog_error, 'error_code') and dialog_error.error_code == 401:
                                if dialog_error_message_attr and 'SESSION_PASSWORD_NEEDED' in dialog_error_message_attr:
                                    session_password_needed_dialog = True
                                    logger.info(f"Detected SESSION_PASSWORD_NEEDED via get_dialogs() error_code 401: {dialog_error_message_attr}")
                        
                        # Check string representation as fallback
                        if "SESSION_PASSWORD_NEEDED" in error_msg:
                            session_password_needed_dialog = True
                            logger.info(f"Detected SESSION_PASSWORD_NEEDED in get_dialogs() error string: {error_msg}")
                        
                        # If SESSION_PASSWORD_NEEDED, raise immediately - don't continue checking
                        if session_password_needed_dialog:
                            session_password_detected = True
                            try:
                                await self.client.disconnect()
                            except:
                                pass
                            logger.info("Raising SESSION_PASSWORD_NEEDED exception from get_dialogs()")
                            raise Exception(
                                "Telegram 2FA password required. "
                                "Your account has two-factor authentication enabled. "
                                "Please run `python authenticate_telegram.py` to authenticate with your 2FA password. "
                                "See TELEGRAM_SETUP.md for detailed instructions."
                            )
                        
                        if (TELETHON_AVAILABLE and AuthKeyUnregisteredError and 
                            isinstance(dialog_error, AuthKeyUnregisteredError)):
                            auth_key_invalid = True
                        elif (TELETHON_AVAILABLE and RPCError and 
                              isinstance(dialog_error, RPCError)):
                            if hasattr(dialog_error, 'error_code') and dialog_error.error_code == 401:
                                # Only treat as invalid if it's not SESSION_PASSWORD_NEEDED
                                if not (hasattr(dialog_error, 'error_message') and 'SESSION_PASSWORD_NEEDED' in str(dialog_error.error_message)):
                                    auth_key_invalid = True
                            if hasattr(dialog_error, 'error_message') and 'AUTH_KEY_UNREGISTERED' in str(dialog_error.error_message):
                                auth_key_invalid = True
                        elif "AUTH_KEY_UNREGISTERED" in error_msg or ("401" in error_msg and "AUTH" in error_msg and "SESSION_PASSWORD" not in error_msg):
                            auth_key_invalid = True
                        logger.debug(f"Telegram get_dialogs() error: {error_msg}")
                
                # Only raise AUTH_KEY_UNREGISTERED if we're sure it's not SESSION_PASSWORD_NEEDED
                if auth_key_invalid and not session_password_detected:
                    # Disconnect client first and ensure it's fully disconnected
                    try:
                        if self.client:
                            if hasattr(self.client, 'is_connected') and self.client.is_connected():
                                await self.client.disconnect()
                            # Force cleanup by deleting the client reference
                            # This helps release file locks on Windows
                            del self.client
                            # Force garbage collection to release file handles
                            import gc
                            gc.collect()
                    except Exception as disconnect_error:
                        logger.debug(f"Error during disconnect: {str(disconnect_error)}")
                    finally:
                        # Always reset client state
                        self.client = None
                        self.is_connected = False
                    
                    # Wait longer for file locks to be released (especially important on Windows)
                    import asyncio
                    await asyncio.sleep(2.0)
                    
                    # Try to automatically delete the invalid session file
                    session_deleted = False
                    session_file_path = None
                    try:
                        session_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'telegram_session')
                        session_file_path = os.path.join(session_dir, 'telegram_session.session')
                        if os.path.exists(session_file_path):
                            # Try to delete the invalid session file
                            # Retry a few times in case file is still locked
                            max_retries = 3
                            for attempt in range(max_retries):
                                try:
                                    os.remove(session_file_path)
                                    logger.info(f"Automatically deleted invalid session file: {session_file_path}")
                                    session_deleted = True
                                    break
                                except (PermissionError, OSError) as delete_error:
                                    if attempt < max_retries - 1:
                                        # Wait longer before retrying (Windows file locks can be persistent)
                                        await asyncio.sleep(2.0)
                                        logger.debug(f"Retry {attempt + 1}/{max_retries} to delete session file...")
                                    else:
                                        logger.warning(f"Could not automatically delete session file after {max_retries} attempts (file is locked by another process). Use the 'Delete Session File' button in the UI or stop the server and delete manually.")
                                        session_deleted = False
                                except Exception as delete_error:
                                    logger.warning(f"Could not automatically delete session file: {str(delete_error)}")
                                    session_deleted = False
                                    break
                        else:
                            session_deleted = False
                    except Exception as e:
                        logger.warning(f"Error checking session file: {str(e)}")
                        session_deleted = False
                    
                    if session_deleted:
                        error_msg = (
                            "Telegram session file was invalid and has been automatically deleted. "
                            "Please follow these steps:\n"
                            "1. Run: python authenticate_telegram.py\n"
                            "2. Complete the full authentication (phone, code, and 2FA password if enabled)\n"
                            "3. Click 'Refresh' again in the Telegram tab\n"
                            "See TELEGRAM_SETUP.md for detailed instructions."
                        )
                    else:
                        error_msg = (
                            "Telegram session file is invalid or expired. "
                            "This usually happens when authentication was incomplete or the session expired. "
                            "Please follow these steps:\n"
                            "1. Stop your backend server (Ctrl+C)\n"
                            "2. Delete the session file: telegram_session/telegram_session.session\n"
                            "3. Run: python authenticate_telegram.py\n"
                            "4. Complete the full authentication (phone, code, and 2FA password if enabled)\n"
                            "5. Restart your backend server\n"
                            "See TELEGRAM_SETUP.md for detailed instructions."
                        )
                    
                    logger.warning("Session file appears invalid. User should authenticate.")
                    raise Exception(error_msg)
                
                # If API calls succeeded but is_user_authorized() returned False, 
                # it means we need to authenticate (not that the session is invalid)
                # Disconnect to prevent reconnection attempts
                try:
                    await self.client.disconnect()
                except:
                    pass
                raise Exception(
                    "Telegram client not authorized. Please authenticate first. "
                    "See TELEGRAM_SETUP.md for instructions. "
                    "You may need to delete the session file in telegram_session/ directory and restart the app."
                )
            
            logger.info(f"Fetching up to {limit} Telegram messages per chat")
            
            all_messages = []
            
            # Get all dialogs (chats)
            dialogs = await self.client.get_dialogs(limit=100)
            
            for dialog in dialogs:
                try:
                    # Get messages from this chat
                    messages_list = await self.client.get_messages(dialog.entity, limit=min(limit, 100))
                    
                    for msg in messages_list:
                        try:
                            telegram_msg = self._parse_telegram_message(msg, dialog)
                            all_messages.append(telegram_msg)
                        except Exception as parse_error:
                            # Log the error but continue processing other messages
                            error_type = type(msg).__name__
                            logger.debug(f"Error parsing message from {dialog.name} (type: {error_type}): {str(parse_error)}")
                            continue
                except Exception as e:
                    logger.warning(f"Error getting messages from {dialog.name}: {str(e)}")
                    continue
            
            # Sort messages by timestamp (newest first)
            all_messages.sort(key=lambda x: x.timestamp, reverse=True)
            
            logger.info(f"Retrieved {len(all_messages)} Telegram messages")
            return all_messages, len(all_messages)
        
        except Exception as e:
            logger.error(f"Error fetching Telegram messages: {str(e)}")
            raise Exception(f"Failed to fetch Telegram messages: {str(e)}")
    
    def _parse_telegram_message(self, msg, dialog) -> TelegramMessage:
        """Parse Telegram message into TelegramMessage model"""
        # Initialize sender information
        sender_name = "Unknown"
        sender_id = ""
        
        # Check if this is a service message (like "user joined", "user left", etc.)
        # Service messages don't have the same attributes as regular messages
        is_service_message = False
        if TELETHON_AVAILABLE and MessageService:
            is_service_message = isinstance(msg, MessageService)
        
        if is_service_message:
            # Handle service messages differently
            body = "[Service Message]"
            if hasattr(msg, 'action') and msg.action:
                action_type = type(msg.action).__name__
                body = f"[{action_type.replace('MessageAction', '')}]"
            sender_name = "System"
        else:
            # Regular message - get sender information
            if hasattr(msg, 'sender') and msg.sender:
                if hasattr(msg.sender, 'first_name'):
                    sender_name = msg.sender.first_name
                    if hasattr(msg.sender, 'last_name') and msg.sender.last_name:
                        sender_name += f" {msg.sender.last_name}"
                if hasattr(msg.sender, 'id'):
                    sender_id = str(msg.sender.id)
                if hasattr(msg.sender, 'username') and msg.sender.username:
                    sender_name = f"@{msg.sender.username}"
            
            # Get message text
            body = ""
            if hasattr(msg, 'text') and msg.text:
                body = msg.text
            elif hasattr(msg, 'media') and msg.media:
                if hasattr(msg.media, 'photo'):
                    body = "[Photo]"
                elif hasattr(msg.media, 'document'):
                    body = f"[Document] {getattr(msg.media.document, 'file_name', '')}"
                elif hasattr(msg.media, 'video'):
                    body = "[Video]"
                elif hasattr(msg.media, 'audio'):
                    body = "[Audio]"
                elif hasattr(msg.media, 'voice'):
                    body = "[Voice Message]"
                else:
                    body = "[Media]"
            else:
                body = "[Empty Message]"
        
        # Get chat information
        chat_name = dialog.name
        chat_id = str(dialog.id)
        
        # Format timestamp
        timestamp = msg.date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(msg, 'date') and msg.date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if message was sent by current user
        is_sent = getattr(msg, 'out', False)
        
        # Safely get unread status - not all message types have this attribute
        is_read = True  # Default to read if we can't determine
        if hasattr(msg, 'unread'):
            is_read = not msg.unread
        elif is_service_message:
            # Service messages are typically considered "read"
            is_read = True
        
        return TelegramMessage(
            message_id=str(msg.id) if hasattr(msg, 'id') else "0",
            from_id=sender_id,
            from_name=sender_name,
            body=body,
            timestamp=timestamp,
            is_read=is_read,
            is_sent=is_sent,
            chat_id=chat_id,
            chat_name=chat_name
        )
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: Optional[str] = None
    ) -> str:
        """
        Send a message to a Telegram chat
        
        Args:
            chat_id: The chat ID to send the message to
            text: The message text to send
            reply_to_message_id: Optional message ID to reply to
        
        Returns:
            Message ID of the sent message
        """
        try:
            if not TELETHON_AVAILABLE:
                raise Exception("Telethon not installed. Install with: pip install telethon")
            
            if not self.is_configured:
                raise Exception("Telegram API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
            
            if not self.client:
                raise Exception("Telegram client not initialized")
            
            # Ensure client is connected
            if not self.client.is_connected():
                await self.client.connect()
            
            # Check authorization
            if not await self.client.is_user_authorized():
                raise Exception("Telegram client not authorized. Please authenticate first.")
            
            logger.info(f"Sending message to chat {chat_id}")
            
            # Convert chat_id to integer if it's a numeric string
            try:
                chat_id_int = int(chat_id)
            except ValueError:
                # If it's not numeric, try to find the entity by username or other means
                chat_id_int = chat_id
            
            # Get the entity (chat/user) to send to
            entity = await self.client.get_entity(chat_id_int)
            
            # Prepare message parameters
            send_kwargs = {}
            if reply_to_message_id:
                try:
                    reply_id_int = int(reply_to_message_id)
                    send_kwargs['reply_to'] = reply_id_int
                except ValueError:
                    logger.warning(f"Invalid reply_to_message_id: {reply_to_message_id}")
            
            # Send the message
            sent_message = await self.client.send_message(entity, text, **send_kwargs)
            
            message_id = str(sent_message.id) if hasattr(sent_message, 'id') else ""
            logger.info(f"Message sent successfully. Message ID: {message_id}")
            return message_id
            
        except Exception as e:
            logger.error(f"Error sending Telegram message: {str(e)}")
            raise Exception(f"Failed to send Telegram message: {str(e)}")
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check if Telegram client is connected
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        if not TELETHON_AVAILABLE:
            return False, "Telethon not installed"
        
        if not self.is_configured:
            return False, "Telegram API credentials not configured"
        
        if not self.client:
            return False, "Telegram client not initialized"
        
        try:
            if await self.client.is_user_authorized():
                return True, "Connected and authorized"
            else:
                return False, "Not authorized - authentication required"
        except Exception as e:
            return False, f"Error: {str(e)}"

