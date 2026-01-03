"""
Helper functions for managing per-user service credentials
"""
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from db_models import UserServiceCredential


def get_user_service_credentials(
    db: Session,
    user_id: int,
    service_name: str
) -> Optional[UserServiceCredential]:
    """
    Get service credentials for a user from the database
    
    Args:
        db: Database session
        user_id: User ID
        service_name: Service name ('gmail', 'whatsapp', 'telegram', 'slack')
    
    Returns:
        UserServiceCredential object or None if not found
    """
    try:
        credential = db.query(UserServiceCredential).filter(
            UserServiceCredential.user_id == user_id,
            UserServiceCredential.service_name == service_name.lower(),
            UserServiceCredential.is_active == True
        ).first()
        return credential
    except Exception as e:
        return None


def get_user_gmail_credentials(
    db: Session,
    user_id: int
) -> Optional[Dict[str, str]]:
    """
    Get Gmail credentials for a user
    
    Args:
        db: Database session
        user_id: User ID
    
    Returns:
        Dict with 'access_token' and 'refresh_token', or None if not found
    """
    credential = get_user_service_credentials(db, user_id, 'gmail')
    if credential and credential.credentials_data:
        cred_data = credential.credentials_data
        return {
            'access_token': cred_data.get('access_token'),
            'refresh_token': cred_data.get('refresh_token')
        }
    return None


def update_service_connection_status(
    db: Session,
    user_id: int,
    service_name: str,
    is_connected: bool,
    error_message: Optional[str] = None
):
    """
    Update the connection status of a service for a user
    
    Args:
        db: Database session
        user_id: User ID
        service_name: Service name
        is_connected: Whether the service is connected
        error_message: Optional error message if connection failed
    """
    try:
        credential = get_user_service_credentials(db, user_id, service_name)
        if credential:
            credential.is_connected = is_connected
            if is_connected:
                from datetime import datetime
                credential.last_connected_at = datetime.now()
            if error_message:
                credential.last_error = error_message
            db.commit()
            db.refresh(credential)
    except Exception as e:
        db.rollback()
        # Log error but don't raise - this is a helper function
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating service connection status: {e}")

