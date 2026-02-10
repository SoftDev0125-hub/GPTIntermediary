"""
Simple email sender for verification codes using SMTP
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_load_env_root / '.env')
logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, code: str) -> bool:
    """
    Send verification code email using SMTP
    
    Args:
        to_email: Recipient email address
        code: 6-digit verification code
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Get SMTP settings from environment variables
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_user = os.getenv('SMTP_USER')
        smtp_password = os.getenv('SMTP_PASSWORD')
        smtp_from = os.getenv('SMTP_FROM', smtp_user)
        
        # If no SMTP credentials configured, log and return False
        if not smtp_user or not smtp_password:
            logger.warning("SMTP credentials not configured. Please set SMTP_USER and SMTP_PASSWORD in .env")
            logger.info(f"[DEMO] Verification code for {to_email}: {code}")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg['Subject'] = "Your Verification Code"
        
        # Plain text version
        text = f"""Your verification code is: {code}
        
This code will expire in 10 minutes.
        
If you didn't request this code, please ignore this email.
        """
        
        # HTML version
        html = f"""<html>
  <body>
    <h2>Verification Code</h2>
    <p>Your verification code is:</p>
    <h1 style="color: #667eea; font-size: 32px; letter-spacing: 5px;">{code}</h1>
    <p>This code will expire in 10 minutes.</p>
    <p>If you didn't request this code, please ignore this email.</p>
  </body>
</html>"""
        
        # Attach both versions
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Verification email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {to_email}: {str(e)}")
        # In case of error, log the code for debugging (in development)
        logger.info(f"[FALLBACK] Verification code for {to_email}: {code}")
        return False

