"""
Helper functions to retrieve configuration values from database
Replaces reading from .env file with per-user database storage
"""
from typing import Optional, Dict
from sqlalchemy.orm import Session
from db_models import GmailInfo, TelegramSession, SlackInfo, APIKey


def get_gmail_config(db: Session, user_id: int) -> Optional[Dict[str, Optional[str]]]:
    """
    Get Gmail configuration for a user from database
    
    Returns:
        Dict with keys: google_client_id, google_client_secret, user_access_token, 
        user_refresh_token, user_email, or None if not found
    """
    try:
        gmail_info = db.query(GmailInfo).filter(GmailInfo.user_id == user_id).first()
        if not gmail_info:
            return None
        
        return {
            'google_client_id': gmail_info.google_client_id,
            'google_client_secret': gmail_info.google_client_secret,
            'user_access_token': gmail_info.user_access_token,
            'user_refresh_token': gmail_info.user_refresh_token,
            'user_email': gmail_info.user_email
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting Gmail config for user {user_id}: {e}")
        return None


def get_openai_api_key(db: Session, user_id: int) -> Optional[str]:
    """
    Get OpenAI API key for a user from database
    
    Returns:
        API key string or None if not found
    """
    try:
        api_key = db.query(APIKey).filter(
            APIKey.user_id == user_id,
            APIKey.service_name == 'openai',
            APIKey.is_active == True
        ).first()
        
        if api_key:
            return api_key.api_key
        return None
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting OpenAI API key for user {user_id}: {e}")
        return None


def get_telegram_config(db: Session, user_id: int) -> Optional[Dict[str, Optional[str]]]:
    """
    Get Telegram configuration for a user from database
    
    Returns:
        Dict with keys: telegram_api_id, telegram_api_hash, telegram_phone_number, 
        or None if not found
    """
    try:
        telegram_session = db.query(TelegramSession).filter(
            TelegramSession.user_id == user_id
        ).first()
        
        if not telegram_session:
            return None
        
        return {
            'telegram_api_id': telegram_session.telegram_api_id,
            'telegram_api_hash': telegram_session.telegram_api_hash,
            'telegram_phone_number': telegram_session.telegram_phone_number
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting Telegram config for user {user_id}: {e}")
        return None


def get_slack_config(db: Session, user_id: int) -> Optional[Dict[str, Optional[str]]]:
    """
    Get Slack configuration for a user from database
    
    Returns:
        Dict with key: slack_user_token, or None if not found
    """
    try:
        slack_info = db.query(SlackInfo).filter(SlackInfo.user_id == user_id).first()
        if not slack_info:
            return None
        
        return {
            'slack_user_token': slack_info.slack_user_token
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting Slack config for user {user_id}: {e}")
        return None


def update_gmail_config(db: Session, user_id: int, **kwargs) -> bool:
    """
    Update Gmail configuration for a user in database
    
    Args:
        db: Database session
        user_id: User ID
        **kwargs: Fields to update (google_client_id, google_client_secret, 
                 user_access_token, user_refresh_token, user_email)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        gmail_info = db.query(GmailInfo).filter(GmailInfo.user_id == user_id).first()
        
        if not gmail_info:
            # Create new record
            gmail_info = GmailInfo(user_id=user_id)
            db.add(gmail_info)
        
        # Update fields
        if 'google_client_id' in kwargs:
            gmail_info.google_client_id = kwargs['google_client_id']
        if 'google_client_secret' in kwargs:
            gmail_info.google_client_secret = kwargs['google_client_secret']
        if 'user_access_token' in kwargs:
            gmail_info.user_access_token = kwargs['user_access_token']
        if 'user_refresh_token' in kwargs:
            gmail_info.user_refresh_token = kwargs['user_refresh_token']
        if 'user_email' in kwargs:
            gmail_info.user_email = kwargs['user_email']
        
        db.commit()
        db.refresh(gmail_info)
        return True
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating Gmail config for user {user_id}: {e}")
        return False


def update_openai_api_key(db: Session, user_id: int, api_key: str) -> bool:
    """
    Update OpenAI API key for a user in database
    
    Returns:
        True if successful, False otherwise
    """
    try:
        api_key_record = db.query(APIKey).filter(
            APIKey.user_id == user_id,
            APIKey.service_name == 'openai'
        ).first()
        
        if not api_key_record:
            # Create new record
            api_key_record = APIKey(
                user_id=user_id,
                service_name='openai',
                api_key=api_key,
                is_active=True
            )
            db.add(api_key_record)
        else:
            # Update existing
            api_key_record.api_key = api_key
            api_key_record.is_active = True
        
        db.commit()
        db.refresh(api_key_record)
        return True
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating OpenAI API key for user {user_id}: {e}")
        return False


def update_telegram_config(db: Session, user_id: int, **kwargs) -> bool:
    """
    Update Telegram configuration for a user in database
    
    Args:
        db: Database session
        user_id: User ID
        **kwargs: Fields to update (telegram_api_id, telegram_api_hash, telegram_phone_number)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        telegram_session = db.query(TelegramSession).filter(
            TelegramSession.user_id == user_id
        ).first()
        
        if not telegram_session:
            # Create new record
            telegram_session = TelegramSession(user_id=user_id)
            db.add(telegram_session)
        
        # Update fields
        if 'telegram_api_id' in kwargs:
            telegram_session.telegram_api_id = kwargs['telegram_api_id']
        if 'telegram_api_hash' in kwargs:
            telegram_session.telegram_api_hash = kwargs['telegram_api_hash']
        if 'telegram_phone_number' in kwargs:
            telegram_session.telegram_phone_number = kwargs['telegram_phone_number']
        
        db.commit()
        db.refresh(telegram_session)
        return True
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating Telegram config for user {user_id}: {e}")
        return False


def update_slack_config(db: Session, user_id: int, slack_user_token: str) -> bool:
    """
    Update Slack configuration for a user in database
    
    Returns:
        True if successful, False otherwise
    """
    try:
        slack_info = db.query(SlackInfo).filter(SlackInfo.user_id == user_id).first()
        
        if not slack_info:
            # Create new record
            slack_info = SlackInfo(user_id=user_id, slack_user_token=slack_user_token)
            db.add(slack_info)
        else:
            # Update existing
            slack_info.slack_user_token = slack_user_token
        
        db.commit()
        db.refresh(slack_info)
        return True
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating Slack config for user {user_id}: {e}")
        return False

