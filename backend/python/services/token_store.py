import json
import os
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except Exception:
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _HAS_CRYPTO = False

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config'))
TOKENS_PATH = os.path.join(BASE_DIR, 'tokens.json')
KEY_PATH = os.path.join(BASE_DIR, '.token_key')


def _ensure_dir():
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR, exist_ok=True)


def _get_key() -> Optional[bytes]:
    """Return a Fernet key from env or key file. If missing, generate and persist one."""
    # Allow explicit environment variable to specify key (useful for standalone builds)
    env_key = os.getenv('TOKEN_STORE_KEY')
    if env_key:
        try:
            return env_key.encode('utf-8')
        except Exception:
            return None

    _ensure_dir()
    if os.path.exists(KEY_PATH):
        try:
            with open(KEY_PATH, 'rb') as f:
                return f.read().strip()
        except Exception:
            return None

    # Generate a new key if cryptography available
    if _HAS_CRYPTO:
        try:
            k = Fernet.generate_key()
            with open(KEY_PATH, 'wb') as f:
                f.write(k)
            return k
        except Exception:
            return None
    return None


def _encrypt(data: bytes) -> bytes:
    key = _get_key()
    if not key or not _HAS_CRYPTO:
        return data
    f = Fernet(key)
    return f.encrypt(data)


def _decrypt(data: bytes) -> bytes:
    key = _get_key()
    if not key or not _HAS_CRYPTO:
        return data
    f = Fernet(key)
    try:
        return f.decrypt(data)
    except InvalidToken:
        # If decryption fails, return raw data to avoid breaking caller; caller must handle format
        return data


def load_tokens() -> dict:
    _ensure_dir()
    if not os.path.exists(TOKENS_PATH):
        return {}
    try:
        with open(TOKENS_PATH, 'rb') as f:
            raw = f.read()
        dec = _decrypt(raw)
        return json.loads(dec.decode('utf-8'))
    except Exception:
        return {}


def save_token(email: str, access_token: str, refresh_token: Optional[str] = None) -> None:
    if not email:
        return
    tokens = load_tokens() or {}
    tokens[email] = tokens.get(email, {})
    if access_token:
        tokens[email]['access_token'] = access_token
    if refresh_token:
        tokens[email]['refresh_token'] = refresh_token
    _ensure_dir()
    try:
        raw = json.dumps(tokens, indent=2).encode('utf-8')
        enc = _encrypt(raw)
        with open(TOKENS_PATH, 'wb') as f:
            f.write(enc)
    except Exception:
        # Best-effort persistence; do not raise to avoid breaking flows
        pass


def get_token_for_email(email: str) -> Optional[dict]:
    if not email:
        return None
    tokens = load_tokens()
    return tokens.get(email)
