"""
ChatGPT Backend/Broker - Main Application Entry Point
Handles email operations, app launching, and other automation tasks
"""

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Set, Dict
import uvicorn
import json
import asyncio
from contextlib import asynccontextmanager
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
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_load_env_root / '.env')

# Early logging so helper functions can safely log before full app init
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Robust env loader (fallback to manual .env parsing) to handle .env lines with spaces
def _read_env_key_from_dotenv(key_name):
    val = os.getenv(key_name)
    if val:
        return val.strip()
    try:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        env_path = os.path.join(base, '.env')
        if not os.path.exists(env_path):
            return ''
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' not in line or line.strip().startswith('#'):
                    continue
                k, v = line.split('=', 1)
                if k.strip() == key_name:
                    return v.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Failed to read .env fallback for {key_name}: {e}")
    return ''


def _get_env_file_path():
    """Return (absolute_path, exists) for the project .env file."""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    env_path = os.path.join(base, '.env')
    return env_path, os.path.exists(env_path)


def _write_env_key_to_dotenv(key_name, value):
    """Write or update a key in the project's .env file (best-effort).
    Returns True on success, False on failure."""
    try:
        env_path, _ = _get_env_file_path()
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        key_found = False
        new_lines = []
        for line in lines:
            if '=' not in line or line.strip().startswith('#'):
                new_lines.append(line)
                continue
            k, v = line.split('=', 1)
            if k.strip() == key_name:
                new_lines.append(f"{key_name}={value}\n")
                key_found = True
            else:
                new_lines.append(line)

        if not key_found:
            new_lines.append(f"{key_name}={value}\n")

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        logger.warning(f"Failed to write {key_name} to .env: {e}")
        return False

# Read NewsAPI key from environment (set in .env or system env)
NEWSAPI_KEY = _read_env_key_from_dotenv('NEWSAPI_KEY')
if not NEWSAPI_KEY:
    logger.warning('NEWSAPI_KEY not found in environment or .env; news endpoints will return error')

from services.email_service import EmailService
from services.app_launcher import AppLauncher
from services.whatsapp_service import WhatsAppService
from services.word_service import WordService
from services.excel_service import ExcelService
from services.contact_resolver import resolve_name_to_emails, email_finder_keys_status

# Database imports
try:
    from database import get_db, init_db, engine
    from db_models import User, UserServiceCredential, GmailInfo, TelegramSession, SlackInfo, APIKey, Contact
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
    optional_security = HTTPBearer(auto_error=False)  # Optional security for backward compatibility
except ImportError as e:
    print(f"[WARNING] Authentication modules not available: {e}")
    print("[WARNING] Install required packages: pip install passlib bcrypt python-jose python-multipart")
    AUTH_AVAILABLE = False
    security = None
    optional_security = None

# Helper function to get current user ID from JWT token (optional)
async def get_current_user_id_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security) if optional_security else None,
    db: Session = Depends(get_db)
) -> Optional[int]:
    """
    Extract and verify user ID from JWT token (optional - for backward compatibility)
    Returns user_id if token is valid and present, None otherwise
    """
    if not AUTH_AVAILABLE or not credentials:
        return None
    
    try:
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            return None
        
        # Verify user exists in database
        if DATABASE_AVAILABLE and User:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return None
        
        return user_id
    except Exception as e:
        logger.debug(f"Error extracting user from token (optional): {e}")
        return None

# Helper function to get current user ID from JWT token (required)
async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> int:
    """
    Extract and verify user ID from JWT token
    Returns user_id if token is valid, raises HTTPException if invalid
    """
    if not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Authentication service not available")
    
    try:
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        # Verify user exists in database
        if DATABASE_AVAILABLE and User:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
        
        return user_id
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting user from token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

from models.schemas import (
    SendEmailRequest, 
    EmailReplyRequest, 
    LaunchAppRequest,
    EmailListResponse,
    OperationResponse,
    UserCredentials,
    GetWhatsAppContactsRequest,
    WhatsAppContactsResponse,
    SendWhatsAppMessageRequest,
    SendWhatsAppMessageResponse,
    WhatsAppStatusResponse,
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
    query: Optional[str] = None


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
    Ensures CORS headers are always present, even for error responses
    """
    origin = request.headers.get("origin")
    
    try:
        response = await call_next(request)
    except Exception as e:
        # If an exception occurs, create a response with CORS headers
        from fastapi.responses import JSONResponse
        import traceback
        error_msg = str(e)
        logger.error(f"Unhandled exception in middleware: {error_msg}")
        logger.error(traceback.format_exc())
        response = JSONResponse(
            status_code=200,  # Use 200 to ensure CORS headers work
            content={
                "success": False,
                "error": error_msg,
                "is_connected": False,
                "is_authenticated": False,
                "has_api_credentials": False,
                "message": f"Error: {error_msg}"
            },
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Expose-Headers": "*"
            }
        )
        return response
    
    # Always add CORS headers regardless of origin
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response.status_code = 200
    
    return response

# Exception handler for HTTPException (raised by FastAPI)
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Handle HTTPException and ensure CORS headers are present"""
    from fastapi.responses import JSONResponse
    
    return JSONResponse(
        status_code=200,
        content={"success": False, "error": exc.detail},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Expose-Headers": "*"
        }
    )

# Global exception handler for unhandled exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler to ensure CORS headers are always present"""
    from fastapi.responses import JSONResponse
    import traceback
    
    error_msg = str(exc)
    logger.error(f"Global exception handler caught: {error_msg}")
    logger.error(traceback.format_exc())
    
    return JSONResponse(
        status_code=200,
        content={"success": False, "error": error_msg},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Expose-Headers": "*"
        }
    )

# Initialize services
email_service = EmailService()
app_launcher = AppLauncher()
whatsapp_service = WhatsAppService()
word_service = WordService()
excel_service = ExcelService()

# WebSocket connection managers
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, service: str):
        await websocket.accept()
        self.active_connections[service].add(websocket)
        logger.info(f"WebSocket connected for {service}. Total connections: {len(self.active_connections[service])}")
    
    def disconnect(self, websocket: WebSocket, service: str):
        self.active_connections[service].discard(websocket)
        logger.info(f"WebSocket disconnected for {service}. Total connections: {len(self.active_connections[service])}")
    
    async def broadcast(self, message: dict, service: str):
        if service not in self.active_connections:
            return
        disconnected = set()
        for connection in self.active_connections[service]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")
                disconnected.add(connection)
        
        # Remove disconnected connections
        for conn in disconnected:
            self.active_connections[service].discard(conn)
    
    async def close_all(self, service: str = None):
        """
        Close all WebSocket connections for a service or all services
        
        Args:
            service: Service name to close connections for, or None to close all
        """
        services_to_close = [service] if service else list(self.active_connections.keys())
        
        for svc in services_to_close:
            if svc not in self.active_connections:
                continue
            
            connections = list(self.active_connections[svc])  # Create a copy to iterate
            logger.info(f"Closing {len(connections)} WebSocket connections for {svc}...")
            
            for connection in connections:
                try:
                    await connection.close()
                    logger.debug(f"Closed WebSocket connection for {svc}")
                except Exception as e:
                    logger.error(f"Error closing WebSocket connection for {svc}: {e}")
                finally:
                    self.active_connections[svc].discard(connection)
            
            logger.info(f"All WebSocket connections for {svc} closed")

# Global connection managers


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
    
    # WhatsApp service will be initialized lazily when the WhatsApp tab is clicked
    # This prevents unnecessary initialization on app startup
    logger.info("WhatsApp service will be initialized when WhatsApp tab is accessed")
    await word_service.initialize()
    logger.info("Services initialized successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown - close WebSocket connections and disconnect services"""
    logger.info("Shutting down ChatGPT Backend Broker...")
    
    # Cleanup services
    await email_service.cleanup()
    if whatsapp_service:
        try:
            await whatsapp_service.cleanup()
        except Exception as e:
            logger.warning(f"Error cleaning up WhatsApp service: {e}")
    await word_service.cleanup()
    await excel_service.cleanup()
    
    logger.info("Shutdown complete")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "ChatGPT Backend Broker",
        "version": "1.0.0",
        "database": "available" if DATABASE_AVAILABLE else "unavailable"
    }


