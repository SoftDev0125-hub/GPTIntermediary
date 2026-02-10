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

from pathlib import Path
from models.schemas import EmailMessage

# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_load_env_root / '.env')

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
    
    def _get_service(self, access_token: str, refresh_token: Optional[str] = None,
                     google_client_id: Optional[str] = None, google_client_secret: Optional[str] = None):
        """Create Gmail service from user's access token. Refreshes token when possible."""
        try:
            access_token = (access_token or '').strip() or None
            refresh_token = (refresh_token or '').strip() or None

            client_id = (google_client_id or os.getenv('GOOGLE_CLIENT_ID') or '').strip() or None
            client_secret = (google_client_secret or os.getenv('GOOGLE_CLIENT_SECRET') or '').strip() or None

            if not client_id or not client_secret:
                raise Exception("Google Client ID and Client Secret are required. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env or Settings.")

            creds = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=SCOPES
            )

            # Always refresh when we have a refresh_token so we use a valid access token.
            if refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Gmail token refreshed successfully")
                    # Persist new access token to project root .env so next request can use it
                    try:
                        env_path = _load_env_root / '.env'
                        if env_path.exists():
                            with open(env_path, 'r', encoding='utf-8') as f:
                                lines = f.readlines()
                            with open(env_path, 'w', encoding='utf-8') as f:
                                for line in lines:
                                    if line.strip().startswith('USER_ACCESS_TOKEN='):
                                        f.write(f'USER_ACCESS_TOKEN={creds.token}\n')
                                    else:
                                        f.write(line)
                            logger.debug("Updated USER_ACCESS_TOKEN in .env")
                    except Exception as env_err:
                        logger.debug(f"Could not update .env with new token: {env_err}")
                except Exception as refresh_error:
                    error_str = str(refresh_error)
                    logger.error(f"Failed to refresh Gmail token: {error_str}")
                    if 'invalid_grant' in error_str.lower() or 'expired' in error_str.lower() or 'revoked' in error_str.lower():
                        raise Exception(
                            "Gmail token has expired or been revoked. Re-authenticate: run from project backend/python: python get_gmail_token.py"
                        )
                    raise Exception(f"Token refresh failed: {error_str}. Re-run: python get_gmail_token.py")

            return build('gmail', 'v1', credentials=creds, cache_discovery=False)
        except Exception as e:
            logger.error(f"Failed to create Gmail service: {str(e)}")
            raise Exception(f"Invalid credentials: {str(e)}")
    
    async def send_email(
        self,
        access_token: str,
        to: List[str] | str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        refresh_token: Optional[str] = None,
        google_client_id: Optional[str] = None,
        google_client_secret: Optional[str] = None,
        from_email: Optional[str] = None
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
            
            # Get service with user credentials (client id/secret required for token refresh)
            service = self._get_service(
                access_token, refresh_token,
                google_client_id=google_client_id,
                google_client_secret=google_client_secret,
            )
            
            # Create message
            # Normalize recipients: accept single string or list
            from email.utils import parseaddr
            to_list: List[str] = []
            if isinstance(to, str):
                raw_recipients = [to]
            else:
                raw_recipients = to

            for raw in raw_recipients:
                _name, _email = parseaddr(raw or '')
                _email = _email.strip() if _email else ''
                if not _email or '@' not in _email:
                    logger.error(f"Invalid recipient in list, skipping: {raw}")
                    continue
                to_list.append(_email)

            if not to_list:
                raise Exception(f"No valid recipient email addresses provided: {to}")

            if html:
                message = MIMEMultipart('alternative')
                message.attach(MIMEText(body, 'plain'))
                message.attach(MIMEText(html, 'html'))
            else:
                message = MIMEText(body)

            # Use the normalized email addresses in the To header
            message['To'] = ', '.join(to_list)
            # If provided, set the From header to the sender email (helps Gmail validate the message)
            if from_email:
                message['From'] = from_email
            else:
                # Try to determine authenticated user's email from Gmail profile
                try:
                    profile = service.users().getProfile(userId='me').execute()
                    profile_email = profile.get('emailAddress') if isinstance(profile, dict) else None
                    if profile_email:
                        message['From'] = profile_email
                        logger.info(f"Using authenticated Gmail profile email as From: {profile_email}")
                    else:
                        logger.warning("Could not determine sender email from Gmail profile; 'From' header left unset")
                except Exception as e:
                    logger.warning(f"Failed to fetch Gmail profile for From header: {e}")
            message['Subject'] = subject
            # Additional logging and safety check
            from_addr = message.get('From')
            to_header = message.get('To')
            logger.info(f"Prepared message headers. From: {from_addr}, To header: {to_header}, recipients: {to_list}")

            # Prevent accidental sends to self when recipient resolution failed
            try:
                normalized_from = from_addr.strip().lower() if from_addr else None
                normalized_recipients = set([r.strip().lower() for r in to_list])
                if normalized_from and normalized_recipients == {normalized_from}:
                    raise Exception("Resolved recipient(s) equal the sender email; aborting to avoid sending to self. Check contact lookup results.")
            except Exception as safety_err:
                logger.error(f"Safety check failed: {safety_err}")
                raise

            # Encode and send
            logger.info(f"Sending message From: {from_addr} To: {to_header}")
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            send_message = {'raw': raw_message}
            
            result = service.users().messages().send(
                userId='me',
                body=send_message
            ).execute()
            
            logger.info(f"Email sent successfully. Message ID: {result['id']}")
            return result['id']
        
        except HttpError as error:
            try:
                raw_preview = message.as_string()[:500]
            except Exception:
                raw_preview = None
            logger.error(f"Gmail API error: {error}")
            raise Exception(f"Failed to send email: {error}. RawPreview: {raw_preview}")
    
    async def get_unread_emails(
        self,
        access_token: str,
        limit: int = 1000,
        refresh_token: Optional[str] = None,
        google_client_id: Optional[str] = None,
        google_client_secret: Optional[str] = None,
        query: Optional[str] = None
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
            service = self._get_service(access_token, refresh_token, google_client_id, google_client_secret)
            
            # Get total unread count from system label (more accurate than page-limited list)
            # Add timeout handling
            try:
                label_info = service.users().labels().get(userId='me', id='UNREAD').execute()
                total_unread = label_info.get('messagesUnread', 0)
            except Exception as label_error:
                logger.warning(f"Could not get unread count: {str(label_error)}")
                total_unread = 0

            # Query for unread messages (paged) with timeout handling
            # Use provided query (e.g., 'in:inbox category:primary is:unread') or default to unread
            list_query = query or 'is:unread'
            try:
                message_ids = []
                page_token = None
                # Gmail API returns paged results; loop until we have enough or no more pages
                while True:
                    params = {
                        'userId': 'me',
                        'q': list_query,
                        'maxResults': min(500, max(1, limit))
                    }
                    if page_token:
                        params['pageToken'] = page_token

                    results = service.users().messages().list(**params).execute()
                    page_msgs = results.get('messages', []) or []
                    for m in page_msgs:
                        if len(message_ids) >= limit:
                            break
                        message_ids.append(m.get('id'))

                    page_token = results.get('nextPageToken')
                    if not page_token or len(message_ids) >= limit:
                        break
            except Exception as list_error:
                error_msg = str(list_error)
                if 'timeout' in error_msg.lower() or '10060' in error_msg:
                    logger.error("Gmail API timeout - network connection issue")
                    raise Exception("Connection timeout. Please check your internet connection and try again.")
                else:
                    raise

            email_list = []
            # Fetch full message bodies for the collected ids (respect limit)
            for mid in message_ids[:limit]:
                try:
                    message = service.users().messages().get(
                        userId='me',
                        id=mid,
                        format='full'
                    ).execute()
                except Exception as msg_error:
                    logger.warning(f"Failed to fetch message {mid}: {msg_error}")
                    continue

                email_data = self._parse_email(message)
                email_list.append(email_data)
            
            # Attempt to sort emails by parsed date (newest first)
            try:
                from email.utils import parsedate_to_datetime
                def _parse_dt(e):
                    try:
                        return parsedate_to_datetime(e.date)
                    except Exception:
                        return None

                email_list_sorted = sorted(email_list, key=lambda e: _parse_dt(e) or datetime.min, reverse=True)
            except Exception:
                email_list_sorted = email_list

            logger.info(f"Retrieved {len(email_list_sorted)} unread emails (total unread: {total_unread})")
            return email_list_sorted, total_unread
        
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
        refresh_token: Optional[str] = None,
        google_client_id: Optional[str] = None,
        google_client_secret: Optional[str] = None
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
            service = self._get_service(access_token, refresh_token, google_client_id, google_client_secret)
            
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
    
    async def mark_email_as_read(
        self,
        access_token: str,
        message_id: str,
        refresh_token: Optional[str] = None,
        google_client_id: Optional[str] = None,
        google_client_secret: Optional[str] = None
    ) -> None:
        """
        Mark an email as read in Gmail
        
        Args:
            access_token: User's Gmail access token
            message_id: ID of the message to mark as read
            refresh_token: Optional refresh token for token renewal
        """
        try:
            # Get service with user credentials
            service = self._get_service(access_token, refresh_token, google_client_id, google_client_secret)
            
            # Remove UNREAD label to mark as read
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            
            logger.info(f"Email {message_id} marked as read")
        
        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            raise Exception(f"Failed to mark email as read: {error}")
    
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
        """Extract body from message payload, preferring HTML for better formatting"""
        html_body = None
        plain_body = None
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and not plain_body:
                    data = part['body'].get('data', '')
                    if data:
                        plain_body = base64.urlsafe_b64decode(data).decode('utf-8')
                elif part['mimeType'] == 'text/html' and not html_body:
                    data = part['body'].get('data', '')
                    if data:
                        html_body = base64.urlsafe_b64decode(data).decode('utf-8')
        
        if not html_body and not plain_body and 'body' in payload and 'data' in payload['body']:
            data = payload['body']['data']
            decoded = base64.urlsafe_b64decode(data).decode('utf-8')
            # Check if it looks like HTML
            if '<' in decoded and '>' in decoded:
                html_body = decoded
            else:
                plain_body = decoded
        
        # Return HTML if available (for Gmail-like rendering), otherwise plain text
        body = html_body or plain_body or ""
        return body.strip()
