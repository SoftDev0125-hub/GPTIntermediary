"""
Email verification code service
Generates and stores verification codes for user registration
"""
import random
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# In-memory storage for verification codes
# Format: {email: {'code': str, 'expires_at': datetime, 'attempts': int}}
verification_codes: Dict[str, Dict] = {}

# Verification code settings
CODE_EXPIRY_MINUTES = 10  # Codes expire after 10 minutes
MAX_ATTEMPTS = 5  # Maximum verification attempts
CODE_LENGTH = 6  # 6-digit code


def generate_verification_code() -> str:
    """Generate a random 6-digit verification code"""
    return str(random.randint(100000, 999999))


def store_verification_code(email: str, code: str) -> None:
    """Store a verification code for an email"""
    expires_at = datetime.now() + timedelta(minutes=CODE_EXPIRY_MINUTES)
    verification_codes[email.lower()] = {
        'code': code,
        'expires_at': expires_at,
        'attempts': 0,
        'created_at': datetime.now()
    }
    logger.info(f"Verification code stored for {email.lower()}, expires at {expires_at}")


def verify_code(email: str, code: str) -> bool:
    """
    Verify a code for an email address
    
    Returns:
        True if code is valid, False otherwise
    """
    email = email.lower()
    
    if email not in verification_codes:
        logger.warning(f"No verification code found for {email}")
        return False
    
    code_data = verification_codes[email]
    
    # Check if code has expired
    if datetime.now() > code_data['expires_at']:
        logger.warning(f"Verification code expired for {email}")
        del verification_codes[email]
        return False
    
    # Check maximum attempts
    if code_data['attempts'] >= MAX_ATTEMPTS:
        logger.warning(f"Maximum verification attempts exceeded for {email}")
        del verification_codes[email]
        return False
    
    # Increment attempt counter
    code_data['attempts'] += 1
    
    # Check if code matches
    if code == code_data['code']:
        # Code is valid, remove it
        del verification_codes[email]
        logger.info(f"Verification code verified successfully for {email}")
        return True
    else:
        logger.warning(f"Invalid verification code attempt for {email}, attempt {code_data['attempts']}")
        return False


def get_code(email: str) -> Optional[str]:
    """Get the stored verification code for an email (for testing/debugging)"""
    email = email.lower()
    if email in verification_codes:
        code_data = verification_codes[email]
        if datetime.now() <= code_data['expires_at']:
            return code_data['code']
        else:
            # Code expired, remove it
            del verification_codes[email]
    return None


def cleanup_expired_codes() -> int:
    """Remove expired verification codes, returns count of removed codes"""
    now = datetime.now()
    expired_emails = [
        email for email, data in verification_codes.items()
        if now > data['expires_at']
    ]
    for email in expired_emails:
        del verification_codes[email]
    
    if expired_emails:
        logger.info(f"Cleaned up {len(expired_emails)} expired verification codes")
    return len(expired_emails)

