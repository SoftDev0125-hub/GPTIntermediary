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
    from telethon.tl.types import User, Chat, Channel
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

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
    
    async def initialize(self):
        """Initialize Telegram client connection"""
        if not TELETHON_AVAILABLE:
            logger.warning("Telethon not installed. Install with: pip install telethon")
            return
        
        if not self.is_configured:
            logger.warning("Telegram API credentials not configured")
            return
        
        if not self.client:
            return
        
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.warning("Telegram client not authorized. User needs to authenticate.")
            else:
                self.is_connected = True
                logger.info("Telegram client connected and authorized")
        except Exception as e:
            logger.error(f"Error initializing Telegram client: {str(e)}")
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.client:
            try:
                await self.client.disconnect()
                self.is_connected = False
            except:
                pass
        logger.info("Telegram service cleanup completed")
    
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
            
            if not self.client:
                raise Exception("Telegram client not initialized")
            
            if not await self.client.is_user_authorized():
                raise Exception("Telegram client not authorized. Please authenticate first.")
            
            logger.info(f"Fetching {limit} Telegram messages")
            
            messages = []
            
            # Get all dialogs (chats)
            dialogs = await self.client.get_dialogs(limit=limit)
            
            for dialog in dialogs:
                try:
                    # Get the last message from this chat
                    messages_list = await self.client.get_messages(dialog.entity, limit=1)
                    
                    if messages_list:
                        msg = messages_list[0]
                        telegram_msg = self._parse_telegram_message(msg, dialog)
                        messages.append(telegram_msg)
                except Exception as e:
                    logger.warning(f"Error getting messages from {dialog.name}: {str(e)}")
                    continue
            
            logger.info(f"Retrieved {len(messages)} Telegram messages")
            return messages, len(messages)
        
        except Exception as e:
            logger.error(f"Error fetching Telegram messages: {str(e)}")
            raise Exception(f"Failed to fetch Telegram messages: {str(e)}")
    
    def _parse_telegram_message(self, msg, dialog) -> TelegramMessage:
        """Parse Telegram message into TelegramMessage model"""
        # Get sender information
        sender_name = "Unknown"
        sender_id = ""
        
        if msg.sender:
            if hasattr(msg.sender, 'first_name'):
                sender_name = msg.sender.first_name
                if hasattr(msg.sender, 'last_name') and msg.sender.last_name:
                    sender_name += f" {msg.sender.last_name}"
            if hasattr(msg.sender, 'id'):
                sender_id = str(msg.sender.id)
            if hasattr(msg.sender, 'username') and msg.sender.username:
                sender_name = f"@{msg.sender.username}"
        
        # Get chat information
        chat_name = dialog.name
        chat_id = str(dialog.id)
        
        # Get message text
        body = ""
        if msg.text:
            body = msg.text
        elif msg.media:
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
        
        # Format timestamp
        timestamp = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return TelegramMessage(
            message_id=str(msg.id),
            from_id=sender_id,
            from_name=sender_name,
            body=body,
            timestamp=timestamp,
            is_read=not msg.unread,
            chat_id=chat_id,
            chat_name=chat_name
        )
    
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

