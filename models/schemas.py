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
