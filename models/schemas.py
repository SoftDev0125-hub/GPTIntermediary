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


# Word Document Models
class CreateWordDocumentRequest(BaseModel):
    """Request model for creating a Word document"""
    file_path: str = Field(..., description="Path where the document should be saved")
    content: Optional[str] = Field(None, description="Optional initial content for the document")
    title: Optional[str] = Field(None, description="Optional document title")


class OpenWordDocumentRequest(BaseModel):
    """Request model for opening a Word document"""
    file_path: str = Field(..., description="Path to the document")


class AddTextToWordRequest(BaseModel):
    """Request model for adding text to a Word document"""
    file_path: str = Field(..., description="Path to the document")
    text: str = Field(..., description="Text to add")
    bold: bool = Field(False, description="Make text bold")
    italic: bool = Field(False, description="Make text italic")
    underline: bool = Field(False, description="Underline text")
    font_name: Optional[str] = Field(None, description="Font name (e.g., 'Arial', 'Times New Roman')")
    font_size: Optional[int] = Field(None, description="Font size in points")
    color: Optional[str] = Field(None, description="Text color in hex format (e.g., '#FF0000' for red)")


class FormatParagraphRequest(BaseModel):
    """Request model for formatting a paragraph in a Word document"""
    file_path: str = Field(..., description="Path to the document")
    paragraph_index: int = Field(..., description="Index of the paragraph to format (0-based)")
    alignment: Optional[str] = Field(None, description="Paragraph alignment: 'left', 'center', 'right', 'justify'")
    line_spacing: Optional[float] = Field(None, description="Line spacing (e.g., 1.5, 2.0)")
    space_before: Optional[float] = Field(None, description="Space before paragraph in points")
    space_after: Optional[float] = Field(None, description="Space after paragraph in points")
    left_indent: Optional[float] = Field(None, description="Left indent in inches")
    right_indent: Optional[float] = Field(None, description="Right indent in inches")


class AddHeadingRequest(BaseModel):
    """Request model for adding a heading to a Word document"""
    file_path: str = Field(..., description="Path to the document")
    text: str = Field(..., description="Heading text")
    level: int = Field(1, description="Heading level (1-9)")


class AddListRequest(BaseModel):
    """Request model for adding a list to a Word document"""
    file_path: str = Field(..., description="Path to the document")
    items: List[str] = Field(..., description="List of items to add")
    numbered: bool = Field(False, description="True for numbered list, False for bulleted list")


class AddTableRequest(BaseModel):
    """Request model for adding a table to a Word document"""
    file_path: str = Field(..., description="Path to the document")
    rows: int = Field(..., description="Number of rows")
    cols: int = Field(..., description="Number of columns")
    data: Optional[List[List[str]]] = Field(None, description="Optional 2D list of data to populate the table")
    header_row: bool = Field(False, description="Whether the first row should be formatted as a header")


class FindReplaceRequest(BaseModel):
    """Request model for find and replace in a Word document"""
    file_path: str = Field(..., description="Path to the document")
    find_text: str = Field(..., description="Text to find")
    replace_text: str = Field(..., description="Text to replace with")
    replace_all: bool = Field(True, description="Whether to replace all occurrences")


class PageSetupRequest(BaseModel):
    """Request model for setting page setup in a Word document"""
    file_path: str = Field(..., description="Path to the document")
    margins: Optional[Dict[str, float]] = Field(None, description="Dictionary with margin values in inches (top, bottom, left, right)")
    orientation: Optional[str] = Field(None, description="Page orientation: 'portrait' or 'landscape'")
    page_size: Optional[str] = Field(None, description="Page size: 'Letter', 'A4', 'Legal', 'A3', 'A5'")


class SaveWordDocumentRequest(BaseModel):
    """Request model for saving a Word document"""
    file_path: str = Field(..., description="Current path to the document")
    new_path: Optional[str] = Field(None, description="Optional new path to save as")


class WordDocumentInfoResponse(BaseModel):
    """Response model for Word document information"""
    success: bool
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    paragraph_count: Optional[int] = None
    table_count: Optional[int] = None
    section_count: Optional[int] = None
    preview: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class SaveWordHTMLRequest(BaseModel):
    """Request model for saving HTML content to Word document with formatting"""
    file_path: str = Field(..., description="Path where the document should be saved")
    html_content: str = Field(..., description="HTML content from contenteditable div")