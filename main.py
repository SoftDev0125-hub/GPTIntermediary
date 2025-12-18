"""
ChatGPT Backend/Broker - Main Application Entry Point
Handles email operations, app launching, and other automation tasks
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel
from typing import Optional, List, Union, Dict
import logging
import os
import platform
import sys
import random
import uuid
import asyncio
from datetime import datetime

from services.email_service import EmailService
from services.app_launcher import AppLauncher
from services.telegram_service import TelegramService
from services.slack_service import SlackService
from services.word_service import WordService
from services.excel_service import ExcelService

# Database imports
try:
    from database import get_db, init_db, engine
    from db_models import User
    from sqlalchemy.orm import Session
    from sqlalchemy.sql import func
    DATABASE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Database modules not available: {e}")
    print("[WARNING] Install required packages: pip install sqlalchemy psycopg2-binary")
    DATABASE_AVAILABLE = False
    # Create stub function for dependency injection
    def get_db():
        raise HTTPException(status_code=503, detail="Database not available")
    # Import Session for type hints even when database not available
    try:
        from sqlalchemy.orm import Session
    except ImportError:
        # Fallback type for when SQLAlchemy is not installed
        Session = object
    User = None

# Authentication imports
try:
    from auth_utils import hash_password, verify_password, create_access_token, verify_token, extract_user_id_from_token
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    AUTH_AVAILABLE = True
    security = HTTPBearer()
except ImportError as e:
    print(f"[WARNING] Authentication modules not available: {e}")
    print("[WARNING] Install required packages: pip install passlib bcrypt python-jose python-multipart")
    AUTH_AVAILABLE = False
    security = None
from models.schemas import (
    SendEmailRequest, 
    EmailReplyRequest, 
    LaunchAppRequest,
    EmailListResponse,
    OperationResponse,
    UserCredentials,
    GetTelegramMessagesRequest,
    TelegramListResponse,
    SendTelegramMessageRequest,
    SendTelegramMessageResponse,
    GetSlackMessagesRequest,
    SlackListResponse,
    SendSlackMessageRequest,
    SendSlackMessageResponse,
    CreateWordDocumentRequest,
    OpenWordDocumentRequest,
    AddTextToWordRequest,
    FormatParagraphRequest,
    AddHeadingRequest,
    AddListRequest,
    SaveWordHTMLRequest,
    AddTableRequest,
    FindReplaceRequest,
    PageSetupRequest,
    SaveWordDocumentRequest,
    CreateExcelSpreadsheetRequest,
    OpenExcelSpreadsheetRequest,
    SaveExcelSpreadsheetRequest,
    AddExcelSheetRequest,
    DeleteExcelSheetRequest,
    ExcelSpreadsheetResponse
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

# Database will be initialized on startup if available

# Configure CORS - Allow all origins including file:// (null origin)
# Using wildcard with allow_credentials=False to support null origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins including null
    allow_credentials=False,  # Must be False when using wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Additional middleware to handle null origin (file:// protocol) explicitly
@app.middleware("http")
async def cors_null_origin_handler(request, call_next):
    """
    Custom middleware to handle null origin (file:// protocol)
    """
    origin = request.headers.get("origin")
    response = await call_next(request)
    
    # If origin is null or doesn't exist, add CORS headers
    if origin is None or origin == "null":
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Expose-Headers"] = "*"
    
    return response

# Initialize services
email_service = EmailService()
app_launcher = AppLauncher()
telegram_service = TelegramService()
slack_service = SlackService()
word_service = WordService()
excel_service = ExcelService()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting ChatGPT Backend Broker...")
    
    # Initialize database connection if available
    if DATABASE_AVAILABLE:
        try:
            init_db()
            logger.info("Database connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            logger.warning("Application will continue without database features")
    else:
        logger.warning("Database not available - authentication features disabled")
    
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
    
    # Initialize Telegram service with timeout to prevent blocking startup
    try:
        await asyncio.wait_for(telegram_service.initialize(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Telegram service initialization timed out - continuing without it")
    except Exception as e:
        logger.warning(f"Telegram service initialization failed: {e} - continuing without it")
    
    await slack_service.initialize()
    await word_service.initialize()
    logger.info("Services initialized successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down ChatGPT Backend Broker...")
    await email_service.cleanup()
    await telegram_service.cleanup()
    await slack_service.cleanup()
    await word_service.cleanup()
    await excel_service.cleanup()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "ChatGPT Backend Broker",
        "version": "1.0.0",
        "database": "available" if DATABASE_AVAILABLE else "unavailable"
    }


# ==================== AUTHENTICATION ENDPOINTS ====================

# Import verification services
try:
    from verification_service import generate_verification_code, store_verification_code, verify_code, cleanup_expired_codes
    from email_verification import send_verification_email
    VERIFICATION_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Verification services not available: {e}")
    VERIFICATION_AVAILABLE = False

# In-memory storage for CAPTCHA challenges
# Format: {session_id: {'question': str, 'answer': int, 'created_at': datetime}}
captcha_challenges: Dict[str, Dict] = {}


class CaptchaRequest(BaseModel):
    """Request model for generating CAPTCHA"""
    pass


class SendVerificationCodeRequest(BaseModel):
    """Request model for sending verification code"""
    email: str
    captcha_answer: int
    captcha_session_id: str


class VerifyCodeRequest(BaseModel):
    """Request model for verifying code"""
    email: str
    code: str


@app.get("/api/auth/captcha")
async def generate_captcha():
    """
    Generate a simple math CAPTCHA challenge
    Returns a math question and session ID
    """
    # Generate two random numbers between 1 and 10
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    answer = num1 + num2
    
    # Create session ID
    session_id = str(uuid.uuid4())
    
    # Store challenge
    captcha_challenges[session_id] = {
        'question': f"{num1} + {num2}",
        'answer': answer,
        'created_at': datetime.now()
    }
    
    return {
        "success": True,
        "session_id": session_id,
        "question": f"{num1} + {num2} = ?"
    }


@app.post("/api/auth/send-verification-code")
async def send_verification_code(request: SendVerificationCodeRequest):
    """
    Send verification code to email after CAPTCHA verification
    """
    if not VERIFICATION_AVAILABLE:
        raise HTTPException(status_code=503, detail="Verification service not available")
    
    try:
        # Verify CAPTCHA
        if request.captcha_session_id not in captcha_challenges:
            raise HTTPException(status_code=400, detail="Invalid or expired CAPTCHA session")
        
        captcha_data = captcha_challenges[request.captcha_session_id]
        
        # Check if answer is correct
        if request.captcha_answer != captcha_data['answer']:
            # Remove invalid CAPTCHA
            del captcha_challenges[request.captcha_session_id]
            raise HTTPException(status_code=400, detail="CAPTCHA answer is incorrect")
        
        # Remove used CAPTCHA
        del captcha_challenges[request.captcha_session_id]
        
        # Validate email
        email = request.email.strip().lower()
        if not email or '@' not in email:
            raise HTTPException(status_code=400, detail="Invalid email address")
        
        # Generate and store verification code
        code = generate_verification_code()
        store_verification_code(email, code)
        
        # Send verification email
        email_sent = send_verification_email(email, code)
        
        if email_sent:
            return {
                "success": True,
                "message": "Verification code sent to your email. Please check your inbox."
            }
        else:
            # Email not sent, but code is still valid (might be in logs for development)
            return {
                "success": True,
                "message": "Verification code generated. Check server logs if email is not configured."
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending verification code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send verification code: {str(e)}")

class RegisterRequest(BaseModel):
    """Request model for user registration"""
    name: str
    email: str
    password: str
    verification_code: Optional[str] = None
    captcha_answer: Optional[int] = None
    captcha_session_id: Optional[str] = None


class LoginRequest(BaseModel):
    """Request model for user login"""
    email: str
    password: str


@app.post("/api/auth/register")
async def register_user(request: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user account (CAPTCHA and email verification disabled)
    Saves user to existing users table (name, email, password, create_at)
    """
    if not DATABASE_AVAILABLE or not User:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        # Validate input
        if not request.email or not request.email.strip():
            raise HTTPException(status_code=400, detail="Email is required")
        if not request.name or not request.name.strip():
            raise HTTPException(status_code=400, detail="Name is required")
        if not request.password or len(request.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Verify email verification code (DISABLED)
        # if VERIFICATION_AVAILABLE:
        #     if not request.verification_code:
        #         raise HTTPException(status_code=400, detail="Verification code is required")
        #     
        #     email = request.email.strip().lower()
        #     if not verify_code(email, request.verification_code):
        #         raise HTTPException(status_code=400, detail="Invalid or expired verification code. Please request a new code.")
        
        # Normalize email (lowercase and strip whitespace)
        email_normalized = request.email.strip().lower()
        
        # Check if user already exists (case-insensitive email check)
        existing_user = db.query(User).filter(func.lower(User.email) == email_normalized).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please use a different email or login.")
        
        # Hash password (truncation to 72 bytes is handled automatically in hash_password function)
        try:
            hashed_password = hash_password(request.password)
        except ValueError as e:
            # This shouldn't happen due to truncation in hash_password, but handle it just in case
            error_msg = str(e)
            logger.error(f"Password hashing error: {error_msg}, password length: {len(request.password.encode('utf-8'))} bytes")
            raise HTTPException(status_code=500, detail=f"Password hashing failed. Please try a different password.")
        
        # Create new user (using existing table structure)
        new_user = User(
            name=request.name.strip(),
            email=email_normalized,  # Store email in lowercase
            password=hashed_password,  # Store hashed password in password column
            create_at=datetime.now()  # Use create_at column (existing structure)
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"New user registered: {new_user.email} (ID: {new_user.id})")
        
        return {
            "success": True,
            "message": "Registration successful! Your account has been created.",
            "user_id": new_user.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@app.post("/api/auth/login")
async def login_user(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user and return JWT token
    Returns error if user not found in database or password is incorrect
    """
    if not DATABASE_AVAILABLE or not User or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Authentication service not available")
    
    try:
        # Validate input
        if not request.email or not request.email.strip():
            raise HTTPException(status_code=400, detail="Email is required")
        if not request.password:
            raise HTTPException(status_code=400, detail="Password is required")
        
        # Find user by email
        user = db.query(User).filter(User.email == request.email.strip()).first()
        if not user:
            # User not found in database - return error
            logger.warning(f"Login attempt with non-existent email: {request.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials and try again.")
        
        # Verify password (check password column which stores hashed password)
        password_valid = False
        if user.password:
            # Verify against password column (stores hashed password)
            password_valid = verify_password(request.password, user.password)
        
        if not password_valid:
            # Password incorrect - return error
            logger.warning(f"Invalid password attempt for user: {request.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials and try again.")
        
        # Password is correct - create JWT token
        token_data = {
            "user_id": user.id,
            "email": user.email,
            "name": user.name
        }
        access_token = create_access_token(data=token_data)
        
        logger.info(f"User logged in successfully: {user.email} (ID: {user.id})")
        
        return {
            "success": True,
            "token": access_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


# ==================== END AUTHENTICATION ENDPOINTS ====================


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
        # Cap limit to prevent slow loading
        actual_limit = min(request.limit, 50)  # Max 50 emails for performance
        if request.limit > 50:
            logger.info(f"Requested {request.limit} emails, capping to {actual_limit} for performance")
        logger.info(f"Fetching {actual_limit} unread emails")
        emails, total_unread = await email_service.get_unread_emails(
            access_token=request.user_credentials.access_token,
            refresh_token=request.user_credentials.refresh_token,
            limit=actual_limit
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
        
        # Check for specific errors and provide helpful messages
        if "invalid_scope" in error_msg.lower():
            error_msg = "Gmail OAuth scopes mismatch. Please run: python get_gmail_token.py to reauthorize with correct scopes."
        elif "invalid_grant" in error_msg.lower() or "expired" in error_msg.lower() or "revoked" in error_msg.lower():
            error_msg = "Gmail access token has expired or been revoked. Please re-authenticate by running: python get_gmail_token.py"
        
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


@app.post("/api/telegram/authenticate")
async def authenticate_telegram(request: dict):
    """
    Authenticate Telegram client
    
    Args:
        request: May contain phone_number, code, and password
    
    Returns:
        Authentication status
    """
    try:
        phone_number = request.get('phone_number')
        code = request.get('code')
        password = request.get('password')
        
        is_complete, message = await telegram_service.authenticate(
            phone_number=phone_number,
            code=code,
            password=password
        )
        
        return {
            "success": is_complete,
            "message": message,
            "requires_code": not phone_number and not is_complete,
            "requires_password": "password" in message.lower() and not password
        }
    except Exception as e:
        logger.error(f"Error authenticating Telegram: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/delete-session")
async def delete_telegram_session():
    """
    Delete Telegram session file to force re-authentication
    
    Returns:
        Success status
    """
    try:
        import os
        import shutil
        
        session_dir = os.path.join(os.path.dirname(__file__), 'telegram_session')
        
        if os.path.exists(session_dir):
            # Disconnect client first if it exists and is connected
            try:
                if telegram_service.client and telegram_service.is_connected:
                    await telegram_service.client.disconnect()
                    logger.info("Disconnected Telegram client before deleting session")
            except Exception as e:
                logger.warning(f"Could not disconnect client (may already be disconnected): {str(e)}")
            
            # Delete all files in session directory
            deleted_files = []
            for filename in os.listdir(session_dir):
                file_path = os.path.join(session_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_files.append(filename)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                        deleted_files.append(filename)
                except Exception as e:
                    logger.warning(f"Could not delete {file_path}: {str(e)}")
            
            # Reset service state
            telegram_service.is_connected = False
            telegram_service.client = None  # Reset client reference
            
            # Recreate the client after deleting session (it will need authentication)
            try:
                telegram_service._create_client()
                logger.info("Telegram client recreated after session deletion")
            except Exception as e:
                logger.warning(f"Could not recreate Telegram client: {str(e)}")
            
            if deleted_files:
                logger.info(f"Deleted {len(deleted_files)} session file(s): {', '.join(deleted_files)}")
            
            return {
                "success": True,
                "message": f"Session file(s) deleted successfully ({len(deleted_files) if deleted_files else 0} file(s)). Please restart your backend server, then click 'Refresh' to authenticate.",
                "deleted_files": deleted_files
            }
        else:
            return {
                "success": True,
                "message": "No session file found."
            }
    except Exception as e:
        logger.error(f"Error deleting Telegram session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/send", response_model=SendTelegramMessageResponse)
async def send_telegram_message(request: SendTelegramMessageRequest):
    """
    Send a message to a Telegram chat
    
    Args:
        request: Chat ID, message text, and optional reply to message ID
    
    Returns:
        Success status and message ID
    """
    try:
        logger.info(f"Sending message to Telegram chat {request.chat_id}")
        message_id = await telegram_service.send_message(
            chat_id=request.chat_id,
            text=request.text,
            reply_to_message_id=request.reply_to_message_id
        )
        logger.info(f"Successfully sent Telegram message. Message ID: {message_id}")
        return SendTelegramMessageResponse(
            success=True,
            message="Message sent successfully",
            message_id=message_id
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending Telegram message: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


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


@app.post("/api/word/create", response_model=OperationResponse)
async def create_word_document(request: CreateWordDocumentRequest):
    """
    Create a new Word document
    
    Args:
        request: Document creation details including file path, content, and title
    
    Returns:
        Operation status and file path
    """
    try:
        logger.info(f"Creating Word document: {request.file_path}")
        result = await word_service.create_document(
            file_path=request.file_path,
            content=request.content,
            title=request.title
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Document created successfully"),
                data={"file_path": result.get("file_path")}
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create document"))
    except Exception as e:
        logger.error(f"Error creating Word document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/open", response_model=OperationResponse)
async def open_word_document(request: OpenWordDocumentRequest):
    """
    Open an existing Word document
    
    Args:
        request: Document path
    
    Returns:
        Document information and content
    """
    try:
        logger.info(f"Opening Word document: {request.file_path}")
        result = await word_service.open_document(request.file_path)
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Document opened successfully"),
                data={
                    "file_path": result.get("file_path"),
                    "paragraph_count": result.get("paragraph_count"),
                    "content": result.get("content", "")
                }
            )
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "Document not found"))
    except Exception as e:
        logger.error(f"Error opening Word document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/add-text", response_model=OperationResponse)
async def add_text_to_word(request: AddTextToWordRequest):
    """
    Add text to a Word document with optional formatting
    
    Args:
        request: Text addition details including formatting options
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Adding text to Word document: {request.file_path}")
        result = await word_service.add_text(
            file_path=request.file_path,
            text=request.text,
            bold=request.bold,
            italic=request.italic,
            underline=request.underline,
            font_name=request.font_name,
            font_size=request.font_size,
            color=request.color
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Text added successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to add text"))
    except Exception as e:
        logger.error(f"Error adding text to Word document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/format-paragraph", response_model=OperationResponse)
async def format_paragraph(request: FormatParagraphRequest):
    """
    Format a paragraph in a Word document
    
    Args:
        request: Paragraph formatting details
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Formatting paragraph {request.paragraph_index} in document: {request.file_path}")
        result = await word_service.format_paragraph(
            file_path=request.file_path,
            paragraph_index=request.paragraph_index,
            alignment=request.alignment,
            line_spacing=request.line_spacing,
            space_before=request.space_before,
            space_after=request.space_after,
            left_indent=request.left_indent,
            right_indent=request.right_indent
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Paragraph formatted successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to format paragraph"))
    except Exception as e:
        logger.error(f"Error formatting paragraph: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/add-heading", response_model=OperationResponse)
async def add_heading(request: AddHeadingRequest):
    """
    Add a heading to a Word document
    
    Args:
        request: Heading details
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Adding heading to Word document: {request.file_path}")
        result = await word_service.add_heading(
            file_path=request.file_path,
            text=request.text,
            level=request.level
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Heading added successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to add heading"))
    except Exception as e:
        logger.error(f"Error adding heading: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/add-list", response_model=OperationResponse)
async def add_list(request: AddListRequest):
    """
    Add a list (bulleted or numbered) to a Word document
    
    Args:
        request: List details
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Adding list to Word document: {request.file_path}")
        result = await word_service.add_list(
            file_path=request.file_path,
            items=request.items,
            numbered=request.numbered
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "List added successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to add list"))
    except Exception as e:
        logger.error(f"Error adding list: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/add-table", response_model=OperationResponse)
async def add_table(request: AddTableRequest):
    """
    Add a table to a Word document
    
    Args:
        request: Table details
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Adding table to Word document: {request.file_path}")
        result = await word_service.add_table(
            file_path=request.file_path,
            rows=request.rows,
            cols=request.cols,
            data=request.data,
            header_row=request.header_row
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Table added successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to add table"))
    except Exception as e:
        logger.error(f"Error adding table: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/find-replace", response_model=OperationResponse)
async def find_replace(request: FindReplaceRequest):
    """
    Find and replace text in a Word document
    
    Args:
        request: Find and replace details
    
    Returns:
        Operation status with replacement count
    """
    try:
        logger.info(f"Find and replace in Word document: {request.file_path}")
        result = await word_service.find_replace(
            file_path=request.file_path,
            find_text=request.find_text,
            replace_text=request.replace_text,
            replace_all=request.replace_all
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Find and replace completed"),
                data={"replacement_count": result.get("replacement_count", 0)}
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to perform find and replace"))
    except Exception as e:
        logger.error(f"Error in find and replace: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/page-setup", response_model=OperationResponse)
async def set_page_setup(request: PageSetupRequest):
    """
    Set page setup options for a Word document
    
    Args:
        request: Page setup details
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Setting page setup for Word document: {request.file_path}")
        result = await word_service.set_page_setup(
            file_path=request.file_path,
            margins=request.margins,
            orientation=request.orientation,
            page_size=request.page_size
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Page setup updated successfully")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to update page setup"))
    except Exception as e:
        logger.error(f"Error setting page setup: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/word/save-html", response_model=OperationResponse)
async def save_word_html(request: SaveWordHTMLRequest):
    """
    Save HTML content to Word document with formatting preserved
    
    Args:
        request: HTML content and file path
    
    Returns:
        Success status
    """
    try:
        result = await word_service.save_html_content(
            file_path=request.file_path,
            html_content=request.html_content
        )
        
        if result["success"]:
            return OperationResponse(
                success=True,
                message=result.get("message", "Document saved successfully"),
                data={"file_path": result.get("file_path")}
            )
        else:
            error_msg = result.get("error", "Failed to save document")
            logger.error(f"Save failed: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving Word HTML: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to save document: {str(e)}")


@app.post("/api/word/save", response_model=OperationResponse)
async def save_word_document(request: SaveWordDocumentRequest):
    """
    Save a Word document (or save as a new file)
    
    Args:
        request: Save details
    
    Returns:
        Operation status with file path
    """
    try:
        logger.info(f"Saving Word document: {request.file_path}")
        result = await word_service.save_document(
            file_path=request.file_path,
            new_path=request.new_path
        )
        
        if result.get("success"):
            return OperationResponse(
                success=True,
                message=result.get("message", "Document saved successfully"),
                data={"file_path": result.get("file_path")}
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to save document"))
    except Exception as e:
        logger.error(f"Error saving Word document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Excel Spreadsheet Endpoints =====

@app.post("/api/excel/create", response_model=ExcelSpreadsheetResponse)
async def create_excel_spreadsheet(request: CreateExcelSpreadsheetRequest):
    """
    Create a new Excel spreadsheet
    
    Args:
        request: Spreadsheet creation details
    
    Returns:
        Operation status with file path
    """
    try:
        logger.info(f"Creating Excel spreadsheet: {request.file_path}")
        result = await excel_service.create_spreadsheet(
            file_path=request.file_path,
            sheet_name=request.sheet_name
        )
        
        if result.get("success"):
            return ExcelSpreadsheetResponse(
                success=True,
                message=result.get("message", "Spreadsheet created successfully"),
                file_path=result.get("file_path"),
                sheet_name=result.get("sheet_name")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create spreadsheet"))
    except Exception as e:
        logger.error(f"Error creating Excel spreadsheet: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Add explicit OPTIONS handler for CORS preflight
@app.options("/api/excel/open")
async def excel_open_options():
    """Handle CORS preflight for Excel open endpoint"""
    from fastapi.responses import Response
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.post("/api/excel/open")
async def open_excel_spreadsheet(request: OpenExcelSpreadsheetRequest):
    """
    Open an existing Excel spreadsheet
    
    Args:
        request: Spreadsheet path
    
    Returns:
        Spreadsheet data and information
    """
    from fastapi.responses import JSONResponse
    
    try:
        logger.info(f"Opening Excel spreadsheet: {request.file_path}")
        result = await excel_service.open_spreadsheet(request.file_path)
        
        if result.get("success"):
            response_data = {
                "success": True,
                "message": result.get("message", "Spreadsheet opened successfully"),
                "file_path": result.get("file_path"),
                "sheets": result.get("sheet_names"),
                "active_sheet": result.get("active_sheet"),
                "data": result.get("data"),
                "all_sheets_data": result.get("all_sheets_data"),  # Include ALL sheets data
                "rows": result.get("rows"),
                "columns": result.get("columns")
            }
            
            # Return with explicit CORS headers
            return JSONResponse(
                content=response_data,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
            )
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": result.get("error", "Failed to open spreadsheet")},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
            )
    except Exception as e:
        logger.error(f"Error opening Excel spreadsheet: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )


# Keep the old endpoint definition for backwards compatibility (will use the handler above)
@app.post("/api/excel/open_old", response_model=ExcelSpreadsheetResponse)
async def open_excel_spreadsheet_old(request: OpenExcelSpreadsheetRequest):
    """Old endpoint - use /api/excel/open instead"""
    try:
        logger.info(f"Opening Excel spreadsheet (old endpoint): {request.file_path}")
        result = await excel_service.open_spreadsheet(request.file_path)
        
        if result.get("success"):
            return ExcelSpreadsheetResponse(
                success=True,
                message=result.get("message", "Spreadsheet opened successfully"),
                file_path=result.get("file_path"),
                sheet_names=result.get("sheet_names"),
                active_sheet=result.get("active_sheet"),
                data=result.get("data"),
                rows=result.get("rows"),
                columns=result.get("columns")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to open spreadsheet"))
    except Exception as e:
        logger.error(f"Error opening Excel spreadsheet: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/excel/save", response_model=ExcelSpreadsheetResponse)
async def save_excel_spreadsheet(request: SaveExcelSpreadsheetRequest):
    """
    Save data to Excel spreadsheet
    
    Args:
        request: Spreadsheet data and path
    
    Returns:
        Operation status
    """
    try:
        logger.info(f"Saving Excel spreadsheet: {request.file_path}")
        if request.data:
            logger.info(f"Data contains {len(request.data)} sheets: {list(request.data.keys())}")
        
        result = await excel_service.save_spreadsheet(
            file_path=request.file_path,
            data=request.data,
            new_path=request.new_path
        )
        
        if result.get("success"):
            return ExcelSpreadsheetResponse(
                success=True,
                message=result.get("message", "Spreadsheet saved successfully"),
                file_path=result.get("file_path"),
                sheets=result.get("sheets")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to save spreadsheet"))
    except Exception as e:
        logger.error(f"Error saving Excel spreadsheet: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/excel/add-sheet", response_model=ExcelSpreadsheetResponse)
async def add_excel_sheet(request: AddExcelSheetRequest):
    """
    Add a new sheet to an Excel spreadsheet
    
    Args:
        request: Spreadsheet path and sheet name
    
    Returns:
        Operation status with updated sheet list
    """
    try:
        logger.info(f"Adding sheet '{request.sheet_name}' to: {request.file_path}")
        result = await excel_service.add_sheet(
            file_path=request.file_path,
            sheet_name=request.sheet_name
        )
        
        if result.get("success"):
            return ExcelSpreadsheetResponse(
                success=True,
                message=result.get("message", "Sheet added successfully"),
                sheet_names=result.get("sheet_names")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to add sheet"))
    except Exception as e:
        logger.error(f"Error adding Excel sheet: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/excel/delete-sheet", response_model=ExcelSpreadsheetResponse)
async def delete_excel_sheet(request: DeleteExcelSheetRequest):
    """
    Delete a sheet from an Excel spreadsheet
    
    Args:
        request: Spreadsheet path and sheet name
    
    Returns:
        Operation status with updated sheet list
    """
    try:
        logger.info(f"Deleting sheet '{request.sheet_name}' from: {request.file_path}")
        result = await excel_service.delete_sheet(
            file_path=request.file_path,
            sheet_name=request.sheet_name
        )
        
        if result.get("success"):
            return ExcelSpreadsheetResponse(
                success=True,
                message=result.get("message", "Sheet deleted successfully"),
                sheet_names=result.get("sheet_names")
            )
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to delete sheet"))
    except Exception as e:
        logger.error(f"Error deleting Excel sheet: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def validate_and_resolve_path(path: str, must_exist: bool = True) -> str:
    """
    Validate and resolve a file system path with security checks
    
    Args:
        path: The path to validate
        must_exist: Whether the path must exist
    
    Returns:
        Resolved absolute path
    
    Raises:
        HTTPException: If path is invalid or inaccessible
    """
    import os
    from pathlib import Path
    
    if not path or not isinstance(path, str):
        raise HTTPException(status_code=400, detail="Invalid path provided")
    
    # Remove leading/trailing whitespace
    path = path.strip()
    
    if not path:
        raise HTTPException(status_code=400, detail="Path cannot be empty")
    
    # Handle special cases
    if path == "~" or path.startswith("~/"):
        path = os.path.expanduser(path)
    elif path.startswith("~\\"):
        path = os.path.expanduser(path.replace("\\", "/"))
    
    # Resolve relative paths
    try:
        if not os.path.isabs(path):
            # Make relative to current working directory
            path = os.path.abspath(path)
        else:
            # Normalize absolute path
            path = os.path.normpath(path)
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path format: {str(e)}")
    
    # Security: Prevent path traversal attempts
    # Check for dangerous patterns
    dangerous_patterns = [
        "..\\",
        "../",
        "..",
        "\\\\",
        "//",
    ]
    
    normalized_for_check = path.replace("\\", "/").lower()
    for pattern in dangerous_patterns:
        if pattern in normalized_for_check and pattern != "..":
            # Allow single ".." in middle of path but not at start
            if pattern == ".." and normalized_for_check.count("..") > 1:
                raise HTTPException(status_code=403, detail="Path traversal detected")
    
    # Additional Windows-specific validation
    if platform.system() == "Windows":
        # Check for reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        path_parts = path.split(os.sep)
        for part in path_parts:
            if part:
                # Remove extension for check
                name_without_ext = os.path.splitext(part)[0].upper()
                reserved_names = [
                    "CON", "PRN", "AUX", "NUL",
                    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
                ]
                if name_without_ext in reserved_names:
                    raise HTTPException(status_code=400, detail=f"Reserved Windows name not allowed: {part}")
        
        # Check for invalid characters (but allow ':' for Windows drive letters)
        invalid_chars = ['<', '>', '"', '|', '?', '*']
        for char in invalid_chars:
            if char in path:
                raise HTTPException(status_code=400, detail=f"Invalid character in path: {char}")
        
        # Check for ':' but allow it only as part of Windows drive letter (e.g., C:)
        if ':' in path:
            import re
            # Allow ':' only if it's part of a Windows drive letter (single letter + :)
            # Pattern: C: or C:\ or C:/ or C:\Users\...
            # Check if it matches drive letter pattern at the start (C: followed by optional separator)
            if re.match(r'^[A-Za-z]:', path):
                # Valid Windows drive letter, allow it
                pass
            else:
                # If colon exists but not as drive letter, it's invalid
                colon_pos = path.find(':')
                if colon_pos != 1 or not path[0].isalpha():
                    # Multiple colons or colon not at position 1 is invalid
                    if path.count(':') > 1:
                        raise HTTPException(status_code=400, detail="Invalid use of ':' in path")
                    raise HTTPException(status_code=400, detail="Invalid drive letter format")
    
    # Check if path exists (if required)
    if must_exist:
        try:
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"Path not found: {path}")
            
            # Check if accessible
            if not os.access(path, os.R_OK):
                raise HTTPException(status_code=403, detail=f"Path not accessible: {path}")
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"Permission denied: {path}")
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Error accessing path: {str(e)}")
    
    return path


@app.get("/api/word/list-directory")
async def list_directory(path: str = None):
    """
    List files and directories in a given path with robust validation
    
    Args:
        path: Directory path to list (defaults to user's Documents folder if not provided)
    
    Returns:
        List of files and directories with their types
    """
    try:
        import os
        from pathlib import Path
        
        # Default to D:\Documents instead of C:\Users\pc\Documents
        if not path:
            # Prefer D: drive Documents folder
            if os.path.exists('D:\\Documents'):
                documents_path = 'D:\\Documents'
            else:
                # Try to create D:\Documents
                try:
                    os.makedirs('D:\\Documents', exist_ok=True)
                    documents_path = 'D:\\Documents'
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not create D:\\Documents: {e}, using D: drive root")
                    documents_path = 'D:\\'
            path = documents_path
        
        # Validate and resolve path
        try:
            path = validate_and_resolve_path(path, must_exist=True)
        except HTTPException as e:
            logger.error(f"Path validation error: {e.detail}")
            raise
        except Exception as e:
            logger.error(f"Error validating path: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=400, detail=f"Invalid path: {str(e)}")
        
        # Ensure it's a directory
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
        
        items = []
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    is_dir = os.path.isdir(item_path)
                    stat_info = os.stat(item_path)
                    size = stat_info.st_size if not is_dir else None
                    modified_time = stat_info.st_mtime
                    items.append({
                        "name": item,
                        "path": item_path,
                        "is_directory": is_dir,
                        "size": size,
                        "extension": os.path.splitext(item)[1].lower() if not is_dir else None,
                        "modified_time": modified_time
                    })
                except (OSError, PermissionError):
                    # Skip items we can't access
                    continue
            
            # Sort: directories first, then files, both alphabetically
            items.sort(key=lambda x: (not x["is_directory"], x["name"].lower()))
            
            # Get parent path (only if not root)
            parent_path = None
            dirname = os.path.dirname(path)
            if dirname and dirname != path:
                parent_path = dirname
            
            return {
                "success": True,
                "path": path,
                "parent_path": parent_path,
                "home_path": "D:\\Documents",  # Use D: drive instead of C: drive
                "items": items
            }
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"Permission denied: {path}")
    except Exception as e:
        logger.error(f"Error listing directory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/word/select-folder")
async def select_folder(initial_path: str = None):
    """
    Open native Windows folder picker dialog using a subprocess
    
    Args:
        initial_path: Optional initial folder path to start from
    
    Returns:
        Selected folder path or None if cancelled
    """
    try:
        if platform.system() != "Windows":
            raise HTTPException(status_code=400, detail="Folder picker is only available on Windows")
        
        import subprocess
        import json
        import tempfile
        
        # Create a temporary Python script to show the folder picker
        script_content = """import tkinter as tk
from tkinter import filedialog
import sys
import json
import os

try:
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)  # Bring to front
    
    initial_path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != 'None' else None
    
    if initial_path and os.path.exists(initial_path) and os.path.isdir(initial_path):
        folder_path = filedialog.askdirectory(initialdir=initial_path, title="Select Folder")
    else:
        folder_path = filedialog.askdirectory(title="Select Folder")
    
    result = {
        "success": folder_path is not None and folder_path != "",
        "folder_path": folder_path if folder_path else None,
        "cancelled": folder_path is None or folder_path == ""
    }
    
    print(json.dumps(result))
    root.destroy()
except Exception as e:
    result = {
        "success": False,
        "error": str(e)
    }
    print(json.dumps(result))
    sys.exit(1)
"""
        
        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            script_path = f.name
        
        try:
            # Run the script
            cmd = [sys.executable, script_path]
            if initial_path:
                cmd.append(initial_path)
            else:
                cmd.append('None')
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout.strip())
                return data
            else:
                error_msg = result.stderr or "Unknown error"
                raise Exception(f"Folder picker script failed: {error_msg}")
                
        finally:
            # Clean up temp file
            try:
                os.unlink(script_path)
            except:
                pass
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in select_folder: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to show folder picker: {str(e)}")


@app.get("/api/excel/select-file")
async def select_excel_file(initial_path: str = None):
    """
    Open native Windows file picker dialog for Excel files
    
    Args:
        initial_path: Optional initial folder path to start from
    
    Returns:
        Selected Excel file path or None if cancelled
    """
    try:
        if platform.system() != "Windows":
            raise HTTPException(status_code=400, detail="File picker is only available on Windows")
        
        import subprocess
        import json
        import tempfile
        
        # Create a temporary Python script to show the file picker for Excel files
        script_content = """import tkinter as tk
from tkinter import filedialog
import sys
import json
import os

try:
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)  # Bring to front
    
    # Set initial directory if provided
    initial_dir = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.expanduser('~')
    
    # Show file picker dialog for Excel files
    file_path = filedialog.askopenfilename(
        title="Select Excel Spreadsheet",
        initialdir=initial_dir,
        filetypes=[
            ("Excel Files", "*.xlsx *.xls"),
            ("Excel Workbook", "*.xlsx"),
            ("Excel 97-2003", "*.xls"),
            ("All Files", "*.*")
        ]
    )
    
    root.destroy()
    
    # Return result as JSON
    if file_path:
        print(json.dumps({"success": True, "file_path": file_path}))
    else:
        print(json.dumps({"success": False, "cancelled": True}))
        
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
    sys.exit(1)
"""
        
        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        try:
            # Prepare initial path argument
            args = [sys.executable, script_path]
            if initial_path and os.path.isdir(initial_path):
                args.append(initial_path)
            elif initial_path:
                # If file path provided, use its directory
                parent_dir = os.path.dirname(initial_path)
                if os.path.isdir(parent_dir):
                    args.append(parent_dir)
            
            # Run the script
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            # Parse the output
            if result.stdout:
                output = json.loads(result.stdout.strip())
                return output
            else:
                return {"success": False, "error": "No output from file picker"}
                
        finally:
            # Clean up temp file
            try:
                os.unlink(script_path)
            except:
                pass
                
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "File picker timed out"}
    except Exception as e:
        logger.error(f"Error in select_excel_file: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/api/word/select-file")
async def select_file(initial_path: str = None):
    """
    Open native Windows file picker dialog using a subprocess
    
    Args:
        initial_path: Optional initial folder/file path to start from
    
    Returns:
        Selected file path or None if cancelled
    """
    try:
        if platform.system() != "Windows":
            raise HTTPException(status_code=400, detail="File picker is only available on Windows")
        
        import subprocess
        import json
        import tempfile
        
        # Create a temporary Python script to show the file picker
        script_content = """import tkinter as tk
from tkinter import filedialog
import sys
import json
import os

try:
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)  # Bring to front
    
    initial_path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != 'None' else None
    
    # Determine initial directory
    if initial_path:
        if os.path.exists(initial_path):
            if os.path.isdir(initial_path):
                initial_dir = initial_path
            else:
                initial_dir = os.path.dirname(initial_path)
        else:
            initial_dir = None
    else:
        initial_dir = None
    
    if initial_dir and os.path.exists(initial_dir):
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Select Word Document",
            filetypes=[("Word Documents", "*.docx"), ("All Files", "*.*")]
        )
    else:
        file_path = filedialog.askopenfilename(
            title="Select Word Document",
            filetypes=[("Word Documents", "*.docx"), ("All Files", "*.*")]
        )
    
    result = {
        "success": file_path is not None and file_path != "",
        "file_path": file_path if file_path else None,
        "cancelled": file_path is None or file_path == ""
    }
    
    print(json.dumps(result))
    root.destroy()
except Exception as e:
    result = {
        "success": False,
        "error": str(e)
    }
    print(json.dumps(result))
    sys.exit(1)
"""
        
        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            script_path = f.name
        
        try:
            # Run the script
            cmd = [sys.executable, script_path]
            if initial_path:
                cmd.append(initial_path)
            else:
                cmd.append('None')
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout.strip())
                return data
            else:
                error_msg = result.stderr or "Unknown error"
                raise Exception(f"File picker script failed: {error_msg}")
                
        finally:
            # Clean up temp file
            try:
                os.unlink(script_path)
            except:
                pass
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in select_file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to show file picker: {str(e)}")


@app.get("/api/chatgpt/functions")
async def get_chatgpt_functions():
    """
    Return function definitions for ChatGPT function calling
    
    Returns:
        List of function definitions compatible with ChatGPT API
    """
    from config.chatgpt_functions import CHATGPT_FUNCTIONS
    return CHATGPT_FUNCTIONS


# Database endpoints removed


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