@app.get("/api/news")
async def get_latest_news(country: Optional[str] = 'us', q: Optional[str] = None, pageSize: int = 5):
    """
    Fetch latest news using NewsAPI.org's top-headlines endpoint.
    Query params:
      - country: 2-letter country code (default 'us')
      - q: optional search query
      - pageSize: number of articles to return (default 5)
    """
    if not NEWSAPI_KEY or NEWSAPI_KEY == '':
        raise HTTPException(status_code=503, detail="NewsAPI key not configured")

    url = 'https://newsapi.org/v2/top-headlines'
    # If a specific query/topic is provided, use the 'everything' endpoint
    if q:
        url = 'https://newsapi.org/v2/everything'
        params = {
            'apiKey': NEWSAPI_KEY,
            'q': q,
            'pageSize': min(pageSize, 20),
            'sortBy': 'publishedAt',
            'language': 'en'
        }
    else:
        params = {
            'apiKey': NEWSAPI_KEY,
            'country': country,
            'pageSize': min(pageSize, 20)
        }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get('status') != 'ok':
            msg = data.get('message', 'Unknown error from NewsAPI')
            logger.error(f"NewsAPI returned error: {msg}")
            raise HTTPException(status_code=500, detail=f"NewsAPI error: {msg}")

        articles = []
        for a in data.get('articles', []):
            articles.append({
                'title': a.get('title'),
                'source': (a.get('source') or {}).get('name'),
                'url': a.get('url'),
                'publishedAt': a.get('publishedAt'),
                'description': a.get('description')
            })

        return { 'success': True, 'articles': articles }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching news: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch news: {str(e)}")


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
        
        # Find user by email - catch database connection errors
        try:
            user = db.query(User).filter(User.email == request.email.strip()).first()
        except Exception as db_error:
            error_str = str(db_error).lower()
            logger.error(f"Database connection error during login: {db_error}")
            if 'password authentication failed' in error_str or 'connection' in error_str or 'operationalerror' in error_str:
                raise HTTPException(
                    status_code=503, 
                    detail="Database connection failed. Please check your DATABASE_URL in .env file and ensure PostgreSQL is running."
                )
            else:
                raise HTTPException(
                    status_code=503,
                    detail=f"Database error: {str(db_error)}"
                )
        
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
                "name": user.name,
                "user_classification_id": user.user_classification_id if hasattr(user, 'user_classification_id') else 0
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@app.post("/api/auth/save-remember-me")
async def save_remember_me(request: dict):
    """
    Save "Remember me" credentials to a file (for app mode when localStorage doesn't persist)
    This is a fallback mechanism for pywebview apps
    """
    try:
        import json
        from pathlib import Path
        
        # Create a secure storage directory
        storage_dir = Path.home() / ".gpt_intermediary"
        storage_dir.mkdir(exist_ok=True)
        storage_file = storage_dir / "remember_me.json"
        
        # Save the data (in production, this should be encrypted)
        data = {
            "remember_me_checked": request.get("remember_me_checked", False),
            "email": request.get("email", ""),
            "password": request.get("password", ""),  # In production, encrypt this
            "saved_at": datetime.now().isoformat()
        }
        
        with open(storage_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        
        logger.info(f"Saved remember me credentials to {storage_file}")
        
        return {
            "success": True,
            "message": "Credentials saved successfully"
        }
    except Exception as e:
        logger.error(f"Error saving remember me credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


@app.get("/api/auth/load-remember-me")
async def load_remember_me():
    """
    Load "Remember me" credentials from file (for app mode when localStorage doesn't persist)
    This is a fallback mechanism for pywebview apps
    """
    try:
        import json
        from pathlib import Path
        
        storage_file = Path.home() / ".gpt_intermediary" / "remember_me.json"
        
        if not storage_file.exists():
            return {
                "success": True,
                "data": {
                    "remember_me_checked": False,
                    "email": "",
                    "password": ""
                }
            }
        
        with open(storage_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return {
            "success": True,
            "data": {
                "remember_me_checked": data.get("remember_me_checked", False),
                "email": data.get("email", ""),
                "password": data.get("password", "")
            }
        }
    except Exception as e:
        logger.error(f"Error loading remember me credentials: {e}")
        # Return empty data on error
        return {
            "success": True,
            "data": {
                "remember_me_checked": False,
                "email": "",
                "password": ""
            }
        }


@app.post("/api/auth/clear-remember-me")
async def clear_remember_me():
    """
    Clear "Remember me" credentials from file
    """
    try:
        from pathlib import Path
        
        storage_file = Path.home() / ".gpt_intermediary" / "remember_me.json"
        
        if storage_file.exists():
            storage_file.unlink()
            logger.info(f"Cleared remember me credentials from {storage_file}")
        
        return {
            "success": True,
            "message": "Credentials cleared successfully"
        }
    except Exception as e:
        logger.error(f"Error clearing remember me credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear credentials: {str(e)}")


# ==================== END AUTHENTICATION ENDPOINTS ====================


@app.post("/api/email/send", response_model=OperationResponse)
async def send_email(
    request: SendEmailRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """
    Send an email via Gmail using user's credentials
    Uses per-user credentials from database if authenticated, otherwise uses request credentials
    
    Args:
        request: Email details including user credentials, recipient, subject, and body
        user_id: User ID from JWT token (optional - for backward compatibility)
        db: Database session
    
    Returns:
        Operation status and message ID
    """
    try:
        # Try to get user's Gmail credentials from database first (if authenticated)
        access_token = None
        refresh_token = None
        google_client_id = None
        google_client_secret = None
        
        if user_id and DATABASE_AVAILABLE:
            from config_helpers import get_gmail_config
            from user_service_helpers import get_user_gmail_credentials
            gmail_config = get_gmail_config(db, user_id)
            user_creds = get_user_gmail_credentials(db, user_id)
            if gmail_config:
                google_client_id = gmail_config.get('google_client_id')
                google_client_secret = gmail_config.get('google_client_secret')
            if user_creds and user_creds.get('access_token'):
                access_token = user_creds['access_token']
                refresh_token = user_creds.get('refresh_token')
                logger.info(f"Using per-user Gmail credentials for user {user_id}")
        
        # Fallback to credentials from request body (backward compatibility)
        if not access_token and request.user_credentials and request.user_credentials.access_token:
            access_token = request.user_credentials.access_token
            refresh_token = request.user_credentials.refresh_token
            logger.info("Using credentials from request body (backward compatibility)")
        if not access_token:
            access_token = (os.getenv('USER_ACCESS_TOKEN') or '').strip()
            refresh_token = (os.getenv('USER_REFRESH_TOKEN') or '').strip()
            if access_token and refresh_token:
                logger.info("Using Gmail credentials from .env (USER_ACCESS_TOKEN, USER_REFRESH_TOKEN)")
                if not google_client_id:
                    google_client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip() or None
                if not google_client_secret:
                    google_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip() or None
        if not access_token:
            raise HTTPException(status_code=400, detail="No Gmail credentials provided. Please connect your Gmail account first or set USER_ACCESS_TOKEN and USER_REFRESH_TOKEN in .env")

        # Determine sender email (from user's saved config or from provided credentials)
        sender_email = None
        try:
            if 'gmail_config' in locals() and gmail_config and gmail_config.get('user_email'):
                sender_email = gmail_config.get('user_email')
        except Exception:
            sender_email = None

        if (not sender_email) and request.user_credentials and getattr(request.user_credentials, 'email', None):
            sender_email = request.user_credentials.email
        
        # Resolve recipient(s)
        targets = []
        resolved_contacts = []

        # First, try to parse an email address directly from `to` (handles "Name <email>" and raw emails)
        from email.utils import parseaddr
        parsed_name, parsed_email = parseaddr(request.to or '')
        parsed_email = parsed_email.strip() if parsed_email else ''

        # If parsed_email looks like a placeholder (example.com etc.) or obviously fake, ignore it
        placeholder_domains = {"example.com", "example.org", "example.net"}
        parsed_is_placeholder = False
        if parsed_email and '@' in parsed_email:
            try:
                domain = parsed_email.split('@', 1)[1].lower()
                if domain in placeholder_domains or domain.startswith('example.') or domain == 'example':
                    parsed_is_placeholder = True
                    logger.info(f"Ignoring placeholder recipient address from input: {parsed_email}")
            except Exception:
                parsed_is_placeholder = False

        if parsed_email and '@' in parsed_email and not parsed_is_placeholder:
            targets = [parsed_email]
            resolved_contacts.append({"query": request.to, "matched": parsed_email, "match_type": "direct_parse"})
        else:
            # Attempt name-based lookup in `contacts` table (case-insensitive substring match)
            # Try to extract a name from natural language like "send hi to Abel"
            raw_to = (request.to or '').strip()
            import re
            m = re.search(r"\bto\s+(.+)$", raw_to, flags=re.IGNORECASE)
            if m:
                query_name = m.group(1).strip().strip('"\'\.,')
            else:
                query_name = raw_to
            if not query_name:
                raise HTTPException(status_code=400, detail="Recipient must be a valid email address or a contact name.")

            if DATABASE_AVAILABLE:
                # Debug: log inputs used for contact lookup
                logger.info(f"Contact lookup inputs: raw_to='{raw_to}', query_name='{query_name}', sender_email='{sender_email}'")

                # Ensure we know the authenticated Gmail address so we can exclude it from matches
                try:
                    if not sender_email and access_token:
                        try:
                            svc = email_service._get_service(access_token, refresh_token, google_client_id, google_client_secret)
                            profile = svc.users().getProfile(userId='me').execute()
                            profile_email = profile.get('emailAddress') if isinstance(profile, dict) else None
                            if profile_email:
                                sender_email = profile_email
                                logger.info(f"Discovered authenticated Gmail profile email: {sender_email}")
                        except Exception as e:
                            logger.info(f"Could not fetch Gmail profile for sender discovery: {e}")
                except Exception:
                    pass
                try:
                    matches = db.query(Contact).filter(Contact.name.ilike(f"%{query_name}%")).all()
                except Exception as e:
                    logger.error(f"Failed to query contacts for '{query_name}' using ilike: {e}")
                    matches = []

                # If no ilike matches, perform a broader in-Python match to handle tokenized names,
                # email local-part matches, and minor formatting differences.
                if not matches:
                    try:
                        logger.info(f"No ilike matches for '{query_name}', performing broader Python-side matching")
                        all_contacts = db.query(Contact).all()
                        q = query_name.lower()
                        broader = []
                        for c in all_contacts:
                            try:
                                name = (c.name or '').lower()
                                email = (c.email or '').lower()
                                # match if query is substring of name or email
                                if q in name or q in email:
                                    broader.append(c)
                                    continue
                                # match by tokens (e.g., query 'abel' matches 'abel simbulan')
                                tokens = [t.strip() for t in name.split() if t.strip()]
                                for t in tokens:
                                    if q == t or q in t or t in q:
                                        broader.append(c)
                                        break
                                else:
                                    # check local-part of email (before @)
                                    if '@' in email:
                                        local = email.split('@', 1)[0]
                                        if q == local or q in local or local in q:
                                            broader.append(c)
                            except Exception:
                                continue
                        matches = broader
                        logger.info(f"Broader matching found {len(matches)} results for '{query_name}'")
                    except Exception as e3:
                        logger.error(f"Broader contact matching failed for '{query_name}': {e3}")
                        matches = []

                # Debug: show number of matches and sample data
                try:
                    if matches is None:
                        logger.info(f"Contact query returned None for '{query_name}'")
                    else:
                        logger.info(f"Contact query found {len(matches)} matches for '{query_name}'")
                        sample = []
                        for m in matches[:20]:
                            sample.append({"id": getattr(m, 'id', None), "name": getattr(m, 'name', None), "email": getattr(m, 'email', None)})
                        logger.info(f"Contact matches sample: {sample}")
                except Exception as log_exc:
                    logger.warning(f"Failed to log contact matches: {log_exc}")

                if not matches:
                    # No matches found after database attempts - try external resolver
                    try:
                        logger.info(f"No local contact matches for '{query_name}', attempting external resolver")
                        candidates = resolve_name_to_emails(query_name)
                        logger.info(f"Resolver returned {len(candidates)} candidates for '{query_name}'")
                        if not candidates:
                            raise HTTPException(status_code=404, detail=f"No contacts found with name containing '{query_name}'")

                        # If resolver returned candidates but caller did not confirm, ask for confirmation
                        if not getattr(request, 'confirm', False):
                            # Return 409 Conflict with candidate suggestions encoded in detail
                            import json as _json
                            raise HTTPException(status_code=409, detail=_json.dumps({
                                'message': 'Address not found in contacts. Resolver found candidate addresses. Set request.confirm=true to proceed automatically.',
                                'candidates': candidates
                            }))

                        # If confirmed, use resolver candidates as targets
                        seen = set()
                        for c in candidates:
                            e = c.get('email')
                            if e and e not in seen:
                                targets.append(e)
                                seen.add(e)
                                resolved_contacts.append({
                                    'query': query_name,
                                    'matched': e,
                                    'match_type': 'external_resolver',
                                    'confidence': c.get('confidence', 0.5),
                                    'sources': c.get('sources', [])
                                })
                    except HTTPException:
                        raise
                    except Exception as e_res:
                        logger.error(f"External resolver failed for '{query_name}': {e_res}")
                        raise HTTPException(status_code=500, detail=f"Contact resolution failed: {e_res}")

                # Collect unique emails from matching contacts, but exclude the sender's own email
                seen = set()
                sender_email_lower = None
                try:
                    if sender_email:
                        sender_email_lower = sender_email.strip().lower()
                except Exception:
                    sender_email_lower = None

                for c in matches:
                    c_email = (c.email or '').strip()
                    if not c_email:
                        continue
                    if sender_email_lower and c_email.lower() == sender_email_lower:
                        logger.info(f"Excluding contact id={c.id} with email={c_email} because it matches the sender email")
                        continue
                    if c_email and c_email not in seen:
                        targets.append(c_email)
                        seen.add(c_email)
                        resolved_contacts.append({"query": query_name, "matched": c_email, "contact_id": c.id, "match_type": "contacts_table"})

                if not targets:
                    # All matches (if any) were the sender's own email or no valid emails
                    raise HTTPException(status_code=404, detail=f"No contacts found with name containing '{query_name}' (matches excluded sender or had no emails)")
            else:
                raise HTTPException(status_code=400, detail=f"Recipient must be a valid email address. Name-based lookup requires database access for '{request.to}'.")

        send_results = []
        for tgt in targets:
            try:
                # Normalize recipient address in main as an extra safety check
                from email.utils import parseaddr
                _name, _email = parseaddr(tgt or '')
                _email = _email.strip() if _email else ''
                if not _email or '@' not in _email:
                    logger.error(f"Skipping invalid recipient address: {tgt}")
                    send_results.append({"to": tgt, "error": "Invalid recipient address", "success": False})
                    continue
                tgt_normalized = _email
                logger.info(f"Sending email to {tgt_normalized}")
                msg_id = await email_service.send_email(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    to=[tgt_normalized],
                    subject=request.subject,
                    body=request.body,
                    html=request.html,
                    google_client_id=google_client_id,
                    google_client_secret=google_client_secret,
                    from_email=sender_email
                )
                send_results.append({"to": tgt, "to_normalized": tgt_normalized, "message_id": msg_id, "success": True})
            except Exception as e:
                logger.error(f"Failed to send to {tgt}: {e}")
                send_results.append({"to": tgt, "to_normalized": tgt_normalized if 'tgt_normalized' in locals() else None, "error": str(e), "success": False})

        # Persist newly-resolved contacts into the contacts table for future lookups
        try:
            if DATABASE_AVAILABLE and resolved_contacts:
                # resolved_contacts entries may include 'matched' and optional 'confidence'
                for rc in resolved_contacts:
                    email_addr = (rc.get('matched') or '').strip()
                    name_guess = (rc.get('query') or '').strip()
                    if not email_addr or '@' not in email_addr:
                        continue
                    # Only add contacts for successful sends
                    sent_success = any(r.get('to_normalized') == email_addr and r.get('success') for r in send_results)
                    if not sent_success:
                        # Don't store contacts that we failed to send to
                        continue
                    try:
                        existing = db.query(Contact).filter(Contact.email == email_addr).first()
                        if existing:
                            logger.info(f"Contact for {email_addr} already exists (id={existing.id})")
                            continue
                        # Create contact record (user_id left NULL for global contact)
                        new_contact = Contact(name=name_guess or email_addr, email=email_addr, user_id=None)
                        db.add(new_contact)
                        db.commit()
                        logger.info(f"Stored new contact: {email_addr} (name='{name_guess}')")
                    except Exception as store_err:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        logger.warning(f"Failed to store resolved contact {email_addr}: {store_err}")
        except Exception as _store_exc:
            logger.warning(f"Error while attempting to persist resolved contacts: {_store_exc}")

        return OperationResponse(
            success=all([r.get('success') for r in send_results]),
            message=f"Email send results",
            data={"results": send_results}
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
async def get_unread_emails(
    request: GetUnreadEmailsRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """
    Retrieve unread emails from Gmail using user's credentials
    Uses per-user credentials from database if authenticated, otherwise uses request credentials
    
    Args:
        request: User credentials and limit for emails to retrieve
        user_id: User ID from JWT token (optional - for backward compatibility)
        db: Database session
    
    Returns:
        List of unread emails
    """
    try:
        # Try to get user's Gmail credentials from database first (if authenticated)
        access_token = None
        refresh_token = None
        google_client_id = None
        google_client_secret = None
        
        if user_id and DATABASE_AVAILABLE:
            from config_helpers import get_gmail_config
            from user_service_helpers import get_user_gmail_credentials
            gmail_config = get_gmail_config(db, user_id)
            user_creds = get_user_gmail_credentials(db, user_id)
            if gmail_config:
                google_client_id = gmail_config.get('google_client_id')
                google_client_secret = gmail_config.get('google_client_secret')
            if user_creds and user_creds.get('access_token'):
                access_token = user_creds['access_token']
                refresh_token = user_creds.get('refresh_token')
                logger.info(f"Using per-user Gmail credentials for user {user_id}")
        
        # Fallback to credentials from request body (backward compatibility)
        if not access_token and request.user_credentials and request.user_credentials.access_token:
            access_token = request.user_credentials.access_token
            refresh_token = request.user_credentials.refresh_token
            logger.info("Using credentials from request body (backward compatibility)")
        if not access_token:
            access_token = (os.getenv('USER_ACCESS_TOKEN') or '').strip()
            refresh_token = (os.getenv('USER_REFRESH_TOKEN') or '').strip()
            if access_token and refresh_token:
                logger.info("Using Gmail credentials from .env (USER_ACCESS_TOKEN, USER_REFRESH_TOKEN)")
                if not google_client_id:
                    google_client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip() or None
                if not google_client_secret:
                    google_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip() or None
        if not access_token:
            raise HTTPException(status_code=400, detail="No Gmail credentials provided. Please connect your Gmail account first or set USER_ACCESS_TOKEN and USER_REFRESH_TOKEN in .env")
        
        # Cap limit to prevent slow loading
        actual_limit = min(request.limit, 50)  # Max 50 emails for performance
        if request.limit > 50:
            logger.info(f"Requested {request.limit} emails, capping to {actual_limit} for performance")
        logger.info(f"Fetching {actual_limit} unread emails")
        emails, total_unread = await email_service.get_unread_emails(
            access_token=access_token,
            refresh_token=refresh_token,
            limit=actual_limit,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            query=request.query
        )
        logger.info(f"Successfully retrieved {len(emails)} emails")
        # Generate lightweight one-sentence summaries for each email (local fallback)
        try:
            import re as _lr
            def _local_summary(subject, body, sender, max_words=25):
                src = ' '.join(filter(None, [subject or '', (body or '')[:600]]))
                src = _lr.sub(r'[^\w\s\.,:;\-@\(\)\'"/]', ' ', src)
                src = _lr.sub(r'\s+', ' ', src).strip()
                if not src:
                    return f"Short message from {sender}."
                low = src.lower()
                if any(k in low for k in ['invoice', 'payment', 'receipt', 'bill', 'charged']):
                    return f"Payment/finance-related message concerning {subject or 'your account'}."
                if any(k in low for k in ['schedule', 'meeting', 'call', 'reschedule']):
                    return f"Request to schedule or update a meeting regarding {subject or 'the topic'}."
                if any(k in low for k in ['unsubscribe', 'opt out', 'subscription']):
                    return f"Subscription or marketing message (unsubscribe link likely present)."
                words = src.split()[:max_words]
                sentence = ' '.join(words).strip()
                if not sentence.endswith('.'):
                    sentence = sentence.rstrip('.,;:') + '.'
                return sentence

            summarized_emails = []
            for e in emails:
                sender = (e.get('from_name') or e.get('from_email') or 'Unknown')
                subject = e.get('subject') or ''
                body = e.get('body') or ''
                summary = _local_summary(subject, body, sender)
                # ensure we don't mutate original objects badly - copy dict
                new_e = dict(e)
                new_e['summary'] = summary
                summarized_emails.append(new_e)
        except Exception:
            summarized_emails = emails

        return EmailListResponse(
            success=True,
            count=len(summarized_emails),
            total_unread=total_unread,
            emails=summarized_emails
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
async def reply_to_email(
    request: EmailReplyRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """
    Reply to a specific email using user's credentials
    Uses per-user credentials from database if authenticated, otherwise uses request credentials
    
    Args:
        request: Reply details including user credentials, message ID or sender email
        user_id: User ID from JWT token (optional - for backward compatibility)
        db: Database session
    
    Returns:
        Operation status
    """
    try:
        # Try to get user's Gmail credentials from database first (if authenticated)
        access_token = None
        refresh_token = None
        google_client_id = None
        google_client_secret = None
        
        if user_id and DATABASE_AVAILABLE:
            from config_helpers import get_gmail_config
            from user_service_helpers import get_user_gmail_credentials
            gmail_config = get_gmail_config(db, user_id)
            user_creds = get_user_gmail_credentials(db, user_id)
            if gmail_config:
                google_client_id = gmail_config.get('google_client_id')
                google_client_secret = gmail_config.get('google_client_secret')
            if user_creds and user_creds.get('access_token'):
                access_token = user_creds['access_token']
                refresh_token = user_creds.get('refresh_token')
                logger.info(f"Using per-user Gmail credentials for user {user_id}")
        
        # Fallback to credentials from request body (backward compatibility)
        if not access_token and request.user_credentials and request.user_credentials.access_token:
            access_token = request.user_credentials.access_token
            refresh_token = request.user_credentials.refresh_token
            logger.info("Using credentials from request body (backward compatibility)")
        if not access_token:
            access_token = (os.getenv('USER_ACCESS_TOKEN') or '').strip()
            refresh_token = (os.getenv('USER_REFRESH_TOKEN') or '').strip()
            if access_token and refresh_token:
                logger.info("Using Gmail credentials from .env (USER_ACCESS_TOKEN, USER_REFRESH_TOKEN)")
                if not google_client_id:
                    google_client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip() or None
                if not google_client_secret:
                    google_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip() or None
        if not access_token:
            raise HTTPException(status_code=400, detail="No Gmail credentials provided. Please connect your Gmail account first or set USER_ACCESS_TOKEN and USER_REFRESH_TOKEN in .env")
        
        logger.info(f"Replying to email from {request.sender_email or request.message_id}")
        message_id = await email_service.reply_to_email(
            access_token=access_token,
            refresh_token=refresh_token,
            message_id=request.message_id,
            sender_email=request.sender_email,
            body=request.body,
            html=request.html,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret
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
async def mark_email_read(
    request: MarkEmailReadRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """
    Mark an email as read in Gmail
    Uses per-user credentials from database if authenticated, otherwise uses request credentials
    
    Args:
        request: User credentials and message ID to mark as read
        user_id: User ID from JWT token (optional - for backward compatibility)
        db: Database session
    
    Returns:
        Operation status
    """
    try:
        # Try to get user's Gmail credentials from database first (if authenticated)
        access_token = None
        refresh_token = None
        google_client_id = None
        google_client_secret = None
        
        if user_id and DATABASE_AVAILABLE:
            from config_helpers import get_gmail_config
            from user_service_helpers import get_user_gmail_credentials
            gmail_config = get_gmail_config(db, user_id)
            user_creds = get_user_gmail_credentials(db, user_id)
            if gmail_config:
                google_client_id = gmail_config.get('google_client_id')
                google_client_secret = gmail_config.get('google_client_secret')
            if user_creds and user_creds.get('access_token'):
                access_token = user_creds['access_token']
                refresh_token = user_creds.get('refresh_token')
                logger.info(f"Using per-user Gmail credentials for user {user_id}")
        
        # Fallback to credentials from request body (backward compatibility)
        if not access_token and request.user_credentials and request.user_credentials.access_token:
            access_token = request.user_credentials.access_token
            refresh_token = request.user_credentials.refresh_token
            logger.info("Using credentials from request body (backward compatibility)")
        if not access_token:
            access_token = (os.getenv('USER_ACCESS_TOKEN') or '').strip()
            refresh_token = (os.getenv('USER_REFRESH_TOKEN') or '').strip()
            if access_token and refresh_token:
                logger.info("Using Gmail credentials from .env (USER_ACCESS_TOKEN, USER_REFRESH_TOKEN)")
                if not google_client_id:
                    google_client_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip() or None
                if not google_client_secret:
                    google_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip() or None
        if not access_token:
            raise HTTPException(status_code=400, detail="No Gmail credentials provided. Please connect your Gmail account first or set USER_ACCESS_TOKEN and USER_REFRESH_TOKEN in .env")
        
        logger.info(f"Marking email {request.message_id} as read")
        await email_service.mark_email_as_read(
            access_token=access_token,
            refresh_token=refresh_token,
            message_id=request.message_id,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret
        )
        return OperationResponse(
            success=True,
            message="Email marked as read",
            data={"message_id": request.message_id}
        )
    except Exception as e:
        logger.error(f"Error marking email as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------- Contacts API -----------------
from models.schemas import ContactCreateRequest, ContactResolveRequest, ContactResponse
from models.schemas import ContactListResponse


@app.post("/api/contacts", response_model=OperationResponse)
async def create_contact(
    request: ContactCreateRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """Create or update a contact (user-scoped if authenticated)."""
    try:
        # Normalize
        name = request.name.strip()
        email = request.email.strip()

        # Try to find existing contact for this user/email
        query = db.query(Contact).filter(Contact.email == email)
        if user_id:
            query = query.filter(Contact.user_id == user_id)
        else:
            query = query.filter(Contact.user_id == None)

        existing = query.first()
        if existing:
            existing.name = name
            db.add(existing)
            db.commit()
            return OperationResponse(success=True, message=f"Contact updated: {name}", data={"id": existing.id})

        new_contact = Contact(user_id=user_id, name=name, email=email)
        db.add(new_contact)
        db.commit()
        return OperationResponse(success=True, message=f"Contact saved: {name}", data={"id": new_contact.id})

    except Exception as e:
        logger.error(f"Error creating contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/contacts/resolve", response_model=ContactResponse)
async def resolve_contact(
    request: ContactResolveRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """Resolve a name or email to a saved contact. Returns first match or empty."""
    try:
        q = (request.query or '').strip()
        if not q:
            return ContactResponse(success=False, message="Empty query")

        # If it looks like an email, try exact match first
        if '@' in q:
            contact = db.query(Contact).filter(Contact.email.ilike(q))
            if user_id:
                contact = contact.filter(Contact.user_id == user_id)
            else:
                contact = contact.filter(Contact.user_id == None)
            result = contact.first()
            if result:
                return ContactResponse(success=True, name=result.name, email=result.email)

        # Otherwise try name fuzzy match (case-insensitive contains)
        contact_q = db.query(Contact)
        if user_id:
            # Authenticated: prefer user-scoped contacts
            contact_q = contact_q.filter(Contact.user_id == user_id)
        else:
            # Unauthenticated callers (chat UI without JWT / simple server)
            # should be allowed to search across all contacts (global + user-scoped)
            # so name lookups like "Abel" find matches even if they're stored
            # under a specific user. Keep ordering by creation time for recent matches.
            contact_q = contact_q

        contact_q = contact_q.filter(Contact.name.ilike(f"%{q}%"))
        result = contact_q.order_by(Contact.created_at.desc()).first()
        if result:
            return ContactResponse(success=True, name=result.name, email=result.email)

        # No match
        return ContactResponse(success=False, message="No contact found")
    except Exception as e:
        logger.error(f"Error resolving contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/contacts/search", response_model=ContactListResponse)
async def search_contacts(
    request: ContactResolveRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional),
    db: Session = Depends(get_db)
):
    """Return all contacts matching a name substring (case-insensitive)."""
    try:
        q = (request.query or '').strip()
        if not q:
            return ContactListResponse(success=False, count=0, contacts=[])

        contact_q = db.query(Contact)
        if user_id:
            contact_q = contact_q.filter(Contact.user_id == user_id)
        else:
            contact_q = contact_q.filter(Contact.user_id == None)

        results = contact_q.filter(Contact.name.ilike(f"%{q}%")).order_by(Contact.created_at.desc()).all()
        contacts = []
        for r in results:
            contacts.append({"name": r.name, "email": r.email})

        return ContactListResponse(success=True, count=len(contacts), contacts=contacts)
    except Exception as e:
        logger.error(f"Error searching contacts: {e}")
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


# WhatsApp API Endpoints
@app.post("/api/whatsapp/initialize")
async def initialize_whatsapp():
    """Initialize WhatsApp service (lazy initialization when tab is clicked)"""
    try:
        # Check if already initialized
        if whatsapp_service.page and whatsapp_service.is_connected:
            return {"success": True, "message": "Already initialized and connected", "is_connected": True}
        
        # Initialize if not already done
        if not whatsapp_service.page:
            logger.info("Initializing WhatsApp service (triggered by tab click)...")
            await whatsapp_service.initialize()
        
        # Check connection status
        is_connected = whatsapp_service.is_connected
        has_session = whatsapp_service.has_session
        
        if is_connected:
            return {"success": True, "message": "Connected to WhatsApp", "is_connected": True, "has_session": has_session}
        else:
            # Return status indicating QR code may be needed
            return {
                "success": True, 
                "message": "Initialized - authentication may be required", 
                "is_connected": False,
                "has_session": has_session
            }
    except Exception as e:
        logger.error(f"Error initializing WhatsApp: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/whatsapp/qr-code")
async def get_whatsapp_qr_code():
    """
    Get WhatsApp QR code for authentication
    Alternative to Node.js server endpoint - works on VPS
    """
    try:
        # If already authenticated, return success
        if whatsapp_service.is_connected:
            return {
                "success": True,
                "is_authenticated": True,
                "message": "Already authenticated"
            }
        
        # Ensure WhatsApp service is initialized
        if not whatsapp_service.page:
            try:
                await whatsapp_service.initialize()
                # Wait a moment for page to load
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Error initializing WhatsApp service: {e}")
                return {
                    "success": False,
                    "is_authenticated": False,
                    "message": f"Error initializing: {str(e)}"
                }
        
        # If a session exists on disk, do NOT return a QR image to the client.
        # The app UI should show a "restoring" state instead of prompting a fresh QR
        # when authentication info is already present in the session storage.
        if whatsapp_service.has_session:
            return {
                "success": False,
                "is_authenticated": False,
                "has_session": True,
                "message": "Session exists - restoring authentication (QR not shown)"
            }

        # Get QR code from page (only when no session info exists)
        qr_code_data = await whatsapp_service.get_qr_code()

        if qr_code_data:
            return {
                "success": True,
                "qr_code": qr_code_data,
                "is_authenticated": False,
                "message": "Scan the QR code with WhatsApp to connect"
            }
        else:
            # QR code not available yet - might still be loading
            return {
                "success": False,
                "is_authenticated": False,
                "message": "QR code not available yet. Please wait..."
            }
    except Exception as e:
        logger.error(f"Error getting QR code: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "is_authenticated": False,
            "error": str(e)
        }

@app.get("/api/whatsapp/status", response_model=WhatsAppStatusResponse)
async def get_whatsapp_status():
    """Check WhatsApp connection and authentication status"""
    try:
        # Fast path: if already connected, return immediately
        if whatsapp_service.is_connected:
            return WhatsAppStatusResponse(
                success=True,
                is_connected=True,
                is_authenticated=True,
                message="Connected to WhatsApp"
            )
        
        # Check connection status - this will check authentication
        is_connected, status_message = await whatsapp_service.check_connection_status()
        
        # If connected, we're authenticated
        if is_connected:
            is_authenticated = True
            # Ensure session is saved
            if not whatsapp_service.has_session:
                whatsapp_service.has_session = True
                try:
                    await whatsapp_service._save_session()
                    logger.info("Session saved in status endpoint")
                except Exception as e:
                    logger.error(f"Error saving session in status endpoint: {e}")
            status_message = "Connected to WhatsApp"
        else:
            # Not connected - check if we have a session that's restoring
            is_authenticated = False
            if whatsapp_service.has_session:
                status_message = "Session found - authentication is restoring. Please wait..."
        
        return WhatsAppStatusResponse(
            success=True,
            is_connected=is_connected,
            is_authenticated=is_authenticated,
            message=status_message,
            has_session=whatsapp_service.has_session
        )
    except Exception as e:
        logger.error(f"Error checking WhatsApp status: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/whatsapp/contacts", response_model=WhatsAppContactsResponse)
async def get_whatsapp_contacts(request: GetWhatsAppContactsRequest):
    """Get WhatsApp contacts/chats"""
    try:
        contacts = await whatsapp_service.get_contacts()
        # Apply limit if needed
        if request.limit > 0:
            contacts = contacts[:request.limit]
        return WhatsAppContactsResponse(
            success=True,
            count=len(contacts),
            contacts=contacts
        )
    except Exception as e:
        logger.error(f"Error fetching WhatsApp contacts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/whatsapp/debug")
async def debug_whatsapp():
    """Debug endpoint to check WhatsApp page state"""
    try:
        debug_info = await whatsapp_service.page.evaluate("""
            () => {
                const info = {
                    url: window.location.href,
                    title: document.title,
                    readyState: document.readyState,
                    hasChatList: !!document.querySelector('div[data-testid="chatlist"]'),
                    hasConversationPanel: !!document.querySelector('div[data-testid="conversation-panel-wrapper"]'),
                    chatCount: document.querySelectorAll('div[data-testid="chat"]').length,
                    selectableTextCount: document.querySelectorAll('span.selectable-text').length,
                    msgContainerCount: document.querySelectorAll('div[data-testid="msg-container"]').length,
                    allDivsCount: document.querySelectorAll('div').length,
                    conversationAreaExists: !!document.querySelector('div[data-testid="conversation-panel-wrapper"]') ||
                                          !!document.querySelector('div[role="application"]')
                };
                
                // Try to get some sample text from selectable-text spans
                const textSpans = document.querySelectorAll('span.selectable-text');
                info.sampleTexts = Array.from(textSpans).slice(0, 5).map(span => span.textContent.trim()).filter(t => t.length > 0);
                
                return info;
            }
        """) if whatsapp_service.page else {"error": "Page not initialized"}
        
        return {
            "success": True,
            "is_connected": whatsapp_service.is_connected,
            "has_session": whatsapp_service.has_session,
            "page_info": debug_info
        }
    except Exception as e:
        logger.error(f"Debug error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "is_connected": whatsapp_service.is_connected if hasattr(whatsapp_service, 'is_connected') else False,
            "has_session": whatsapp_service.has_session if hasattr(whatsapp_service, 'has_session') else False
        }


@app.post("/api/whatsapp/send", response_model=SendWhatsAppMessageResponse)
async def send_whatsapp_message(request: SendWhatsAppMessageRequest):
    """Send a WhatsApp message to a contact"""
    try:
        message_id = await whatsapp_service.send_message(
            contact_id=request.contact_id,
            text=request.text
        )
        return SendWhatsAppMessageResponse(
            success=True,
            message="Message sent successfully",
            message_id=message_id
        )
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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


# ==================== SETTINGS/ENV MANAGEMENT ENDPOINTS ====================

class EnvVariablesRequest(BaseModel):
    """Request model for updating environment variables"""
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    telegram_phone_number: Optional[str] = None
    slack_user_token: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    openai_api_key: Optional[str] = None
    user_access_token: Optional[str] = None
    user_refresh_token: Optional[str] = None
    user_email: Optional[str] = None
    bing_search_api_key: Optional[str] = None
    people_api_key: Optional[str] = None


# Keys shown in the Settings tab; all read from and written to .env only
SETTINGS_ENV_KEYS = [
    "OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "USER_EMAIL", "USER_ACCESS_TOKEN", "USER_REFRESH_TOKEN",
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE_NUMBER",
    "SLACK_USER_TOKEN", "BING_SEARCH_API_KEY", "PEOPLE_API_KEY",
]


@app.get("/api/settings/env")
async def get_env_variables(
    user_id: int = Depends(get_current_user_id) if AUTH_AVAILABLE and security else None,
):
    """
    Get current environment variables from the .env file only (not the database).
    Used by the Settings tab to display and edit .env values.
    """
    if not user_id and AUTH_AVAILABLE and security:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        env_path, env_exists = _get_env_file_path()
        # Read every key from .env file only (no database)
        final_vars = {}
        for key in SETTINGS_ENV_KEYS:
            val = _read_env_key_from_dotenv(key)
            final_vars[key] = (val or "").strip()

        return {
            "success": True,
            "variables": final_vars,
            "env_file_path": env_path,
            "env_file_exists": env_exists,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading settings from .env: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to read settings: {str(e)}")


# Map request field names (snake_case) to .env key names (UPPER_SNAKE)
_REQUEST_TO_ENV_KEY = {
    "openai_api_key": "OPENAI_API_KEY",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "user_email": "USER_EMAIL",
    "user_access_token": "USER_ACCESS_TOKEN",
    "user_refresh_token": "USER_REFRESH_TOKEN",
    "telegram_api_id": "TELEGRAM_API_ID",
    "telegram_api_hash": "TELEGRAM_API_HASH",
    "telegram_phone_number": "TELEGRAM_PHONE_NUMBER",
    "slack_user_token": "SLACK_USER_TOKEN",
    "bing_search_api_key": "BING_SEARCH_API_KEY",
    "people_api_key": "PEOPLE_API_KEY",
}


@app.post("/api/settings/env")
async def update_env_variables(
    request: EnvVariablesRequest,
    user_id: int = Depends(get_current_user_id) if AUTH_AVAILABLE and security else None,
    db: Session = Depends(get_db) if DATABASE_AVAILABLE else None,
):
    """
    Update environment variables in the .env file. All values from the Settings tab
    are written to the project .env file. Optionally syncs Gmail/Telegram/Slack to DB
    for backward compatibility with code that reads from the database.
    """
    if not user_id and AUTH_AVAILABLE and security:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        from config_helpers import (
            update_gmail_config,
            update_telegram_config,
            update_slack_config,
        )

        # Build flat dict from request (only non-None fields)
        req_dict = request.model_dump(exclude_none=True)
        success_count = 0
        errors = []

        # 1) Write every provided key to .env file
        for req_key, env_key in _REQUEST_TO_ENV_KEY.items():
            if req_key not in req_dict:
                continue
            raw = req_dict[req_key]
            value = (raw.strip() if raw else "")
            if _write_env_key_to_dotenv(env_key, value):
                success_count += 1
            else:
                errors.append(f"Failed to write {env_key} to .env")

        # 2) Optionally sync to DB for Gmail/Telegram/Slack so existing code paths still work
        if DATABASE_AVAILABLE and db is not None and user_id is not None:
            gmail_updates = {}
            if "google_client_id" in req_dict:
                gmail_updates["google_client_id"] = (req_dict["google_client_id"] or "").strip() or None
            if "google_client_secret" in req_dict:
                gmail_updates["google_client_secret"] = (req_dict["google_client_secret"] or "").strip() or None
            if "user_access_token" in req_dict:
                gmail_updates["user_access_token"] = (req_dict["user_access_token"] or "").strip() or None
            if "user_refresh_token" in req_dict:
                gmail_updates["user_refresh_token"] = (req_dict["user_refresh_token"] or "").strip() or None
            if "user_email" in req_dict:
                gmail_updates["user_email"] = (req_dict["user_email"] or "").strip() or None
            if gmail_updates and not update_gmail_config(db, user_id, **gmail_updates):
                errors.append("Failed to sync Gmail config to database")

            telegram_updates = {}
            if "telegram_api_id" in req_dict:
                telegram_updates["telegram_api_id"] = (req_dict["telegram_api_id"] or "").strip() or None
            if "telegram_api_hash" in req_dict:
                telegram_updates["telegram_api_hash"] = (req_dict["telegram_api_hash"] or "").strip() or None
            if "telegram_phone_number" in req_dict:
                telegram_updates["telegram_phone_number"] = (req_dict["telegram_phone_number"] or "").strip() or None
            if telegram_updates and not update_telegram_config(db, user_id, **telegram_updates):
                errors.append("Failed to sync Telegram config to database")

            if "slack_user_token" in req_dict:
                slack_token = (req_dict["slack_user_token"] or "").strip()
                if not update_slack_config(db, user_id, slack_token):
                    errors.append("Failed to sync Slack config to database")

        if errors:
            logger.warning(f"Some settings updates failed: {errors}")

        return {
            "success": True,
            "message": "Settings saved to .env file.",
            "updated_sections": success_count,
            "errors": errors if errors else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


# ==================== FIND EMAIL BY NAME (CONTACTS + BING/PEOPLE API) ====================

class FindEmailRequest(BaseModel):
    """Request body for find-email endpoint"""
    name: str


@app.post("/api/contacts/find-email")
async def find_email_by_name(
    request: FindEmailRequest,
    user_id: Optional[int] = Depends(get_current_user_id_optional) if AUTH_AVAILABLE else None,
    db: Session = Depends(get_db) if DATABASE_AVAILABLE else None,
):
    """
    Find a person's email address by name. Checks the contacts database first;
    if not found, uses Bing Search API and/or People API (when keys are in .env).
    Saves newly found emails to the contacts table.
    """
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please provide a name to look up.")

    # 1) Check database for existing contact
    if DATABASE_AVAILABLE and db is not None:
        try:
            matches = db.query(Contact).filter(Contact.name.ilike(f"%{name}%")).all()
            if matches:
                c = matches[0]
                return {
                    "success": True,
                    "email": c.email,
                    "name": c.name,
                    "source": "database",
                    "message": f"Found in contacts: {c.email}",
                }
            # Broader match (tokenized name)
            all_contacts = db.query(Contact).all()
            q = name.lower()
            for c in all_contacts:
                n = (c.name or "").lower()
                if q in n or q in (c.email or "").lower():
                    return {
                        "success": True,
                        "email": c.email,
                        "name": c.name,
                        "source": "database",
                        "message": f"Found in contacts: {c.email}",
                    }
        except Exception as e:
            logger.warning(f"Contact lookup failed: {e}")

    # 2) No DB match – check if API keys are configured
    status = email_finder_keys_status()
    if not status.get("any_configured"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Email finder APIs are not configured. These are paid services. "
                "To find email addresses by name when they are not in your contacts, add at least one of these keys to the .env file or the Settings tab:\n\n"
                "• BING_SEARCH_API_KEY – Bing Web Search API (Azure). Get a key at https://www.microsoft.com/en-us/bing/apis/bing-web-search-api\n"
                "• PEOPLE_API_KEY – e.g. Hunter.io Email Finder. Get a key at https://hunter.io/api\n\n"
                "After adding a key, restart the app and try again."
            ),
        )

    # 3) Call resolver
    try:
        candidates = resolve_name_to_emails(name, max_results=5)
    except Exception as e:
        logger.error(f"Resolver error for '{name}': {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Could not search for this person's email. Please try again later. Error: {str(e)}",
        )

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No email address could be found for \"{name}\". "
                "Possible reasons: the person's email is not publicly available, search results did not contain a valid address, "
                "or the name is too generic. Try adding more context (e.g. company name) or add the contact manually in Settings."
            ),
        )

    best = candidates[0]
    email = (best.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=404, detail=f"No valid email found for \"{name}\".")

    # 4) Save to contacts for future lookups
    if DATABASE_AVAILABLE and db is not None:
        try:
            existing = db.query(Contact).filter(Contact.email.ilike(email)).first()
            if not existing:
                new_contact = Contact(name=name, email=email, user_id=user_id)
                db.add(new_contact)
                db.commit()
                logger.info(f"Saved new contact: {name} -> {email}")
        except Exception as e:
            logger.warning(f"Could not save contact: {e}")
            db.rollback()

    return {
        "success": True,
        "email": email,
        "name": name,
        "source": "api",
        "message": f"Found via search and saved to contacts: {email}",
    }


@app.post("/api/settings/gmail-token")
async def generate_gmail_token(background_tasks: BackgroundTasks):
    """
    Run get_gmail_token.py script to generate Gmail OAuth tokens
    
    Returns:
        Success status and instructions
    """
    try:
        import subprocess
        import sys
        from pathlib import Path
        
        # Get the path to get_gmail_token.py
        script_path = Path(__file__).parent / "get_gmail_token.py"
        
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="get_gmail_token.py not found")
        
        # Run the script in background
        def run_gmail_token_script():
            try:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                logger.info(f"Gmail token script output: {result.stdout}")
                if result.stderr:
                    logger.error(f"Gmail token script errors: {result.stderr}")
                
                logger.info("Gmail token generation completed. Please restart the application manually for changes to take effect.")
            except subprocess.TimeoutExpired:
                logger.error("Gmail token script timed out")
            except Exception as e:
                logger.error(f"Error running Gmail token script: {e}")
        
        # Run in background
        background_tasks.add_task(run_gmail_token_script)
        
        return {
            "success": True,
            "message": "Gmail token generation started. Please check the console for OAuth flow. Please restart the application manually after completion."
        }
    except Exception as e:
        logger.error(f"Error starting Gmail token generation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start Gmail token generation: {str(e)}")


# ==================== END SETTINGS/ENV MANAGEMENT ENDPOINTS ====================

# ==================== USER SERVICE CREDENTIALS ENDPOINTS ====================

class SaveServiceCredentialsRequest(BaseModel):
    """Request model for saving service credentials"""
    service_name: str  # 'gmail', 'whatsapp', 'telegram', 'slack'
    credentials_data: Dict  # Service-specific credentials (e.g., {access_token, refresh_token} for Gmail)

class ServiceCredentialsResponse(BaseModel):
    """Response model for service credentials"""
    success: bool
    message: str
    service_name: str
    is_connected: bool

@app.post("/api/user/services/{service_name}/connect", response_model=ServiceCredentialsResponse)
async def save_service_credentials(
    service_name: str,
    request: SaveServiceCredentialsRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Save or update service credentials for the authenticated user
    Service names: 'gmail', 'whatsapp', 'telegram', 'slack'
    """
    if not DATABASE_AVAILABLE or not UserServiceCredential or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Validate service name
        valid_services = ['gmail', 'whatsapp', 'telegram', 'slack']
        if service_name.lower() not in valid_services:
            raise HTTPException(status_code=400, detail=f"Invalid service name. Must be one of: {', '.join(valid_services)}")
        
        service_name = service_name.lower()
        
        # Check if credentials already exist
        existing = db.query(UserServiceCredential).filter(
            UserServiceCredential.user_id == user_id,
            UserServiceCredential.service_name == service_name
        ).first()
        
        if existing:
            # Update existing credentials
            existing.credentials_data = request.credentials_data
            existing.is_active = True
            existing.updated_at = datetime.now()
            db.commit()
            db.refresh(existing)
            logger.info(f"Updated {service_name} credentials for user {user_id}")
        else:
            # Create new credentials
            new_credential = UserServiceCredential(
                user_id=user_id,
                service_name=service_name,
                credentials_data=request.credentials_data,
                is_active=True,
                is_connected=False
            )
            db.add(new_credential)
            db.commit()
            db.refresh(new_credential)
            logger.info(f"Created {service_name} credentials for user {user_id}")
        
        return ServiceCredentialsResponse(
            success=True,
            message=f"{service_name.capitalize()} credentials saved successfully",
            service_name=service_name,
            is_connected=False  # Will be updated when connection is verified
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving service credentials: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


@app.get("/api/user/services/{service_name}/credentials")
async def get_service_credentials(
    service_name: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Get service credentials for the authenticated user
    Returns credentials data (sensitive fields may be masked)
    """
    if not DATABASE_AVAILABLE or not UserServiceCredential or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        service_name = service_name.lower()
        
        # Get credentials
        credential = db.query(UserServiceCredential).filter(
            UserServiceCredential.user_id == user_id,
            UserServiceCredential.service_name == service_name,
            UserServiceCredential.is_active == True
        ).first()
        
        if not credential:
            return {
                "success": False,
                "message": f"{service_name.capitalize()} credentials not found. Please connect your account.",
                "has_credentials": False
            }
        
        # Return credentials (mask sensitive data if needed)
        credentials_data = credential.credentials_data.copy()
        
        # Mask sensitive tokens in response
        if service_name == 'gmail':
            if 'access_token' in credentials_data:
                credentials_data['access_token'] = credentials_data['access_token'][:20] + '...' if len(credentials_data['access_token']) > 20 else '***'
            if 'refresh_token' in credentials_data:
                credentials_data['refresh_token'] = credentials_data['refresh_token'][:20] + '...' if len(credentials_data['refresh_token']) > 20 else '***'
        
        return {
            "success": True,
            "has_credentials": True,
            "service_name": service_name,
            "is_connected": credential.is_connected,
            "credentials_data": credentials_data,  # Masked version
            "last_connected_at": credential.last_connected_at.isoformat() if credential.last_connected_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting service credentials: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get credentials: {str(e)}")


@app.delete("/api/user/services/{service_name}/disconnect")
async def disconnect_service(
    service_name: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Disconnect/remove service credentials for the authenticated user
    """
    if not DATABASE_AVAILABLE or not UserServiceCredential or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        service_name = service_name.lower()
        
        # Find and delete credentials
        credential = db.query(UserServiceCredential).filter(
            UserServiceCredential.user_id == user_id,
            UserServiceCredential.service_name == service_name
        ).first()
        
        if credential:
            db.delete(credential)
            db.commit()
            logger.info(f"Disconnected {service_name} for user {user_id}")
            return {
                "success": True,
                "message": f"{service_name.capitalize()} disconnected successfully"
            }
        else:
            return {
                "success": False,
                "message": f"{service_name.capitalize()} not connected"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error disconnecting service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to disconnect service: {str(e)}")


@app.get("/api/user/services/status")
async def get_all_services_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Get status of all connected services for the authenticated user
    """
    if not DATABASE_AVAILABLE or not UserServiceCredential or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get all active credentials for user
        credentials_list = db.query(UserServiceCredential).filter(
            UserServiceCredential.user_id == user_id,
            UserServiceCredential.is_active == True
        ).all()
        
        services_status = {}
        for cred in credentials_list:
            services_status[cred.service_name] = {
                "is_connected": cred.is_connected,
                "last_connected_at": cred.last_connected_at.isoformat() if cred.last_connected_at else None,
                "has_credentials": True
            }
        
        # Add services that are not connected
        all_services = ['gmail', 'whatsapp', 'telegram', 'slack']
        for service in all_services:
            if service not in services_status:
                services_status[service] = {
                    "is_connected": False,
                    "last_connected_at": None,
                    "has_credentials": False
                }
        
        return {
            "success": True,
            "services": services_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting services status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get services status: {str(e)}")


# ==================== END USER SERVICE CREDENTIALS ENDPOINTS ====================

# ==================== USER MANAGEMENT ENDPOINTS ====================

class UpdateUserClassificationRequest(BaseModel):
    """Request model for updating user classification"""
    user_classification_id: int

class DeleteUserRequest(BaseModel):
    """Request model for deleting a user"""
    user_id: int

@app.get("/api/users/all")
async def get_all_users(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Get all users in the database
    Only accessible to users with user_classification_id = 1
    """
    if not DATABASE_AVAILABLE or not User or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        user_id = extract_user_id_from_token(token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get current user and check classification
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user has admin privileges (user_classification_id = 1)
        user_classification_id = getattr(current_user, 'user_classification_id', 0) or 0
        if user_classification_id != 1:
            raise HTTPException(status_code=403, detail="Access denied. Admin privileges required.")
        
        # Get all users
        users = db.query(User).all()
        
        # Return user data (excluding passwords)
        users_data = []
        for user in users:
            users_data.append({
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "user_classification_id": getattr(user, 'user_classification_id', 0) or 0,
                "create_at": user.create_at.isoformat() if user.create_at else None
            })
        
        logger.info(f"User {current_user.email} retrieved all users list")
        
        return {
            "success": True,
            "users": users_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve users: {str(e)}")


@app.put("/api/users/{user_id}/classification")
async def update_user_classification(
    user_id: int,
    request: UpdateUserClassificationRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Update a user's classification_id
    Only accessible to users with user_classification_id = 1
    """
    if not DATABASE_AVAILABLE or not User or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        current_user_id = extract_user_id_from_token(token)
        
        if not current_user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get current user and check classification
        current_user = db.query(User).filter(User.id == current_user_id).first()
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user has admin privileges (user_classification_id = 1)
        user_classification_id = getattr(current_user, 'user_classification_id', 0) or 0
        if user_classification_id != 1:
            raise HTTPException(status_code=403, detail="Access denied. Admin privileges required.")
        
        # Get target user
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")
        
        # Prevent user from changing their own classification
        if target_user.id == current_user.id:
            raise HTTPException(status_code=400, detail="You cannot change your own classification")
        
        # Update classification
        target_user.user_classification_id = request.user_classification_id
        db.commit()
        db.refresh(target_user)
        
        logger.info(f"User {current_user.email} updated classification for user {target_user.email} to {request.user_classification_id}")
        
        return {
            "success": True,
            "message": f"User classification updated successfully",
            "user": {
                "id": target_user.id,
                "email": target_user.email,
                "name": target_user.name,
                "user_classification_id": target_user.user_classification_id
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating user classification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user classification: {str(e)}")


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Delete a user from the database
    Only accessible to users with user_classification_id = 1
    """
    if not DATABASE_AVAILABLE or not User or not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Verify token and get user
        token = credentials.credentials
        current_user_id = extract_user_id_from_token(token)
        
        if not current_user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get current user and check classification
        current_user = db.query(User).filter(User.id == current_user_id).first()
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user has admin privileges (user_classification_id = 1)
        user_classification_id = getattr(current_user, 'user_classification_id', 0) or 0
        if user_classification_id != 1:
            raise HTTPException(status_code=403, detail="Access denied. Admin privileges required.")
        
        # Get target user
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Prevent user from deleting themselves
        if target_user.id == current_user.id:
            raise HTTPException(status_code=400, detail="You cannot delete your own account")
        
        # Store email for logging
        deleted_email = target_user.email
        
        # Delete user
        db.delete(target_user)
        db.commit()
        
        logger.info(f"User {current_user.email} deleted user {deleted_email}")
        
        return {
            "success": True,
            "message": f"User {deleted_email} deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting user: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")

# ==================== END USER MANAGEMENT ENDPOINTS ====================


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
