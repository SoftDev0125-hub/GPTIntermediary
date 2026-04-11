"""
Resolve Gmail OAuth tokens per user for multi-tenant (e.g. Hostinger) deployments.

When MULTI_TENANT_MODE is enabled:
- Per-user tokens come only from the database (gmail_info / gmail_secondary_info).
- Request body must not supply user OAuth tokens (ignored to prevent cross-user token injection).
- user_id is required for any Gmail operation (enforced by FastAPI dependency + chat server).

Shared .env may still hold OPENAI_API_KEY, DATABASE_URL, JWT_SECRET, and optional default
GOOGLE_CLIENT_* only if not stored per user — user-linked tokens never come from USER_ACCESS_TOKEN*.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class GmailResolutionError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(detail)


def is_multi_tenant_deployment() -> bool:
    v = (os.getenv("MULTI_TENANT_MODE") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _truthy_second(raw: Any) -> bool:
    if raw is True or raw == 1:
        return True
    if isinstance(raw, str) and raw.strip().lower() in ("true", "1", "yes"):
        return True
    return False


def resolve_gmail_credentials(
    db: Optional[Session],
    user_id: Optional[int],
    use_second_account: bool,
    request_credentials: Optional[Any],
) -> Dict[str, Optional[str]]:
    """
    Returns dict: access_token, refresh_token, google_client_id, google_client_secret, sender_email.

    Raises GmailResolutionError on failure.
    """
    mt = is_multi_tenant_deployment()
    use_second = _truthy_second(use_second_account)

    if mt and not user_id:
        raise GmailResolutionError(
            401,
            "Sign in is required. Each user must use their own linked Gmail accounts on this server.",
        )

    access_token = None
    refresh_token = None
    google_client_id = None
    google_client_secret = None
    sender_email = None

    if db is not None and user_id is not None:
        uid = int(user_id)
        if use_second:
            try:
                from config_helpers import get_gmail_secondary_config

                sec = get_gmail_secondary_config(db, uid)
                if sec:
                    access_token = (sec.get("user_access_token") or "").strip() or None
                    refresh_token = (sec.get("user_refresh_token") or "").strip() or None
                    google_client_id = (sec.get("google_client_id") or "").strip() or None
                    google_client_secret = (sec.get("google_client_secret") or "").strip() or None
                    sender_email = (sec.get("user_email") or "").strip() or None
            except Exception as e:
                logger.warning("Gmail secondary DB read failed: %s", e)
        else:
            try:
                from config_helpers import get_gmail_config
                from user_service_helpers import get_user_gmail_credentials

                gmail_config = get_gmail_config(db, uid)
                user_creds = get_user_gmail_credentials(db, uid)
                if gmail_config:
                    google_client_id = gmail_config.get("google_client_id")
                    google_client_secret = gmail_config.get("google_client_secret")
                    sender_email = gmail_config.get("user_email")
                if user_creds and user_creds.get("access_token"):
                    access_token = user_creds.get("access_token")
                    refresh_token = user_creds.get("refresh_token")
            except Exception as e:
                logger.warning("Gmail primary DB read failed: %s", e)

    # Second account (EMAIL2): do not apply request body tokens here — the UI only sends
    # primary credentials from /get_user_credentials; merging them with use_second would
    # skip USER_ACCESS_TOKEN_2 / USER_REFRESH_TOKEN_2 and break refresh (wrong client_id).
    if not mt and request_credentials is not None and not use_second:
        ra = getattr(request_credentials, "access_token", None) or ""
        rr = getattr(request_credentials, "refresh_token", None) or ""
        if ra.strip():
            access_token = ra.strip()
            refresh_token = (rr or "").strip() or None
            em = getattr(request_credentials, "email", None)
            if em and not sender_email:
                sender_email = str(em).strip() or None

    if not mt:
        if use_second:
            if not access_token:
                access_token = (os.getenv("USER_ACCESS_TOKEN_2") or "").strip() or None
            if not refresh_token:
                refresh_token = (os.getenv("USER_REFRESH_TOKEN_2") or "").strip() or None
            if not google_client_id:
                google_client_id = (os.getenv("GOOGLE_CLIENT_ID_2") or "").strip() or None
            if not google_client_secret:
                google_client_secret = (os.getenv("GOOGLE_CLIENT_SECRET_2") or "").strip() or None
            if not sender_email:
                sender_email = (os.getenv("USER_EMAIL_2") or "").strip() or None
        else:
            if not access_token:
                access_token = (os.getenv("USER_ACCESS_TOKEN") or "").strip() or None
            if not refresh_token:
                refresh_token = (os.getenv("USER_REFRESH_TOKEN") or "").strip() or None
            if not google_client_id:
                google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip() or None
            if not google_client_secret:
                google_client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip() or None
            if not sender_email:
                sender_email = (os.getenv("USER_EMAIL") or "").strip() or None

    if not access_token or not refresh_token:
        if use_second:
            raise GmailResolutionError(
                400,
                "Second Gmail is not linked for this user. Connect it in Settings (or disable MULTI_TENANT_MODE for shared .env testing).",
            )
        raise GmailResolutionError(
            400,
            "Gmail is not linked for this user. Sign in and connect Gmail in Settings (or disable MULTI_TENANT_MODE for shared .env testing).",
        )

    if use_second and (not google_client_id or not google_client_secret):
        raise GmailResolutionError(
            400,
            "Second Gmail needs Google OAuth client ID and secret stored for this user (Settings / admin).",
        )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "google_client_id": google_client_id,
        "google_client_secret": google_client_secret,
        "sender_email": sender_email,
    }


def resolve_gmail_to_chat_credential_dict(
    db: Optional[Session],
    user_id: Optional[int],
    use_second_account: bool,
) -> Optional[Dict[str, str]]:
    """For chat_server: returns {access_token, refresh_token, email} or None if unavailable."""
    try:
        r = resolve_gmail_credentials(db, user_id, use_second_account, None)
    except GmailResolutionError:
        return None
    return {
        "access_token": r["access_token"] or "",
        "refresh_token": r["refresh_token"] or "",
        "email": (r.get("sender_email") or "") or "",
    }
