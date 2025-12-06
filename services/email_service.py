"""
Gmail API Service
Handles all email operations including sending, reading, and replying
"""

import os
import base64
import logging
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models.schemas import EmailMessage

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Gmail API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]


class EmailService:
    """Service for handling Gmail operations"""
    
    def __init__(self):
        # No longer needs file-based credentials
        # Credentials will be provided per-request from ChatGPT
        pass
    
    async def initialize(self):
        """Initialize Gmail API connection"""
        logger.info("Email service ready - will use credentials from ChatGPT requests")
    
    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Email service cleanup completed")
    
    def _get_service(self, access_token: str, refresh_token: Optional[str] = None):
        """Create Gmail service from user's access token"""
        try:
            creds = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=SCOPES
            )
            
            # Refresh if expired
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            
            return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            logger.error(f"Failed to create Gmail service: {str(e)}")
            raise Exception(f"Invalid credentials: {str(e)}")
    
    async def send_email(
        self,
        access_token: str,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        refresh_token: Optional[str] = None
    ) -> str:
        """
        Send an email via Gmail
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text body
            html: Optional HTML body
        
        Returns:
            Message ID of sent email
        """
        try:
            # Demo mode: only if using explicit mock credentials
            if 'mock' in access_token.lower():
                logger.info(f"📧 [DEMO MODE] Email sent to {to}")
                logger.info(f"   Subject: {subject}")
                logger.info(f"   Body: {body}")
                return f"demo-{int(__import__('time').time())}"
            
            # Get service with user credentials
            service = self._get_service(access_token, refresh_token)
            
            # Create message
            if html:
                message = MIMEMultipart('alternative')
                message.attach(MIMEText(body, 'plain'))
                message.attach(MIMEText(html, 'html'))
            else:
                message = MIMEText(body)
            
            message['To'] = to
            message['Subject'] = subject
            
            # Encode and send
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            send_message = {'raw': raw_message}
            
            result = service.users().messages().send(
                userId='me',
                body=send_message
            ).execute()
            
            logger.info(f"Email sent successfully. Message ID: {result['id']}")
            return result['id']
        
        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            raise Exception(f"Failed to send email: {error}")
    
    async def get_unread_emails(
        self,
        access_token: str,
        limit: int = 1000,
        refresh_token: Optional[str] = None
    ) -> tuple[List[EmailMessage], int]:
        """
        Retrieve unread emails
        
        Args:
            limit: Maximum number of emails to retrieve
        
        Returns:
            List of unread email messages
        """
        try:
            # Get service with user credentials
            service = self._get_service(access_token, refresh_token)
            
            # Get total unread count from system label (more accurate than page-limited list)
            label_info = service.users().labels().get(userId='me', id='UNREAD').execute()
            total_unread = label_info.get('messagesUnread', 0)

            # Query for unread messages (paged subset)
            results = service.users().messages().list(
                userId='me',
                q='is:unread',
                maxResults=limit
            ).execute()

            messages = results.get('messages', [])
            email_list = []
            
            for msg in messages:
                # Get full message details
                message = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
                
                email_data = self._parse_email(message)
                email_list.append(email_data)
            
            logger.info(f"Retrieved {len(email_list)} unread emails (total unread: {total_unread})")
            return email_list, total_unread
        
        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            raise Exception(f"Failed to fetch unread emails: {error}")
    
    async def reply_to_email(
        self,
        access_token: str,
        message_id: Optional[str] = None,
        sender_email: Optional[str] = None,
        body: str = "",
        html: Optional[str] = None,
        refresh_token: Optional[str] = None
    ) -> str:
        """
        Reply to an email
        
        Args:
            message_id: Message ID to reply to
            sender_email: Sender email to find and reply to most recent message
            body: Reply body (plain text)
            html: Optional HTML body
        
        Returns:
            Message ID of sent reply
        """
        try:
            # Get service with user credentials
            service = self._get_service(access_token, refresh_token)
            
            # If sender_email provided, find the most recent message from that sender
            if sender_email and not message_id:
                results = service.users().messages().list(
                    userId='me',
                    q=f'from:{sender_email}',
                    maxResults=1
                ).execute()
                
                messages = results.get('messages', [])
                if not messages:
                    raise Exception(f"No messages found from {sender_email}")
                
                message_id = messages[0]['id']
            
            if not message_id:
                raise Exception("Either message_id or sender_email must be provided")
            
            # Get original message
            original = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract headers
            headers = original['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            to = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            message_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')
            
            # Create reply
            if html:
                reply = MIMEMultipart('alternative')
                reply.attach(MIMEText(body, 'plain'))
                reply.attach(MIMEText(html, 'html'))
            else:
                reply = MIMEText(body)
            
            reply['To'] = to
            reply['Subject'] = f"Re: {subject}" if not subject.startswith('Re:') else subject
            reply['In-Reply-To'] = message_id_header
            reply['References'] = message_id_header
            
            # Send reply
            raw_message = base64.urlsafe_b64encode(reply.as_bytes()).decode('utf-8')
            send_message = {
                'raw': raw_message,
                'threadId': original['threadId']
            }
            
            result = service.users().messages().send(
                userId='me',
                body=send_message
            ).execute()
            
            logger.info(f"Reply sent successfully. Message ID: {result['id']}")
            return result['id']
        
        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            raise Exception(f"Failed to send reply: {error}")
    
    def _parse_email(self, message: dict) -> EmailMessage:
        """Parse Gmail API message into EmailMessage model"""
        headers = message['payload']['headers']
        
        # Extract headers
        from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        date = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
        
        # Parse from header
        from_email = from_header
        from_name = None
        if '<' in from_header:
            from_name = from_header.split('<')[0].strip().strip('"')
            from_email = from_header.split('<')[1].strip('>')
        
        # Extract body
        body = self._get_message_body(message['payload'])
        
        # Check if unread
        is_unread = 'UNREAD' in message.get('labelIds', [])
        
        return EmailMessage(
            message_id=message['id'],
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body=body,
            date=date,
            is_unread=is_unread,
            labels=message.get('labelIds', [])
        )
    
    def _get_message_body(self, payload: dict) -> str:
        """Extract body text from message payload"""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8')
        
        if 'body' in payload and 'data' in payload['body']:
            data = payload['body']['data']
            return base64.urlsafe_b64decode(data).decode('utf-8')
        
        return ""
