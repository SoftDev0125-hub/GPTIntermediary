"""
Slack Service
Handles Slack message retrieval and operations using Slack Web API
"""

import logging
import os
from typing import List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

from models.schemas import SlackMessage, SlackChannel

# Try to import Slack SDK
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class SlackService:
    """Service for handling Slack operations using Slack Web API"""
    
    def __init__(self):
        """Initialize Slack service"""
        load_dotenv(override=True)
        self.bot_token = os.getenv('SLACK_BOT_TOKEN', '')
        self.user_token = os.getenv('SLACK_USER_TOKEN', '')
        
        # Prefer user token for accessing all channels the user is in
        # User tokens have access to all channels, while bot tokens only have access to channels the bot is invited to
        self.token = self.user_token or self.bot_token
        self.token_type = "user" if self.user_token else ("bot" if self.bot_token else None)
        self.client = None
        self.is_configured = bool(self.token)
        
        if not SLACK_SDK_AVAILABLE:
            logger.warning("slack_sdk not available. Install with: pip install slack_sdk")
        elif not self.is_configured:
            logger.warning("Slack API token not configured. Set SLACK_BOT_TOKEN or SLACK_USER_TOKEN in .env")
            logger.info("Note: SLACK_USER_TOKEN is recommended to access all channels in your Slack account")
        else:
            self.client = WebClient(token=self.token)
            logger.info(f"Slack service initialized with {self.token_type} token")
            if self.token_type == "bot":
                logger.info("Using bot token - bot must be invited to channels to access messages")
                logger.info("Consider using SLACK_USER_TOKEN to access all channels in your account")
    
    async def initialize(self):
        """Initialize Slack client connection"""
        if not SLACK_SDK_AVAILABLE:
            logger.warning("slack_sdk not installed. Install with: pip install slack_sdk")
            return
        
        if not self.is_configured:
            logger.warning("Slack API token not configured")
            return
        
        if not self.client:
            return
        
        try:
            # Test connection by getting auth info
            response = self.client.auth_test()
            if response["ok"]:
                team = response.get('team', 'Unknown')
                user = response.get('user', 'Unknown')
                token_type = self.token_type or "unknown"
                logger.info(f"Slack client connected. Team: {team}, User: {user}, Token type: {token_type}")
                if token_type == "user":
                    logger.info("✓ Using user token - will have access to all channels in your account")
                elif token_type == "bot":
                    logger.warning("⚠ Using bot token - only channels where bot is invited will be accessible")
            else:
                logger.warning(f"Slack auth test failed: {response.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Error initializing Slack client: {str(e)}")
    
    async def cleanup(self):
        """Cleanup resources"""
        # Slack SDK doesn't require explicit cleanup
        logger.info("Slack service cleanup completed")
    
    async def get_messages(
        self,
        limit: int = 50
    ) -> tuple[List[SlackMessage], int]:
        """
        Retrieve Slack messages from all channels and DMs
        
        Args:
            limit: Maximum number of messages to retrieve per channel
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            if not SLACK_SDK_AVAILABLE:
                raise Exception("slack_sdk not installed. Install with: pip install slack_sdk")
            
            if not self.is_configured:
                raise Exception("Slack API token not configured. Set SLACK_BOT_TOKEN or SLACK_USER_TOKEN in .env")
            
            if not self.client:
                raise Exception("Slack client not initialized")
            
            logger.info(f"Fetching up to {limit} Slack messages per channel")
            
            all_messages = []
            
            # Get all conversations (channels, DMs, groups)
            try:
                # Try to get all conversation types including DMs
                # Note: Requires 'im:read' scope for direct messages
                channels_response = self.client.conversations_list(
                    types="public_channel,private_channel,im,mpim",
                    limit=100
                )
                
                if not channels_response["ok"]:
                    error = channels_response.get('error', 'Unknown error')
                    needed_scope = channels_response.get('needed')
                    
                    # Provide helpful error message for missing scopes
                    if error == 'missing_scope' and needed_scope:
                        raise Exception(
                            f"Missing required Slack scope: '{needed_scope}'. "
                            f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                            f"then reinstall the app to your workspace. "
                            f"See SLACK_SETUP.md for detailed instructions."
                        )
                    raise Exception(f"Failed to list conversations: {error}")
                
                conversations = channels_response.get("channels", [])
                logger.info(f"Found {len(conversations)} conversations")
                
                # Get messages from each conversation - limit to first N conversations for faster loading
                max_conversations = min(30, len(conversations))  # Process max 30 conversations initially
                
                for conv in conversations[:max_conversations]:
                    try:
                        conv_id = conv["id"]
                        conv_name = conv.get("name", conv.get("user", "Unknown"))
                        conv_type = conv.get("is_im", False) and "DM" or (conv.get("is_private", False) and "Private" or "Channel")
                        
                        # Get messages from this conversation - reduced limit for faster loading
                        messages_response = self.client.conversations_history(
                            channel=conv_id,
                            limit=min(limit, 20)  # Reduced from 100 to 20 for faster loading
                        )
                        
                        if messages_response["ok"]:
                            messages = messages_response.get("messages", [])
                            
                            for msg in messages:
                                slack_msg = self._parse_slack_message(msg, conv_id, conv_name, conv_type)
                                all_messages.append(slack_msg)
                        else:
                            error = messages_response.get("error", "Unknown error")
                            # Some channels might not be accessible (e.g., private channels bot isn't in)
                            if error not in ["channel_not_found", "not_in_channel", "missing_scope"]:
                                logger.warning(f"Error getting messages from {conv_name}: {error}")
                    
                    except SlackApiError as e:
                        logger.warning(f"Slack API error for conversation {conv.get('name', conv.get('id', 'unknown'))}: {str(e)}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error processing conversation {conv.get('name', conv.get('id', 'unknown'))}: {str(e)}")
                        continue
                
                # Sort messages by timestamp (newest first)
                all_messages.sort(key=lambda x: x.timestamp, reverse=True)
                
                # Limit total messages if needed
                if len(all_messages) > limit * 10:  # Reasonable limit
                    all_messages = all_messages[:limit * 10]
                
                logger.info(f"Retrieved {len(all_messages)} Slack messages")
                return all_messages, len(all_messages)
            
            except SlackApiError as e:
                # Extract error details from Slack API response
                error_msg = None
                needed_scope = None
                
                # Try to get response data from the exception
                if hasattr(e, 'response'):
                    response = e.response
                    # Check if response has a 'data' attribute (SlackResponse object)
                    if hasattr(response, 'data') and isinstance(response.data, dict):
                        error_data = response.data
                        error_code = error_data.get('error', '')
                        needed_scope = error_data.get('needed')
                        
                        if error_code == 'missing_scope' and needed_scope:
                            error_msg = (
                                f"Missing required Slack scope: '{needed_scope}'. "
                                f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                                f"then reinstall the app to your workspace. "
                                f"See SLACK_SETUP.md for detailed instructions."
                            )
                    # Check if response is a dict directly
                    elif isinstance(response, dict):
                        error_code = response.get('error', '')
                        needed_scope = response.get('needed')
                        
                        if error_code == 'missing_scope' and needed_scope:
                            error_msg = (
                                f"Missing required Slack scope: '{needed_scope}'. "
                                f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                                f"then reinstall the app to your workspace. "
                                f"See SLACK_SETUP.md for detailed instructions."
                            )
                
                # Fallback to generic error message
                if not error_msg:
                    # Try to extract from error string
                    error_str = str(e)
                    if 'missing_scope' in error_str and 'needed' in error_str:
                        # Try to parse from the error message
                        import re
                        match = re.search(r"'needed':\s*'([^']+)'", error_str)
                        if match:
                            needed_scope = match.group(1)
                            error_msg = (
                                f"Missing required Slack scope: '{needed_scope}'. "
                                f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                                f"then reinstall the app to your workspace. "
                                f"See SLACK_SETUP.md for detailed instructions."
                            )
                    
                    if not error_msg:
                        error_msg = f"Slack API error: {str(e)}"
                
                logger.error(error_msg)
                raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Error fetching Slack messages: {str(e)}")
            raise Exception(f"Failed to fetch Slack messages: {str(e)}")
    
    async def get_channels(self) -> List[SlackChannel]:
        """
        Get list of Slack channels/conversations (without messages) - fast operation
        
        Returns:
            List of SlackChannel objects
        """
        try:
            if not SLACK_SDK_AVAILABLE:
                raise Exception("slack_sdk not installed")
            
            if not self.is_configured:
                raise Exception("Slack API token not configured")
            
            if not self.client:
                raise Exception("Slack client not initialized")
            
            logger.info("Fetching Slack channels list...")
            
            # Get all conversations (channels, DMs, groups) - this is fast, no messages loaded
            channels_response = self.client.conversations_list(
                types="public_channel,private_channel,im,mpim",
                limit=1000  # Get all conversations
            )
            
            if not channels_response["ok"]:
                raise Exception(f"Failed to list conversations: {channels_response.get('error', 'Unknown error')}")
            
            conversations = channels_response.get("channels", [])
            channels = []
            
            for conv in conversations:
                try:
                    conv_id = conv["id"]
                    conv_name = conv.get("name", conv.get("user", "Unknown"))
                    conv_type = conv.get("is_im", False) and "DM" or (conv.get("is_private", False) and "Private" or "Channel")
                    
                    # Get last message info (lightweight - just the latest message)
                    last_message = None
                    last_message_time = None
                    unread_count = 0
                    
                    try:
                        # Get only the latest message for preview
                        messages_response = self.client.conversations_history(
                            channel=conv_id,
                            limit=1
                        )
                        if messages_response["ok"]:
                            messages = messages_response.get("messages", [])
                            if messages:
                                msg = messages[0]
                                last_message = msg.get("text", "")[:100]  # First 100 chars
                                ts = msg.get("ts", "")
                                if ts:
                                    timestamp = datetime.fromtimestamp(float(ts))
                                    last_message_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        pass  # Ignore errors getting last message
                    
                    # Get unread count
                    try:
                        info_response = self.client.conversations_info(channel=conv_id)
                        if info_response["ok"]:
                            channel_info = info_response.get("channel", {})
                            unread_count = channel_info.get("unread_count", 0) or 0
                    except:
                        pass  # Ignore errors getting unread count
                    
                    channel = SlackChannel(
                        channel_id=conv_id,
                        channel_name=conv_name,
                        channel_type=conv_type,
                        last_message=last_message,
                        last_message_time=last_message_time,
                        unread_count=unread_count,
                        is_thread=False
                    )
                    channels.append(channel)
                except Exception as e:
                    logger.debug(f"Error processing conversation {conv.get('name', conv.get('id', 'unknown'))}: {e}")
                    continue
            
            logger.info(f"Retrieved {len(channels)} Slack channels")
            return channels
        
        except Exception as e:
            logger.error(f"Error fetching Slack channels: {str(e)}")
            raise Exception(f"Failed to fetch Slack channels: {str(e)}")
    
    async def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 50
    ) -> tuple[List[SlackMessage], int]:
        """
        Get messages for a specific Slack channel - on-demand loading
        
        Args:
            channel_id: The channel ID to get messages from
            limit: Maximum number of messages to retrieve
        
        Returns:
            Tuple of (list of messages, total count)
        """
        try:
            if not SLACK_SDK_AVAILABLE:
                raise Exception("slack_sdk not installed")
            
            if not self.is_configured:
                raise Exception("Slack API token not configured")
            
            if not self.client:
                raise Exception("Slack client not initialized")
            
            logger.info(f"Fetching messages for channel {channel_id} (limit: {limit})")
            
            # Get channel info for name
            channel_info_response = self.client.conversations_info(channel=channel_id)
            if not channel_info_response["ok"]:
                raise Exception(f"Failed to get channel info: {channel_info_response.get('error', 'Unknown error')}")
            
            channel_info = channel_info_response.get("channel", {})
            channel_name = channel_info.get("name", channel_info.get("user", "Unknown"))
            channel_type = channel_info.get("is_im", False) and "DM" or (channel_info.get("is_private", False) and "Private" or "Channel")
            
            # Get messages from this specific channel only
            messages_response = self.client.conversations_history(
                channel=channel_id,
                limit=limit
            )
            
            if not messages_response["ok"]:
                raise Exception(f"Failed to get messages: {messages_response.get('error', 'Unknown error')}")
            
            messages = messages_response.get("messages", [])
            all_messages = []
            
            for msg in messages:
                try:
                    slack_msg = self._parse_slack_message(msg, channel_id, channel_name, channel_type)
                    all_messages.append(slack_msg)
                except Exception as e:
                    logger.debug(f"Error parsing message: {e}")
                    continue
            
            # Sort messages by timestamp (oldest first for chat display)
            all_messages.sort(key=lambda x: x.timestamp)
            
            logger.info(f"Retrieved {len(all_messages)} messages for channel {channel_id}")
            return all_messages, len(all_messages)
        
        except Exception as e:
            logger.error(f"Error fetching messages for channel {channel_id}: {str(e)}")
            raise Exception(f"Failed to fetch messages for channel: {str(e)}")
    
    def _parse_slack_message(self, msg: dict, channel_id: str, channel_name: str, channel_type: str) -> SlackMessage:
        """Parse Slack message into SlackMessage model"""
        # Get message text
        text = msg.get("text", "")
        
        # Check for files/media
        has_media = False
        media_type = None
        media_filename = None
        media_mimetype = None
        file_id = None
        
        files = msg.get("files", [])
        if files:
            has_media = True
            file = files[0]  # Get first file
            file_id = file.get("id")
            media_filename = file.get("name")
            media_mimetype = file.get("mimetype")
            
            # Determine media type
            if file.get("mimetype", "").startswith("image/"):
                media_type = "image"
            elif file.get("mimetype", "").startswith("video/"):
                media_type = "video"
            else:
                media_type = "file"
            
            # Update text if no text but has file
            if not text:
                text = f"[{media_type.title()}] {media_filename or 'File'}"
        
        # Handle message formatting (remove Slack markdown formatting if needed)
        # For now, keep as-is
        
        # Get user information
        user_id = msg.get("user", "")
        user_name = "Unknown"
        
        if user_id:
            try:
                # Try to get user info
                user_response = self.client.users_info(user=user_id)
                if user_response["ok"]:
                    user = user_response.get("user", {})
                    user_name = user.get("real_name") or user.get("name", user_id)
            except:
                # If we can't get user info, use the user ID
                user_name = user_id
        
        # Get timestamp
        ts = msg.get("ts", "")
        if ts:
            try:
                # Slack timestamps are in Unix time with microseconds
                timestamp = datetime.fromtimestamp(float(ts))
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            except:
                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get thread information
        thread_ts = msg.get("thread_ts")
        is_thread = thread_ts is not None and thread_ts != ts
        
        # Format channel name with type
        if channel_type == "DM":
            display_channel = f"DM: {channel_name}"
        elif channel_type == "Private":
            display_channel = f"🔒 {channel_name}"
        else:
            display_channel = f"#{channel_name}"
        
        return SlackMessage(
            message_id=msg.get("ts", ""),
            from_id=user_id,
            from_name=user_name,
            body=text,
            timestamp=timestamp_str,
            channel_id=channel_id,
            channel_name=display_channel,
            is_thread=is_thread,
            thread_ts=thread_ts,
            has_media=has_media,
            media_type=media_type,
            media_url=None,  # Will be set when downloading
            media_filename=media_filename,
            media_mimetype=media_mimetype,
            file_id=file_id
        )
    
    async def send_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: Optional[str] = None
    ) -> str:
        """
        Send a message to a Slack channel or DM
        
        Args:
            channel_id: The channel ID to send the message to
            text: The message text to send
            thread_ts: Optional thread timestamp to reply to a thread
        
        Returns:
            Timestamp of the sent message
        """
        try:
            if not SLACK_SDK_AVAILABLE:
                raise Exception("slack_sdk not installed. Install with: pip install slack_sdk")
            
            if not self.is_configured:
                raise Exception("Slack API token not configured. Set SLACK_BOT_TOKEN or SLACK_USER_TOKEN in .env")
            
            if not self.client:
                raise Exception("Slack client not initialized")
            
            logger.info(f"Sending message to channel {channel_id}")
            
            # Prepare message parameters
            message_params = {
                "channel": channel_id,
                "text": text
            }
            
            # Add thread timestamp if replying to a thread
            if thread_ts:
                message_params["thread_ts"] = thread_ts
            
            # Send the message
            response = self.client.chat_postMessage(**message_params)
            
            if not response["ok"]:
                error = response.get("error", "Unknown error")
                raise Exception(f"Failed to send message: {error}")
            
            message_ts = response.get("ts", "")
            logger.info(f"Message sent successfully. Timestamp: {message_ts}")
            return message_ts
            
        except SlackApiError as e:
            error_response = e.response
            error_msg = None
            needed_scope = None
            
            if hasattr(e, 'response'):
                response = e.response
                if hasattr(response, 'data') and isinstance(response.data, dict):
                    error_data = response.data
                    error_code = error_data.get('error', '')
                    needed_scope = error_data.get('needed')
                    
                    if error_code == 'missing_scope' and needed_scope:
                        error_msg = (
                            f"Missing required Slack scope: '{needed_scope}'. "
                            f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                            f"then reinstall the app to your workspace. "
                            f"See SLACK_SETUP.md for detailed instructions."
                        )
                    else:
                        error_msg = f"Slack API error: {error_code}"
                elif isinstance(response, dict):
                    error_code = response.get('error', '')
                    needed_scope = response.get('needed')
                    
                    if error_code == 'missing_scope' and needed_scope:
                        error_msg = (
                            f"Missing required Slack scope: '{needed_scope}'. "
                            f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                            f"then reinstall the app to your workspace. "
                            f"See SLACK_SETUP.md for detailed instructions."
                        )
                    else:
                        error_msg = f"Slack API error: {error_code}"
            
            if not error_msg:
                error_str = str(e)
                if 'missing_scope' in error_str and 'needed' in error_str:
                    import re
                    match = re.search(r"'needed':\s*'([^']+)'", error_str)
                    if match:
                        needed_scope = match.group(1)
                        error_msg = (
                            f"Missing required Slack scope: '{needed_scope}'. "
                            f"Please add '{needed_scope}' to your Slack app's User Token Scopes in OAuth & Permissions, "
                            f"then reinstall the app to your workspace. "
                            f"See SLACK_SETUP.md for detailed instructions."
                        )
                
                if not error_msg:
                    error_msg = f"Slack API error: {str(e)}"
            
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Error sending Slack message: {str(e)}")
            raise Exception(f"Failed to send Slack message: {str(e)}")
    
    async def check_connection_status(self) -> Tuple[bool, str]:
        """
        Check if Slack client is connected
        
        Returns:
            Tuple of (is_connected, status_message)
        """
        if not SLACK_SDK_AVAILABLE:
            return False, "slack_sdk not installed"
        
        if not self.is_configured:
            return False, "Slack API token not configured"
        
        if not self.client:
            return False, "Slack client not initialized"
        
        try:
            response = self.client.auth_test()
            if response["ok"]:
                team = response.get("team", "Unknown")
                user = response.get("user", "Unknown")
                return True, f"Connected to {team} as {user}"
            else:
                error = response.get("error", "Unknown error")
                return False, f"Auth test failed: {error}"
        except Exception as e:
            return False, f"Error: {str(e)}"

