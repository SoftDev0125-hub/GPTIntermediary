"""
Google Custom Search JSON API — shared by chat_server, chat_server_simple, and main API.
Requires GOOGLE_CUSTOM_SEARCH_API_KEY and GOOGLE_CUSTOM_SEARCH_ENGINE_ID (cx).
"""
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)


def _read_env_key_from_dotenv(key_name: str) -> str:
    try:
        from pathlib import Path
        # services/google_cse.py -> parents[3] = project root (contains .env)
        base = Path(__file__).resolve().parents[3]
        env_path = base / '.env'
        if not env_path.exists():
            return ''
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' not in line or line.strip().startswith('#'):
                    continue
                k, v = line.split('=', 1)
                if k.strip() == key_name:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ''


def google_cse_credentials():
    key = os.getenv('GOOGLE_CUSTOM_SEARCH_API_KEY') or _read_env_key_from_dotenv('GOOGLE_CUSTOM_SEARCH_API_KEY')
    cx = os.getenv('GOOGLE_CUSTOM_SEARCH_ENGINE_ID') or _read_env_key_from_dotenv('GOOGLE_CUSTOM_SEARCH_ENGINE_ID')
    key = (key or '').strip()
    cx = (cx or '').strip()
    return key, cx


def is_google_cse_configured() -> bool:
    k, cx = google_cse_credentials()
    return bool(k and cx)


def google_custom_search(q: str, num: int = 8) -> list:
    """Return list of dicts: title, snippet, url, displayLink."""
    k, cx = google_cse_credentials()
    if not k or not cx:
        return []
    q = (q or '').strip()[:2000]
    if len(q) < 2:
        return []
    try:
        r = requests.get(
            'https://www.googleapis.com/customsearch/v1',
            params={'key': k, 'cx': cx, 'q': q, 'num': min(max(num, 1), 10)},
            timeout=12,
        )
        data = r.json()
        if r.status_code != 200:
            err = (data.get('error') or {}).get('message', r.text[:200])
            logger.warning('Google CSE HTTP %s: %s', r.status_code, err)
            return []
        items = data.get('items') or []
        out = []
        for it in items:
            out.append({
                'title': it.get('title'),
                'snippet': it.get('snippet'),
                'url': it.get('link'),
                'displayLink': it.get('displayLink'),
            })
        return out
    except Exception as e:
        logger.warning('Google CSE request failed: %s', e)
        return []


def format_cse_results_for_grounding(items: list, instruction_prefix: str, max_items: int = 8, max_snip: int = 280):
    """Returns (text, n_lines) for chat grounding."""
    lines = []
    for it in (items or [])[:max_items]:
        title = (it.get('title') or '').strip()[:200]
        snip = (it.get('snippet') or '').strip()
        if len(snip) > max_snip:
            snip = snip[:max_snip].rsplit(' ', 1)[0] + '...'
        url = (it.get('url') or '').strip()
        if title or snip:
            lines.append(f"- {title}\n  {snip}\n  {url}")
    if not lines:
        return '', 0
    text = (
        instruction_prefix
        + "\n\nGoogle Custom Search results (cite titles and URLs when answering):\n"
        + "\n".join(lines)
    )
    return text, len(lines)


def is_core_integration_message(message: str, analyzed: dict | None) -> bool:
    """
    True when the user is operating Gmail / WhatsApp / Telegram / Slack / app launch —
    skip external web grounding for these.
    """
    if analyzed and str(analyzed.get('confidence', '')).lower() == 'high':
        intent = (analyzed.get('intent') or '').lower()
        if intent in (
            'mark_all_read', 'clean_gmail', 'reply_to_email', 'send_email',
            'whatsapp_unread', 'whatsapp_send', 'whatsapp_reply',
            'get_unread_emails',
        ):
            return True
    low = (message or '').lower()
    if re.search(r'\b(slack|telegram)\b', low):
        return True
    if re.search(
        r'\b(launch|open|start)\s+(my\s+)?(the\s+)?(app|application|calculator|notepad|microsoft\s+word|word|excel)\b',
        low,
    ):
        return True
    if re.search(r'\b(whatsapp|gmail|inbox|unread\s+mail)\b', low) and re.search(
        r'\b(send|reply|check|show|get|read|open|mark|delete|clean|clear)\b',
        low,
    ):
        return True
    return False

