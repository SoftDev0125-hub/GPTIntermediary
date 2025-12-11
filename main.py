"""
ChatGPT Backend/Broker - Main Application Entry Point
Handles email operations, app launching, and other automation tasks
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel
from typing import Optional, List
import logging
import os

from services.email_service import EmailService
from services.app_launcher import AppLauncher
from services.whatsapp_service import WhatsAppService
from services.telegram_service import TelegramService
from services.slack_service import SlackService
from models.schemas import (
    SendEmailRequest, 
    EmailReplyRequest, 
    LaunchAppRequest,
    EmailListResponse,
    OperationResponse,
    UserCredentials,
    GetWhatsAppMessagesRequest,
    WhatsAppListResponse,
    GetTelegramMessagesRequest,
    TelegramListResponse,
    GetSlackMessagesRequest,
    SlackListResponse,
    SendSlackMessageRequest,
    SendSlackMessageResponse
)
from pydantic import BaseModel


class GetUnreadEmailsRequest(BaseModel):
    """Request model for getting unread emails"""
    user_credentials: UserCredentials
    limit: int = 1000


class MarkEmailReadRequest(BaseModel):
    """Request model for marking an email as read"""
    user_credentials: UserCredentials
    message_id: str

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="ChatGPT Backend Broker",
    description="Backend service for ChatGPT to handle emails and app launching",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
email_service = EmailService()
app_launcher = AppLauncher()
whatsapp_service = WhatsAppService()
telegram_service = TelegramService()
slack_service = SlackService()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting ChatGPT Backend Broker...")
    
    # Check for Gmail credentials
    access_token = os.getenv('USER_ACCESS_TOKEN', '').strip()
    refresh_token = os.getenv('USER_REFRESH_TOKEN', '').strip()
    
    if not access_token or not refresh_token or access_token == 'your_token_here' or refresh_token == 'your_token_here':
        logger.warning("=" * 70)
        logger.warning("[!] GMAIL SETUP REQUIRED")
        logger.warning("=" * 70)
        logger.warning("No Gmail account is registered in this app!")
        logger.warning("")
        logger.warning("To use email features, run this command FIRST:")
        logger.warning("  python get_gmail_token.py")
        logger.warning("")
        logger.warning("This will authorize your Gmail account and save tokens to .env")
        logger.warning("=" * 70)
    
    await email_service.initialize()
    await whatsapp_service.initialize()
    await telegram_service.initialize()
    await slack_service.initialize()
    logger.info("Services initialized successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down ChatGPT Backend Broker...")
    await email_service.cleanup()
    await whatsapp_service.cleanup()
    await telegram_service.cleanup()
    await slack_service.cleanup()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "ChatGPT Backend Broker",
        "version": "1.0.0"
    }


@app.post("/api/email/send", response_model=OperationResponse)
async def send_email(request: SendEmailRequest):
    """
    Send an email via Gmail using user's credentials from ChatGPT
    
    Args:
        request: Email details including user credentials, recipient, subject, and body
    
    Returns:
        Operation status and message ID
    """
    try:
        logger.info(f"Sending email to {request.to}")
        message_id = await email_service.send_email(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            to=request.to,
            subject=request.subject,
            body=request.body,
            html=request.html
        )
        return OperationResponse(
            success=True,
            message=f"Email sent successfully to {request.to}",
            data={"message_id": message_id}
        )
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/email/test")
async def test_email():
    """Test email service connectivity"""
    try:
        logger.info("Testing email service...")
        from services.email_service import EmailService
        service = EmailService()
        
        # Try to get service with test token
        test_access = os.getenv('USER_ACCESS_TOKEN')
        test_refresh = os.getenv('USER_REFRESH_TOKEN')
        
        logger.info(f"Access token present: {bool(test_access)}")
        logger.info(f"Refresh token present: {bool(test_refresh)}")
        
        if not test_access or not test_refresh:
            return {
                "success": False,
                "error": "Tokens missing from environment"
            }
        
        # Try a simple API call
        try:
            test_service = service._get_service(test_access, test_refresh)
            logger.info("Gmail service created successfully")
            
            # Try to list labels (simple test)
            result = test_service.users().labels().list(userId='me').execute()
            logger.info(f"Gmail API working - found {len(result.get('labels', []))} labels")
            
            return {
                "success": True,
                "message": "Email service working",
                "labels_count": len(result.get('labels', []))
            }
        except Exception as api_error:
            logger.error(f"Gmail API error: {str(api_error)}")
            return {
                "success": False,
                "error": f"Gmail API error: {str(api_error)}"
            }
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e)
        }


@app.post("/api/email/unread", response_model=EmailListResponse)
async def get_unread_emails(request: GetUnreadEmailsRequest):
    """
    Retrieve unread emails from Gmail using user's credentials from ChatGPT
    
    Args:
        request: User credentials and limit for emails to retrieve
    
    Returns:
        List of unread emails
    """
    try:
        logger.info(f"Fetching {request.limit} unread emails")
        emails, total_unread = await email_service.get_unread_emails(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            limit=request.limit
        )
        logger.info(f"Successfully retrieved {len(emails)} emails")
        return EmailListResponse(
            success=True,
            count=len(emails),
            total_unread=total_unread,
            emails=emails
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching unread emails: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Check for invalid_scope error and provide helpful message
        if "invalid_scope" in error_msg.lower():
            error_msg = "Gmail OAuth scopes mismatch. Please run: python get_gmail_token.py to reauthorize with correct scopes."
        
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/email/reply", response_model=OperationResponse)
async def reply_to_email(request: EmailReplyRequest):
    """
    Reply to a specific email using user's credentials from ChatGPT
    
    Args:
        request: Reply details including user credentials, message ID or sender email
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Replying to email from {request.sender_email or request.message_id}")
        message_id = await email_service.reply_to_email(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            message_id=request.message_id,
            sender_email=request.sender_email,
            body=request.body,
            html=request.html
        )
        return OperationResponse(
            success=True,
            message="Reply sent successfully",
            data={"message_id": message_id}
        )
    except Exception as e:
        logger.error(f"Error replying to email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/mark-read", response_model=OperationResponse)
