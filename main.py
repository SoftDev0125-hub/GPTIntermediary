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

from services.email_service import EmailService
from services.app_launcher import AppLauncher
from models.schemas import (
    SendEmailRequest, 
    EmailReplyRequest, 
    LaunchAppRequest,
    EmailListResponse,
    OperationResponse,
    UserCredentials
)
from pydantic import BaseModel


class GetUnreadEmailsRequest(BaseModel):
    """Request model for getting unread emails"""
    user_credentials: UserCredentials
    limit: int = 10

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


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting ChatGPT Backend Broker...")
    await email_service.initialize()
    logger.info("Services initialized successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down ChatGPT Backend Broker...")
    await email_service.cleanup()


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
        emails = await email_service.get_unread_emails(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            limit=request.limit
        )
        return EmailListResponse(
            success=True,
            count=len(emails),
            emails=emails
        )
    except Exception as e:
        logger.error(f"Error fetching unread emails: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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
        reload=True,
        log_level="info"
    )
