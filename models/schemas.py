"""
Pydantic models for request/response validation
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class UserCredentials(BaseModel):
    """User credentials passed from ChatGPT"""
    access_token: str = Field(..., description="OAuth access token from user's ChatGPT session")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    email: Optional[str] = Field(None, description="User's email address")


class SendEmailRequest(BaseModel):
    """Request model for sending emails"""
    user_credentials: UserCredentials = Field(..., description="User's OAuth credentials from ChatGPT")
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text)")
    html: Optional[str] = Field(None, description="HTML version of the email body")


class EmailReplyRequest(BaseModel):
    """Request model for replying to emails"""
    user_credentials: UserCredentials = Field(..., description="User's OAuth credentials from ChatGPT")
    message_id: Optional[str] = Field(None, description="Message ID to reply to")
    sender_email: Optional[str] = Field(None, description="Sender email address to find and reply to")
    body: str = Field(..., description="Reply body (plain text)")
    html: Optional[str] = Field(None, description="HTML version of the reply")


class LaunchAppRequest(BaseModel):
    """Request model for launching applications"""
    app_name: str = Field(..., description="Name or path of the application to launch")
    args: Optional[List[str]] = Field(None, description="Arguments to pass to the application")


class EmailMessage(BaseModel):
    """Email message model"""
    message_id: str
    from_email: str
    from_name: Optional[str] = None
    subject: str
    body: str
    date: str
    is_unread: bool = True
    labels: List[str] = []


class EmailListResponse(BaseModel):
    """Response model for email list operations"""
    success: bool
    count: int
    total_unread: int
    emails: List[EmailMessage]


class OperationResponse(BaseModel):
    """Generic operation response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class TelegramMessage(BaseModel):
    """Telegram message model"""
    message_id: str
    from_id: str
    from_name: Optional[str] = None
    body: str
    timestamp: str
    is_read: bool = False
    is_sent: bool = False  # True if sent by current user, False if received
    chat_id: Optional[str] = None
    chat_name: Optional[str] = None


class GetTelegramMessagesRequest(BaseModel):
    """Request model for getting Telegram messages"""
    limit: int = 50


class TelegramListResponse(BaseModel):
    """Response model for Telegram message list operations"""
    success: bool
    count: int
    total_count: int
    messages: List[TelegramMessage]


class SendTelegramMessageRequest(BaseModel):
    """Request model for sending Telegram messages"""
    chat_id: str = Field(..., description="Chat ID to send the message to")
    text: str = Field(..., description="Message text to send")
    reply_to_message_id: Optional[str] = Field(None, description="Optional message ID to reply to")


class SendTelegramMessageResponse(BaseModel):
    """Response model for sending Telegram messages"""
    success: bool
    message_id: str
    message: str


class SlackMessage(BaseModel):
    """Slack message model"""
    message_id: str
    from_id: str
    from_name: Optional[str] = None
    body: str
    timestamp: str
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    is_thread: bool = False
    thread_ts: Optional[str] = None


class GetSlackMessagesRequest(BaseModel):
    """Request model for getting Slack messages"""
    limit: int = 50


class SlackListResponse(BaseModel):
    """Response model for Slack message list operations"""
    success: bool
    count: int
    total_count: int
    messages: List[SlackMessage]


class SendSlackMessageRequest(BaseModel):
    """Request model for sending Slack messages"""
    channel_id: str
    text: str
    thread_ts: Optional[str] = None


class SendSlackMessageResponse(BaseModel):
    """Response model for sending Slack messages"""
    success: bool
    message: str
    message_ts: Optional[str] = None