async def mark_email_read(request: MarkEmailReadRequest):
    """
    Mark an email as read in Gmail
    
    Args:
        request: User credentials and message ID to mark as read
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Marking email {request.message_id} as read")
        await email_service.mark_email_as_read(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            message_id=request.message_id
        )
        return OperationResponse(
            success=True,
            message="Email marked as read",
            data={"message_id": request.message_id}
        )
    except Exception as e:
        logger.error(f"Error marking email as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/app/launch", response_model=OperationResponse)
async def launch_app(request: LaunchAppRequest):
    """
    Launch an application on the system
    
    Args:
        request: App name or path to launch
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Launching app: {request.app_name}")
        success = await app_launcher.launch_app(
            app_name=request.app_name,
            args=request.args
        )
        
        if success:
            return OperationResponse(
                success=True,
                message=f"Successfully launched {request.app_name}"
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Application '{request.app_name}' not found"
            )
    except Exception as e:
        logger.error(f"Error launching app: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/whatsapp/messages", response_model=WhatsAppListResponse)
async def get_whatsapp_messages(request: GetWhatsAppMessagesRequest):
    """
    Retrieve WhatsApp messages
    
    Args:
        request: Limit and optional access token for WhatsApp API
    
    Returns:
        List of WhatsApp messages
    """
    try:
        logger.info(f"Fetching {request.limit} WhatsApp messages")
        messages, total_count = await whatsapp_service.get_messages(
            limit=request.limit,
            access_token=request.access_token
        )
        logger.info(f"Successfully retrieved {len(messages)} WhatsApp messages")
        return WhatsAppListResponse(
            success=True,
            count=len(messages),
            total_count=total_count,
            messages=messages
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching WhatsApp messages: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/whatsapp/qr-code")
async def get_whatsapp_qr_code():
    """
    Get WhatsApp QR code for scanning
    Note: WhatsApp Cloud API doesn't use QR codes - setup is done via API credentials
    
    Returns:
        Message indicating Cloud API setup method
    """
    try:
        # WhatsApp Cloud API doesn't use QR codes
        # Check connection status instead
        is_connected, status = await whatsapp_service.check_connection_status()
        if is_connected:
            return {
                "success": False, 
                "message": "WhatsApp Cloud API is connected. No QR code needed.",
                "connected": True,
                "uses_cloud_api": True
            }
        else:
            return {
                "success": False,
                "message": "WhatsApp Cloud API not configured. Please set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID in .env file. See WHATSAPP_CLOUD_API_SETUP.md for instructions.",
                "connected": False,
                "uses_cloud_api": True
            }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error checking WhatsApp status: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/whatsapp/status")
async def get_whatsapp_status():
    """
    Check WhatsApp connection status
    
    Returns:
        Connection status
    """
    try:
        is_connected, status_message = await whatsapp_service.check_connection_status()
        return {
            "success": True,
            "connected": is_connected,
            "message": status_message
        }
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/messages", response_model=TelegramListResponse)
async def get_telegram_messages(request: GetTelegramMessagesRequest):
    """
    Retrieve Telegram messages
    
    Args:
        request: Limit for messages to retrieve
    
    Returns:
        List of Telegram messages
    """
    try:
        logger.info(f"Fetching {request.limit} Telegram messages")
        messages, total_count = await telegram_service.get_messages(
            limit=request.limit
        )
        logger.info(f"Successfully retrieved {len(messages)} Telegram messages")
        return TelegramListResponse(
            success=True,
            count=len(messages),
            total_count=total_count,
            messages=messages
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching Telegram messages: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/telegram/status")
async def get_telegram_status():
    """
    Check Telegram connection status
    
    Returns:
        Connection status
    """
    try:
        is_connected, status_message = await telegram_service.check_connection_status()
        return {
            "success": True,
            "connected": is_connected,
            "message": status_message
        }
    except Exception as e:
        logger.error(f"Error checking Telegram status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/slack/messages", response_model=SlackListResponse)
async def get_slack_messages(request: GetSlackMessagesRequest):
    """
    Retrieve Slack messages
    
    Args:
        request: Limit for messages to retrieve
    
    Returns:
        List of Slack messages
    """
    try:
        logger.info(f"Fetching {request.limit} Slack messages")
        messages, total_count = await slack_service.get_messages(
            limit=request.limit
        )
        logger.info(f"Successfully retrieved {len(messages)} Slack messages")
        return SlackListResponse(
            success=True,
            count=len(messages),
            total_count=total_count,
            messages=messages
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching Slack messages: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/slack/status")
async def get_slack_status():
    """
    Check Slack connection status
    
    Returns:
        Connection status
    """
    try:
        is_connected, status_message = await slack_service.check_connection_status()
        return {
            "success": True,
            "connected": is_connected,
            "message": status_message
        }
    except Exception as e:
        logger.error(f"Error checking Slack status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/slack/send", response_model=SendSlackMessageResponse)
async def send_slack_message(request: SendSlackMessageRequest):
    """
    Send a message to a Slack channel or DM
    
    Args:
        request: Channel ID, message text, and optional thread timestamp
    
    Returns:
        Success status and message timestamp
    """
    try:
        logger.info(f"Sending message to channel {request.channel_id}")
        message_ts = await slack_service.send_message(
            channel_id=request.channel_id,
            text=request.text,
            thread_ts=request.thread_ts
        )
        logger.info(f"Successfully sent message. Timestamp: {message_ts}")
        return SendSlackMessageResponse(
            success=True,
            message="Message sent successfully",
            message_ts=message_ts
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending Slack message: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/chatgpt/functions")
async def get_chatgpt_functions():
    """
    Return function definitions for ChatGPT function calling
    
    Returns:
        List of function definitions compatible with ChatGPT API
    """
    from config.chatgpt_functions import CHATGPT_FUNCTIONS
    return CHATGPT_FUNCTIONS


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
