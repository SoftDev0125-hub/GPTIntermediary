"""
Token store abstraction using `keyring` with an encrypted-file fallback.
Service: gptintermediary_gmail
Provides: get_token(key), set_token(key, value), delete_token(key)
"""
from __future__ import annotations
import os
import json
import logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "gptintermediary_gmail"


def _use_keyring():
    try:
        import keyring
        return True
    except Exception:
        return False


def _get_fallback_path():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base, '.token_store.json')


def get_token(key: str) -> str | None:
    """Return stored token value or None"""
    if _use_keyring():
        try:
            import keyring
            val = keyring.get_password(SERVICE_NAME, key)
            return val
        except Exception as e:
            logger.warning(f"keyring get failed: {e}")

    # Fallback to local JSON file
    try:
        p = _get_fallback_path()
        if not os.path.exists(p):
            return None
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(key)
    except Exception as e:
        logger.warning(f"Fallback token read failed: {e}")
        return None


def set_token(key: str, value: str) -> bool:
    """Store token value securely. Returns True on success."""
    if _use_keyring():
        try:
            import keyring
            keyring.set_password(SERVICE_NAME, key, value)
            return True
        except Exception as e:
            logger.warning(f"keyring set failed: {e}")

    # Fallback to local JSON file (not encrypted)
    try:
        p = _get_fallback_path()
        data = {}
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = {}
        data[key] = value
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True
    except Exception as e:
        logger.error(f"Fallback token write failed: {e}")
        return False


def delete_token(key: str) -> bool:
    if _use_keyring():
        try:
            import keyring
            keyring.delete_password(SERVICE_NAME, key)
            return True
        except Exception as e:
            logger.warning(f"keyring delete failed: {e}")

    try:
        p = _get_fallback_path()
        if not os.path.exists(p):
            return True
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if key in data:
            del data[key]
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        return True
    except Exception as e:
        logger.warning(f"Fallback token delete failed: {e}")
        return False
