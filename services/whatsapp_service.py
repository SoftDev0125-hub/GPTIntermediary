"""
WhatsApp Service
Handles WhatsApp message retrieval and operations using WhatsApp Cloud API (Meta)
"""

import logging
import os
import aiohttp
import asyncio
from typing import List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

from models.schemas import WhatsAppMessage

load_dotenv()
logger = logging.getLogger(__name__)

# WhatsApp Cloud API Configuration
WHATSAPP_API_VERSION = "v21.0"  # Update to latest version
WHATSAPP_API_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


class WhatsAppService:
    """Service for handling WhatsApp operations using WhatsApp Cloud API"""
    
    def __init__(self):
        """Initialize WhatsApp service"""
        load_dotenv(override=True)
        self.access_token = os.getenv('WHATSAPP_ACCESS_TOKEN', '')
        self.phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
        self.business_account_id = os.getenv('WHATSAPP_BUSINESS_ACCOUNT_ID', '')
        self.app_id = os.getenv('WHATSAPP_APP_ID', '')
        self.app_secret = os.getenv('WHATSAPP_APP_SECRET', '')
        
        self.is_configured = bool(self.access_token and self.phone_number_id)
        
        if not self.is_configured:
            logger.warning("WhatsApp Cloud API not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID in .env")
        else:
            logger.info("WhatsApp Cloud API service initialized")
    
    async def initialize(self):
        """Initialize WhatsApp Cloud API connection"""
        if not self.is_configured:
            logger.warning("WhatsApp Cloud API credentials not configured")
            return
        
        # Verify credentials by making a test API call
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}"
                headers = {
                    'Authorization': f'Bearer {self.access_token}'
                }
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        logger.info("WhatsApp Cloud API connection verified")
                    else:
                        error_text = await response.text()
                        logger.error(f"WhatsApp Cloud API verification failed: {error_text}")
        except Exception as e:
            logger.error(f"Error verifying WhatsApp Cloud API: {str(e)}")
    
    async def cleanup(self):
        """Cleanup resources"""
        logger.info("WhatsApp service cleanup completed")
    
    async def get_messages(
        self,
        limit: int = 50,
        access_token: Optional[str] = None
    ) -> tuple[List[WhatsAppMessage], int]:
        """
        Retrieve WhatsApp messages from Cloud API
        
        Args:
            limit: Maximum number of messages to retrieve
            access_token: Optional access token (overrides env if provided)
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            if not self.is_configured and not access_token:
                logger.warning("WhatsApp Cloud API not configured")
                return [], 0
            
            token = access_token or self.access_token
            if not token:
                raise Exception("WhatsApp access token not provided")
            
            logger.info(f"Fetching {limit} WhatsApp messages from Cloud API")
            
            # Get conversations/messages from WhatsApp Cloud API
            messages = await self._fetch_messages_from_api(token, limit)
            
            logger.info(f"Retrieved {len(messages)} WhatsApp messages")
            return messages, len(messages)
        
        except Exception as e:
            logger.error(f"Error fetching WhatsApp messages: {str(e)}")
            raise Exception(f"Failed to fetch WhatsApp messages: {str(e)}")
    
    async def _fetch_messages_from_api(self, access_token: str, limit: int) -> List[WhatsAppMessage]:
        """Fetch messages from WhatsApp Cloud API"""
        messages = []
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {access_token}'
                }
                
                # WhatsApp Cloud API: Get conversations
                # Note: This endpoint may require specific permissions
                conversations_url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}/conversations"
                
                try:
                    async with session.get(
                        conversations_url, 
                        headers=headers, 
                        params={'limit': limit, 'fields': 'id,participants'}
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            conversations = data.get('data', [])
                            
                            logger.info(f"Found {len(conversations)} conversations")
                            
                            # For each conversation, get latest message
                            for conv in conversations[:limit]:
                                try:
                                    conversation_id = conv.get('id', '')
                                    participants = conv.get('participants', {}).get('data', [])
                                    
                                    if not participants:
                                        continue
                                    
                                    participant = participants[0]
                                    participant_name = participant.get('name', 'Unknown')
                                    participant_wa_id = participant.get('wa_id', '')
                                    
                                    # Get messages for this conversation
                                    messages_url = f"{WHATSAPP_API_BASE_URL}/{conversation_id}/messages"
                                    async with session.get(
                                        messages_url, 
                                        headers=headers, 
                                        params={'limit': 1, 'fields': 'id,from,timestamp,type,text,status'}
                                    ) as msg_response:
                                        if msg_response.status == 200:
                                            msg_data = await msg_response.json()
                                            msg_list = msg_data.get('data', [])
                                            
                                            if msg_list:
                                                latest_msg = msg_list[0]
                                                message = self._parse_cloud_api_message(
                                                    latest_msg, 
                                                    participant_name, 
                                                    participant_wa_id, 
                                                    conversation_id
                                                )
                                                messages.append(message)
                                        elif msg_response.status == 404:
                                            # Conversation might not have messages yet
                                            logger.debug(f"No messages in conversation {conversation_id}")
                                        else:
                                            error_text = await msg_response.text()
                                            logger.warning(f"Error getting messages for conversation {conversation_id}: {error_text}")
                                except Exception as conv_error:
                                    logger.warning(f"Error processing conversation: {str(conv_error)}")
                                    continue
                        elif response.status == 403:
                            error_text = await response.text()
                            logger.error(f"Permission denied: {error_text}")
                            raise Exception("WhatsApp API permission denied. Check your access token permissions.")
                        elif response.status == 401:
                            error_text = await response.text()
                            logger.error(f"Unauthorized: {error_text}")
                            raise Exception("Invalid access token. Please check your WHATSAPP_ACCESS_TOKEN.")
                        else:
                            error_text = await response.text()
                            logger.error(f"WhatsApp API error ({response.status}): {error_text}")
                            # Try alternative: return empty list with helpful message
                            raise Exception(f"WhatsApp API error: {error_text}")
                except aiohttp.ClientError as http_error:
                    logger.error(f"HTTP error: {str(http_error)}")
                    raise Exception(f"Network error connecting to WhatsApp API: {str(http_error)}")
        
        except Exception as e:
            # Re-raise if it's already a formatted exception
            if "WhatsApp API" in str(e) or "Network error" in str(e):
                raise
            # Otherwise wrap it
            logger.error(f"Unexpected error fetching messages: {str(e)}")
            raise Exception(f"Failed to fetch messages: {str(e)}")
        
        return messages
    
    def _parse_cloud_api_message(self, raw_message: dict, participant_name: str, participant_wa_id: str, conversation_id: str) -> WhatsAppMessage:
        """Parse WhatsApp Cloud API message into WhatsAppMessage model"""
        message_id = raw_message.get('id', '')
        timestamp = raw_message.get('timestamp', '')
        
        # Convert timestamp to readable format
        if timestamp:
            try:
                dt = datetime.fromtimestamp(int(timestamp))
                timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                timestamp_str = timestamp
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get message body
        body = ''
        msg_type = raw_message.get('type', '')
        
        if msg_type == 'text':
            body = raw_message.get('text', {}).get('body', '')
        elif msg_type == 'image':
            body = f"[Image] {raw_message.get('image', {}).get('caption', '')}"
        elif msg_type == 'video':
            body = "[Video]"
        elif msg_type == 'audio':
            body = "[Audio]"
        elif msg_type == 'document':
            body = f"[Document] {raw_message.get('document', {}).get('filename', '')}"
        else:
            body = f"[{msg_type}]"
        
        return WhatsAppMessage(
            message_id=message_id,
            from_number=participant_wa_id,
            from_name=participant_name,
            body=body,
            timestamp=timestamp_str,
            is_read=raw_message.get('status') == 'read',
            chat_id=conversation_id,
            chat_name=participant_name
        )
    
    async def get_qr_code(self) -> Optional[str]:
        """
        Get QR code for WhatsApp Cloud API setup
        Note: Cloud API doesn't use QR codes - this is for initial setup only
        """
        if not self.is_configured:
            return None
        
        # WhatsApp Cloud API doesn't use QR codes
        # QR codes are only for WhatsApp Web
        # Return None to indicate setup is done via API credentials
        return None
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check if WhatsApp Cloud API is connected
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        if not self.is_configured:
            return False, "WhatsApp Cloud API not configured. Please set credentials in .env file"
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{WHATSAPP_API_BASE_URL}/{self.phone_number_id}"
                headers = {
                    'Authorization': f'Bearer {self.access_token}'
                }
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return True, "Connected to WhatsApp Cloud API"
                    else:
                        error_text = await response.text()
                        return False, f"Connection failed: {error_text}"
        except Exception as e:
            return False, f"Error checking connection: {str(e)}"
