"""
Authentication utilities for password hashing and JWT token management
"""
import os
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from pathlib import Path
from dotenv import load_dotenv

# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_load_env_root / '.env')

# JWT settings
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-please-use-a-secure-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt directly
    Note: bcrypt has a 72-byte limit, so longer passwords are truncated
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string (bcrypt hash)
    """
    if not isinstance(password, str):
        password = str(password)
    
    # Convert to bytes and truncate to 72 bytes if necessary
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    # Hash using bcrypt directly (returns bytes, decode to string)
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash using bcrypt directly
    Note: Passwords longer than 72 bytes are truncated to match the hashing behavior
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against (bcrypt hash string)
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        # Truncate to 72 bytes if necessary (same as in hash_password)
        password_bytes = plain_password.encode('utf-8')
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        
        # Convert hashed_password to bytes if it's a string
        if isinstance(hashed_password, str):
            hashed_bytes = hashed_password.encode('utf-8')
        else:
            hashed_bytes = hashed_password
        
        # Verify using bcrypt
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token
    
    Args:
        data: Dictionary of data to encode in the token
        expires_delta: Optional expiration time delta
        
    Returns:
        JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def extract_user_id_from_token(token: str) -> Optional[int]:
    """
    Extract user ID from JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        User ID if valid token, None if invalid
    """
    payload = verify_token(token)
    if payload:
        return payload.get("user_id")
    return None

