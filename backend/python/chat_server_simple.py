"""
Chat Server - Hybrid mode with OpenAI fallback
Uses OpenAI for conversation + function calling when available
Falls back to keyword matching when OpenAI quota is exceeded
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import openai
import os
import json
import logging
from dotenv import load_dotenv
from datetime import datetime


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Database imports
try:
    from database import SessionLocal, init_db, engine
    from db_models import ChatWithGPT, Base
    DATABASE_AVAILABLE = True
    logger.info("[OK] Database modules loaded successfully")

    # Initialize database tables if they don't exist
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("[OK] Database tables checked/created")
    except Exception as e:
        logger.warning(f"[WARNING] Could not initialize database tables: {e}")
except ImportError as e:
    logger.warning(f"[WARNING] Database modules not available: {e}")
    logger.warning("[WARNING] Chat conversations will not be saved to database")
    DATABASE_AVAILABLE = False
    ChatWithGPT = None
    SessionLocal = None
    Base = None
    engine = None

# Load project root .env only (GPTIntermediary/.env)
from pathlib import Path
_load_env_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_load_env_root / '.env')

# Robust env loader: handle cases where .env has spaces around '=' or nonstandard formatting
def _read_env_key_from_dotenv(key_name):
    # First try os.environ
    val = os.getenv(key_name)
    if val:
        return val.strip()

    # Fallback: manually parse .env in repo root
    try:
        # Try repo root relative to this file (two levels up)
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        env_path = os.path.join(base, '.env')
        if not os.path.exists(env_path):
            return None
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' not in line or line.strip().startswith('#'):
                    continue
                k, v = line.split('=', 1)
                if k.strip() == key_name:
                    return v.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Failed to read .env fallback for {key_name}: {e}")
    return None

# OpenAI Configuration
# Read from .env robustly (fallback parsing handles spacing/formatting)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or _read_env_key_from_dotenv('OPENAI_API_KEY') or ''
openai.api_key = OPENAI_API_KEY
USE_OPENAI = bool(OPENAI_API_KEY) and OPENAI_API_KEY != 'your_openai_api_key_here'

BACKEND_URL = os.getenv('BACKEND_URL') or "http://localhost:8000"

# Robust env loader: handle cases where .env has spaces around '=' or nonstandard formatting
def _read_env_key_from_dotenv(key_name):
    # First try os.environ
    val = os.getenv(key_name)
    if val:
        return val.strip()

    # Fallback: manually parse .env in repo root
    try:
        # Try repo root relative to this file (two levels up)
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        env_path = os.path.join(base, '.env')
        if not os.path.exists(env_path):
            return None
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' not in line or line.strip().startswith('#'):
                    continue
                k, v = line.split('=', 1)
                if k.strip() == key_name:
                    return v.strip().strip('\"').strip("\'")
    except Exception as e:
        logger.warning(f"Failed to read .env fallback for {key_name}: {e}")
    return None

# NewsAPI configuration
NEWSAPI_KEY = _read_env_key_from_dotenv('NEWSAPI_KEY')
USE_NEWSAPI = bool(NEWSAPI_KEY)
if not NEWSAPI_KEY:
    logger.warning('NEWSAPI_KEY is not configured; news features will be disabled')

def fetch_latest_news(q=None, country='us', pageSize=5):
    """Fetch top headlines from NewsAPI and return a list of simplified articles."""
    if not NEWSAPI_KEY:
        return []
    try:
        # Try multiple strategies to get the most relevant and recent articles.
        articles = []

        # 1) If topic provided, prefer `everything` with qInTitle for specificity
        if q:
            params = {
                'apiKey': NEWSAPI_KEY,
                'qInTitle': q,
                'pageSize': min(pageSize, 20),
                'sortBy': 'publishedAt'
            }
            resp = requests.get('https://newsapi.org/v2/everything', params=params, timeout=10)
            data = resp.json()
            if data.get('status') == 'ok' and data.get('articles'):
                for a in data.get('articles', []):
                    articles.append({
                        'title': a.get('title'),
                        'source': (a.get('source') or {}).get('name'),
                        'url': a.get('url'),
                        'publishedAt': a.get('publishedAt'),
                        'description': a.get('description')
                    })

        # 2) If still empty and q provided, try `everything` without qInTitle (broader)
        if q and not articles:
            params = {
                'apiKey': NEWSAPI_KEY,
                'q': q,
                'pageSize': min(pageSize * 2, 50),
                'sortBy': 'publishedAt',
                'language': 'en'
            }
            resp = requests.get('https://newsapi.org/v2/everything', params=params, timeout=10)
            data = resp.json()
            if data.get('status') == 'ok' and data.get('articles'):
                for a in data.get('articles', []):
                    articles.append({
                        'title': a.get('title'),
                        'source': (a.get('source') or {}).get('name'),
                        'url': a.get('url'),
                        'publishedAt': a.get('publishedAt'),
                        'description': a.get('description')
                    })

        # 3) If no topic provided or still empty, try top-headlines (country) first
        if not q and not articles:
            params = {
                'apiKey': NEWSAPI_KEY,
                'country': country,
                'pageSize': min(pageSize, 20)
            }
            resp = requests.get('https://newsapi.org/v2/top-headlines', params=params, timeout=8)
            data = resp.json()
            if data.get('status') == 'ok' and data.get('articles'):
                for a in data.get('articles', []):
                    articles.append({
                        'title': a.get('title'),
                        'source': (a.get('source') or {}).get('name'),
                        'url': a.get('url'),
                        'publishedAt': a.get('publishedAt'),
                        'description': a.get('description')
                    })

        # 4) Final fallback: if still empty and we had a topic, try top-headlines without country
        if q and not articles:
            params = {
                'apiKey': NEWSAPI_KEY,
                'q': q,
                'pageSize': min(pageSize, 20)
            }
            resp = requests.get('https://newsapi.org/v2/top-headlines', params=params, timeout=8)
            data = resp.json()
            if data.get('status') == 'ok' and data.get('articles'):
                for a in data.get('articles', []):
                    articles.append({
                        'title': a.get('title'),
                        'source': (a.get('source') or {}).get('name'),
                        'url': a.get('url'),
                        'publishedAt': a.get('publishedAt'),
                        'description': a.get('description')
                    })

        logger.info(f"Fetched {len(articles)} news articles for query='{q}' country='{country}' via NewsAPI")
        return articles
    except Exception as e:
        logger.error(f"Failed to fetch news: {e}")
        return []

# User credentials (mock)
USER_CREDENTIALS = {
    "access_token": os.getenv('USER_ACCESS_TOKEN', 'mock_access_token'),
    "refresh_token": os.getenv('USER_REFRESH_TOKEN', 'mock_refresh_token'),
    "email": os.getenv('USER_EMAIL', 'user@gmail.com')
}

# OpenAI Function definitions
FUNCTIONS = [
    {
        "name": "launch_app",
        "description": "Launch an application on the computer",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name of the app to launch (e.g., notepad, chrome, calculator)"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "send_email",
        "description": "Send an email to a recipient",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body content"
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_unread_emails",
        "description": "Retrieve unread emails from Gmail inbox",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of emails to retrieve (default 10)",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an email",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID of the email to reply to"
                },
                "message": {
                    "type": "string",
                    "description": "Reply message content"
                }
            },
            "required": ["thread_id", "message"]
        }
    }
]

def parse_command(message):
    """Parse user message and determine action with enhanced NLP"""
    message_lower = message.lower()
    
    # CHECK EMAIL PATTERNS FIRST (before app launching)
    # Email sending patterns - enhanced to handle various formats (email or name as recipient)
    send_patterns = [
        # "send "message" to email@example.com" or "send "message" to John Doe"
        (r"send\s+['\"](.+?)['\"]\s+to\s+(.+?)(?:\?|\.|$)", True),
        # "email "message" to email@example.com" or name
        (r"email\s+['\"](.+?)['\"]\s+to\s+(.+?)(?:\?|\.|$)", True),
        # "send email to email@example.com "message""
        (r"send\s+email\s+to\s+([\w\.-]+@[\w\.-]+).*?['\"](.+?)['\"]", False),
        # "send to email@example.com: message" or "send to email "message""
        (r"send\s+to\s+([\w\.-]+@[\w\.-]+)[:\s]+['\"]?(.+?)['\"]?$", False),
        # Simple: message to email (without send keyword)
        (r"['\"](.+?)['\"]\s+to\s+([\w\.-]+@[\w\.-]+)\s*$", False),
    ]
    
    for item in send_patterns:
        pattern, allow_name = item[0], item[1] if len(item) > 1 else False
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                if '@' in groups[0]:
                    email_or_name = groups[0]
                    msg = groups[1] if len(groups) > 1 else "Message"
                else:
                    msg = groups[0]
                    email_or_name = groups[1].strip().strip('"\'.')
                if not email_or_name:
                    continue
                # If pattern doesn't allow name, require @ in recipient
                if not allow_name and '@' not in email_or_name:
                    continue
                logger.info(f"Email send detected: to={email_or_name}, msg={msg}")
                return {
                    'action': 'send_email',
                    'to': email_or_name,
                    'subject': msg,
                    'body': msg,
                    'needs_oauth': False
                }
    
    # Find email of a person: "find the email address of X", "find email of X from company Y", "what is X's email"
    find_email_patterns = [
        r"find\s+(?:the\s+)?email\s+(?:address\s+)?(?:of\s+)?(.+?)(?:\?|\.|$)",
        r"what\s+is\s+(.+?)'s\s+email",
        r"get\s+(?:the\s+)?email\s+(?:of\s+)?(.+?)(?:\?|\.|$)",
        r"look\s+up\s+(?:the\s+)?email\s+(?:for\s+)?(.+?)(?:\?|\.|$)",
    ]
    for pat in find_email_patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().strip('"\'.')
            if not raw or len(raw) <= 1:
                continue
            # Parse "Name from company X" / "Name at X" / "Name from X"
            name, company = raw, None
            for suffix_pat, group in [
                (r"^(.+?)\s+from\s+company\s+(.+)$", (0, 1)),   # "John from company Microsoft" -> name, company
                (r"^(.+?)\s+at\s+(.+)$", (0, 1)),                 # "John at Microsoft"
                (r"^(.+?)\s+from\s+(.+)$", (0, 1)),               # "John from Microsoft"
            ]:
                sm = re.match(suffix_pat, raw, re.IGNORECASE)
                if sm:
                    name = sm.group(group[0] + 1).strip()
                    company = sm.group(group[1] + 1).strip()
                    if not company:
                        company = None
                    break
            if name and len(name) > 1:
                out = {'action': 'find_email', 'name': name}
                if company:
                    out['company'] = company
                return out

    # Check for generic email patterns
    if 'unread' in message_lower and 'email' in message_lower:
        return {'action': 'get_emails'}

    # Reply patterns: accept polite prefixes like 'please reply to', 'reply to', 'reply', 'please reply'
    reply_patterns = [
        r"^(?:please\s+)?reply(?:\s+to)?\s+(.+)$",
        r"^reply\s+(.+)$",
        r"^please\s+reply\s+(.+)$"
    ]
    for rp in reply_patterns:
        m = re.search(rp, message, re.IGNORECASE)
        if m:
            sender = m.group(1).strip()
            return {'action': 'reply_email', 'sender': sender}
    
    if ('send email' in message_lower or 'email to' in message_lower) and '@' not in message_lower:
        return {'action': 'send_email', 'needs_oauth': True}
    
    # NOW CHECK APP LAUNCH PATTERNS
    launch_patterns = [
        # Direct launch commands
        (r'\b(?:open|launch|start|run|execute|begin|activate)\s+(?:the\s+)?(\w+(?:\s+\w+)?)', 'launch_app'),
        # "Can you..." patterns
        (r'(?:can\s+you|please|would\s+you|could\s+you)?\s*(?:open|launch|start|run)(?:\s+the)?\s+(\w+(?:\s+\w+)?)', 'launch_app'),
        # "[app] please" or just app name - BUT NOT IF CONTAINS EMAIL SYMBOLS
        (r'^(\w+(?:\s+\w+)?)\s*(?:please)?$', 'launch_app') if '@' not in message else None,
    ]
    
    for item in launch_patterns:
        if item is None:
            continue
        pattern, action = item
        match = re.search(pattern, message_lower)
        if match:
            app_name = match.group(1).strip()
            if action == 'launch_app':
                logger.info(f"App launch detected: {app_name}")
                return {'action': 'launch_app', 'app_name': app_name}
            break
    
    return {'action': 'chat', 'message': message}


def execute_action(action_data):
    """Execute the parsed action"""
    action = action_data.get('action')
    
    if action == 'launch_app':
        app_name = action_data.get('app_name')
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/app/launch",
                json={"app_name": app_name}
            )
            result = response.json()
            
            if response.status_code == 200 and result.get('success'):
                return {
                    'response': f"✅ {result['message']}",
                    'function_called': 'launch_app'
                }
            else:
                return {
                    'response': f"❌ Failed to launch {app_name}. Make sure the app name is correct.",
                    'error': True
                }
        except Exception as e:
            return {
                'response': f"❌ Error launching app: {str(e)}",
                'error': True
            }
    
    elif action == 'find_email':
        name = action_data.get('name', '').strip()
        company = action_data.get('company', '').strip() or None
        if not name:
            return {'response': 'Please specify a name to look up (e.g. "find the email address of John Doe" or "find the email of Jane from company Acme").', 'function_called': None}
        try:
            payload = {"name": name}
            if company:
                payload["company"] = company
            response = requests.post(
                f"{BACKEND_URL}/api/contacts/find-email",
                json=payload,
                timeout=15
            )
            data = response.json() if response.ok else {}
            if response.status_code == 200 and data.get('success'):
                source = data.get('source', '')
                email = data.get('email', '')
                display_name = data.get('name', name)
                if source == 'database':
                    msg = f"📧 **From your contacts** — **{display_name}**: {email}"
                else:
                    msg = f"📧 **Found via web search** (saved to your contacts) — **{display_name}**: {email}"
                return {'response': msg, 'function_called': 'find_email'}
            if response.status_code == 400:
                detail = data.get('detail', 'Email finder is not configured.')
                if not isinstance(detail, str):
                    detail = str(detail)
                return {
                    'response': "🔍 " + detail,
                    'function_called': None,
                    'error': True
                }
            if response.status_code == 404:
                detail = data.get('detail', f'No email found for "{name}".')
                if not isinstance(detail, str):
                    detail = str(detail)
                return {
                    'response': "🔍 " + detail + "\n\n_You can add contacts manually in Settings if you know the email._",
                    'function_called': None
                }
            return {
                'response': "🔍 " + (data.get('detail', 'Could not find email. Please try again.') if isinstance(data.get('detail'), str) else 'Could not find email.'),
                'function_called': None,
                'error': True
            }
        except Exception as e:
            return {
                'response': f"🔍 Error looking up email: {str(e)}. Is the backend running on {BACKEND_URL}?",
                'function_called': None,
                'error': True
            }

    elif action == 'get_emails':
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/email/unread",
                json={"user_credentials": USER_CREDENTIALS, "max_results": 10}
            )
            result = response.json()
            
            if response.status_code == 200 and result.get('success'):
                emails = result.get('emails', [])
                total_unread = result.get('total_unread', len(emails))

                # Analyze emails: top senders, urgency, short previews
                if not emails:
                    return {
                        'response': "📧 No unread emails found.",
                        'function_called': 'get_emails'
                    }

                from collections import Counter
                import re
                # Normalize sender name/email
                senders = [((e.get('from_name') or e.get('from_email') or '').strip()) for e in emails]
                sender_counts = Counter(senders)
                top = sender_counts.most_common(3)

                # Urgency detection
                urgency_keywords = ['urgent', 'asap', 'immediately', 'action required', 'deadline', 'due', 'important']
                flagged = []
                previews = []
                for e in emails[:10]:
                    subj = (e.get('subject') or '').strip()
                    body = (e.get('body') or '')
                    # strip html
                    snippet = re.sub(r'<[^>]+>', '', body or '')
                    snippet = snippet.replace('\n', ' ').strip()
                    preview = (snippet[:140] + '...') if len(snippet) > 140 else snippet
                    previews.append({'from': e.get('from_name') or e.get('from_email'), 'subject': subj, 'preview': preview})

                    low = (subj + ' ' + (snippet or '')).lower()
                    if any(k in low for k in urgency_keywords):
                        flagged.append({'from': e.get('from_name') or e.get('from_email'), 'subject': subj})

                # Build concise summary
                top_senders_str = ', '.join([f"{s[0]} ({s[1]})" for s in top if s[0]]) or 'Various'
                flagged_str = ''
                if flagged:
                    flagged_list = '; '.join([f"{f['from']}: {f['subject']}" for f in flagged[:5]])
                    flagged_str = f"\n⚠️ Urgent/Action-required: {len(flagged)} — {flagged_list}"

                preview_lines = []
                for p in previews[:5]:
                    preview_lines.append(f"• {p['from']} - {p['subject']}\n  {p['preview']}")

                summary = (
                    f"📧 You have {len(emails)} unread emails (total unread: {total_unread}).\n"
                    f"Top senders: {top_senders_str}.{flagged_str}\n\n"
                    f"Recent messages:\n" + "\n".join(preview_lines)
                )

                return {
                    'response': summary,
                    'function_called': 'get_emails'
                }
            else:
                return {
                    'response': f"❌ {result.get('error', 'Failed to fetch emails. OAuth required.')}",
                    'error': True
                }
        except Exception as e:
            return {
                'response': f"📧 Email features require Gmail OAuth authentication. Error: {str(e)}",
                'error': True
            }
    
    elif action == 'send_email':
        if action_data.get('needs_oauth') and not action_data.get('to'):
            return {
                'response': "📧 To send an email, use: send \"message\" to email@example.com or send \"message\" to Contact Name",
                'function_called': None
            }
        
        try:
            to_field = (action_data.get('to') or '').strip()
            if not to_field:
                return {'response': '📧 No recipient specified.', 'function_called': None, 'error': True}

            subject = action_data.get('subject', 'Message')
            body = action_data.get('body', action_data.get('subject', 'Message'))

            # Backend accepts either email or name; it will check DB then use Bing/People API if needed
            targets = [to_field]
            if not targets:
                return {
                    'response': '📧 No recipient specified.',
                    'function_called': None,
                    'error': True
                }

            successes = []
            failures = []
            for tgt in targets:
                try:
                    email_data = {
                        "user_credentials": USER_CREDENTIALS,
                        "to": tgt,
                        "subject": subject,
                        "body": body
                    }
                    response = requests.post(f"{BACKEND_URL}/api/email/send", json=email_data, timeout=10)
                    result = response.json() if response is not None else {}
                    # Handle resolver candidate response (409)
                    if response.status_code == 409:
                        detail = result.get('detail') if isinstance(result, dict) else None
                        try:
                            cand_payload = json.loads(detail) if isinstance(detail, str) else detail
                        except Exception:
                            cand_payload = None
                        return {
                            'response': 'I found possible addresses for that name. Please confirm before sending.',
                            'candidates': cand_payload.get('candidates') if isinstance(cand_payload, dict) else None,
                            'function_called': None,
                            'require_confirm': True
                        }
                    if response.status_code == 200 and result.get('success'):
                        successes.append(tgt)
                    else:
                        failures.append({"to": tgt, "error": result.get('error', 'unknown')})
                except Exception as send_err:
                    failures.append({"to": tgt, "error": str(send_err)})

            # Build summary message
            parts = []
            if successes:
                parts.append(f"✅ Sent to: {', '.join(successes)}")
            if failures:
                fail_msgs = ", ".join([f"{f['to']} ({f['error']})" for f in failures])
                parts.append(f"❌ Failed: {fail_msgs}")

            summary = " | ".join(parts) if parts else "No actions performed."
            return {
                'response': summary,
                'function_called': 'send_email'
            }
        except Exception as e:
            return {
                'response': f"❌ Error sending email: {str(e)}",
                'error': True
            }
    
    elif action == 'reply_email':
        sender = action_data.get('sender')
        if not sender:
            return {'response': 'Please specify who to reply to (e.g. "Reply to Alice").', 'error': True}
        try:
            # Build a Primary inbox query for this sender
            sender_part = sender
            if '@' in sender_part:
                q = f'in:inbox category:primary from:{sender_part}'
            else:
                safe = sender_part.replace('"', '').strip()
                q = f'in:inbox category:primary from:"{safe}"'

            # Request recent unread emails from this sender
            response = requests.post(
                f"{BACKEND_URL}/api/email/unread",
                json={"user_credentials": USER_CREDENTIALS, "limit": 20, "query": q},
                timeout=8
            )
            result = response.json()
            if response.status_code != 200 or not result.get('success'):
                return {'response': f"❌ Could not fetch messages from {sender}.", 'error': True}

            emails = result.get('emails', [])
            if not emails:
                return {'response': f'No unread messages found from {sender} in Primary inbox.', 'function_called': 'get_emails'}

            target = emails[0]
            # Draft a short reply using OpenAI if available, otherwise use polite default
            draft = None
            if USE_OPENAI:
                try:
                    sys_msg = {"role": "system", "content": "You are a concise assistant that drafts short professional email replies."}
                    user_msg = {"role": "user", "content": (
                        f"Draft a short (2-4 sentence) polite reply to this email.\n\nFrom: {target.get('from_name') or target.get('from_email')}\nSubject: {target.get('subject')}\nPreview: {(target.get('body') or target.get('snippet') or '')[:600]}\n\nReturn only the reply body text." )}
                    gen = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[sys_msg, user_msg],
                        max_tokens=300,
                        temperature=0.3,
                        timeout=6
                    )
                    draft = gen.choices[0].message.content if gen and hasattr(gen.choices[0].message, 'content') else None
                except Exception:
                    draft = None

            if not draft:
                draft = "Hello,\n\nThanks for your message. I'll follow up shortly.\n\nBest regards."

            # Send reply using backend reply endpoint (use sender_email to find thread)
            reply_payload = {
                "user_credentials": USER_CREDENTIALS,
                "sender_email": target.get('from_email') or target.get('from'),
                "body": draft
            }
            send_resp = requests.post(f"{BACKEND_URL}/api/email/reply", json=reply_payload, timeout=8)
            send_res = send_resp.json() if send_resp is not None else {}
            if send_resp.status_code == 200 and send_res.get('success'):
                return {'response': f"✅ Reply sent to {target.get('from_name') or target.get('from_email')}.", 'function_called': 'reply_to_email'}
            else:
                return {'response': f"❌ Failed to send reply: {send_res.get('error') or send_res.get('detail') or send_res}", 'error': True}
        except Exception as e:
            return {'response': f'Error replying to {sender}: {str(e)}', 'error': True}
    
    else:
        # Default chat response - provide helpful guidance
        return {
            'response': """Hello! I'm your AI assistant. I can help you with:

💬 **General Questions**
• Answer questions on any topic
• Explain concepts and ideas
• Help with problem-solving
• Write and debug code

🚀 **Computer Control**
• Open apps: "Open Chrome", "Launch Calculator"
• Available: notepad, calc, chrome, firefox, telegram, discord, sticky notes, task manager, etc.

📧 **Email Management**
• Send: send "message" to email@example.com
• Check unread emails
• Reply to emails

What would you like to know or do?""",
            'function_called': None
        }


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "running", "service": "ChatGPT Interface Server (No OpenAI)"})


@app.route('/get_user_credentials', methods=['GET'])
def get_user_credentials():
    """Return user credentials for email operations"""
    logger.info(f"[*] Returning user credentials")
    logger.info(f"    Access Token: {USER_CREDENTIALS.get('access_token', 'NONE')[:30]}...")
    logger.info(f"    Refresh Token: {USER_CREDENTIALS.get('refresh_token', 'NONE')[:30]}...")
    logger.info(f"    Email: {USER_CREDENTIALS.get('email', 'NONE')}")
    return jsonify({
        "access_token": USER_CREDENTIALS.get("access_token"),
        "refresh_token": USER_CREDENTIALS.get("refresh_token"),
        "email": USER_CREDENTIALS.get("email")
    })


@app.route('/news', methods=['GET'])
def news_endpoint():
    """Simple endpoint to return NewsAPI articles for a query. Useful for testing and verification.

    Query params:
    - q: optional search topic (string)
    - pageSize: optional number of articles (int)
    """
    q = request.args.get('q')
    try:
        pageSize = int(request.args.get('pageSize', 5))
    except Exception:
        pageSize = 5

    if not NEWSAPI_KEY:
        return jsonify({'success': False, 'error': 'NEWSAPI_KEY not configured', 'articles': []}), 400

    articles = fetch_latest_news(q=q, pageSize=pageSize)
    return jsonify({'success': True, 'count': len(articles), 'articles': articles})


@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages with OpenAI + fallback"""
    data = request.json
    user_message = data.get('message', '').strip()
    user_id = data.get('user_id')  # Get user_id from request
    
    # Validate and convert user_id
    if user_id:
        try:
            user_id = int(user_id)
            logger.info(f"[CHAT] Received message from user_id={user_id}, message='{user_message[:50]}...' (length={len(user_message)})")
        except (ValueError, TypeError):
            logger.warning(f"[CHAT] Invalid user_id format: {user_id}, type: {type(user_id)}")
            user_id = None
    else:
        logger.warning(f"[CHAT] No user_id provided in request. Data keys: {list(data.keys()) if data else 'None'}")
    
    if not user_message:
        return jsonify({
            'response': 'Please enter a message.',
            'error': True
        })
    
    # Try OpenAI first if available
    if USE_OPENAI:
        try:
            # DISABLED: Database history retrieval to prevent timeout
            # The database query was causing timeouts, so we skip it entirely
            # Each question is now answered independently without past context
            
            # Build messages for OpenAI
            # Simplified system prompt without history to prevent timeout
            system_content = """You are ChatGPT, a helpful AI assistant created by OpenAI. You can answer questions on any topic, provide explanations, help with problem-solving, write code, and have natural conversations.

Additionally, you have special capabilities to interact with the user's computer:
• Launch applications (notepad, calculator, chrome, telegram, discord, etc.)
• Send emails via Gmail
• Check unread emails
• Reply to emails

Answer each question independently and clearly. Focus on the current question without referencing past conversations.

When answering questions:
- Provide clear, accurate, and helpful responses
- Explain complex topics in an understandable way
- Format code with proper syntax
- Use examples when helpful
- Be conversational and friendly

When users ask you to send emails, use the send_email function with proper to/subject/body parameters.
For app launching, use the launch_app function with the app name.

You can discuss any topic freely - science, math, programming, history, creative writing, or anything else the user asks about."""
            
            messages = [
                {
                    "role": "system",
                    "content": system_content
                }
            ]
            
            # DISABLED: No history is used to prevent timeout
            # Each question is answered independently
            # Skip database history and frontend history entirely

           
            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # If this looks like a news/current-events query, fetch latest news and include as context
            try:
                is_news_query = False
                # Broader news/current detection: look for explicit news keywords OR present-tense 'who is the current' style questions
                if re.search(r"\b(news|headline|headlines|latest|recent|today|breaking|current events|updates|what(?:'s| is) happening|any updates)\b", user_message, re.IGNORECASE):
                    is_news_query = True

                # Detect present-tense 'who is the current X' or 'who is the president' questions
                if re.search(r"\bwho\s+is\b", user_message, re.IGNORECASE) and re.search(r"\b(current|today|now|president|prime minister|leader|king|queen|chancellor|pm|president of)\b", user_message, re.IGNORECASE):
                    is_news_query = True

                # Try to extract a topic for more relevant search (e.g., 'news about X' or 'who is the current X')
                topic = None
                m = re.search(r"news(?:\s+(?:about|on|for)\s+)(.+)$", user_message, re.IGNORECASE)
                if not m:
                    m = re.search(r"who\s+is\s+(?:the\s+)?(current\s+)?(.+)$", user_message, re.IGNORECASE)
                if m:
                    topic = (m.group(1) if m.lastindex >= 1 and m.group(1) else m.group(2) if m.lastindex >= 2 else None)
                    if topic:
                        topic = topic.strip().strip('?.!')

                news_articles = []
                if is_news_query and USE_NEWSAPI:
                    try:
                        news_articles = fetch_latest_news(q=topic, country='us', pageSize=5)
                    except Exception:
                        news_articles = []

                if news_articles:
                    # Build a compact news summary to include in the system context for the model
                    news_lines = []
                    for a in news_articles:
                        title = a.get('title') or ''
                        src = a.get('source') or ''
                        desc = a.get('description') or ''
                        url = a.get('url') or ''
                        news_lines.append(f"- {title} ({src})\n  {desc}\n  {url}")

                    news_snippet = "\n\nNewsAPI - Latest articles:\n" + "\n".join(news_lines)
                else:
                    news_snippet = None
            except Exception as e:
                logger.warning(f"News integration failed: {e}")
                news_snippet = None

            # Bing grounding: inject web search results into context (like ChatGPT.com with Bing)
            bing_grounding_snippet = None
            try:
                from services.contact_resolver import bing_web_search_grounding, email_finder_keys_status
                if email_finder_keys_status().get("bing_configured"):
                    # Use grounding for questions / factual queries (not for greetings or commands)
                    q = user_message.strip()
                    is_searchy = (
                        q.endswith("?") or
                        re.search(r"\b(what|who|when|where|why|how|which|current|latest|recent|today|is\s+\w+\s+\w+\?)\b", q, re.IGNORECASE)
                    )
                    if is_searchy and len(q) > 10:
                        results = bing_web_search_grounding(q, max_results=5)
                        if results:
                            lines = ["Web search results (use to answer with up-to-date information):"]
                            for i, r in enumerate(results, 1):
                                snip = (r.get("snippet") or "").strip()
                                url = (r.get("url") or "").strip()
                                if snip:
                                    lines.append(f"{i}. {snip}")
                                if url:
                                    lines.append(f"   Source: {url}")
                            bing_grounding_snippet = "\n".join(lines)
                            logger.info(f"[CHAT] Bing grounding: injected {len(results)} web snippets")
            except Exception as e:
                logger.debug(f"Bing grounding failed: {e}")
            
            total_context = len(messages)
            logger.info(f"[CHAT] Total messages in context: {total_context} (1 system + {total_context-1} conversation messages)")
            
            # Warn if context is getting large
            if total_context > 25:
                logger.warning(f"[CHAT] Large context size: {total_context} messages - may cause timeout")
            
            # Call OpenAI with function calling - use direct call with very short timeout
            # Only system + current user message to prevent timeout
            # Insert news and/or Bing grounding snippets after system message (like ChatGPT.com)
            minimal_messages = [messages[0]]
            if news_snippet:
                minimal_messages.append({"role": "system", "content": news_snippet})
            if bing_grounding_snippet:
                minimal_messages.append({"role": "system", "content": bing_grounding_snippet})
            minimal_messages.append({"role": "user", "content": user_message})
            
            logger.info(f"[CHAT] Calling OpenAI API with minimal context: {len(minimal_messages)} messages")
            
            # Direct call with very short timeout
            try:
                response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=minimal_messages,
                    functions=FUNCTIONS,
                    function_call="auto",
                    temperature=0.7,
                    max_tokens=1500,  # Reduced tokens for faster response
                    timeout=8  # Very short timeout - 8 seconds
                )
            except Exception as api_error:
                error_str = str(api_error).lower()
                logger.error(f"[CHAT] OpenAI API error: {error_str}")
                if 'timeout' in error_str or 'timed out' in error_str:
                    raise Exception("OpenAI API timeout")
                raise
            except Exception as api_error:
                error_str = str(api_error).lower()
                logger.error(f"[CHAT] OpenAI API error: {error_str}")
                # Fall through to keyword matching fallback
                raise
            
            message = response.choices[0].message
            function_called = None
            
            # Check if function was called
            if message.function_call:
                function_name = message.function_call.name
                function_args = json.loads(message.function_call.arguments)
                
                # Execute the function
                if function_name == 'launch_app':
                    app_name = function_args.get('app_name')
                    backend_response = requests.post(
                        f"{BACKEND_URL}/api/app/launch",
                        json={"app_name": app_name},
                        timeout=5  # 5 second timeout
                    )
                    function_result = backend_response.json()
                    function_called = function_name
                
                elif function_name == 'send_email':
                    email_data = {
                        "user_credentials": USER_CREDENTIALS,
                        "to": function_args.get('to'),
                        "subject": function_args.get('subject'),
                        "body": function_args.get('body')
                    }
                    backend_response = requests.post(
                        f"{BACKEND_URL}/api/email/send",
                        json=email_data,
                        timeout=5  # 5 second timeout
                    )
                    function_result = backend_response.json()
                    function_called = function_name
                
                elif function_name == 'get_unread_emails':
                    email_data = {
                        "user_credentials": USER_CREDENTIALS,
                        "limit": function_args.get('limit', 10)
                    }
                    backend_response = requests.post(
                        f"{BACKEND_URL}/api/email/unread",
                        json=email_data,
                        timeout=5  # 5 second timeout
                    )
                    function_result = backend_response.json()
                    function_called = function_name
                
                elif function_name == 'reply_to_email':
                    email_data = {
                        "user_credentials": USER_CREDENTIALS,
                        "thread_id": function_args.get('thread_id'),
                        "message": function_args.get('message')
                    }
                    backend_response = requests.post(
                        f"{BACKEND_URL}/api/email/reply",
                        json=email_data,
                        timeout=5  # 5 second timeout
                    )
                    function_result = backend_response.json()
                    function_called = function_name
                
                else:
                    function_result = {"error": "Unknown function"}
                    
                if function_result:
                    # Send function result back to OpenAI
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": function_name,
                            "arguments": json.dumps(function_args)
                        }
                    })
                    
                    messages.append({
                        "role": "function",
                        "name": function_name,
                        "content": json.dumps(function_result)
                    })
                    
            # Get final response from OpenAI
            # Use MINIMAL context: only system + user message + function call messages
            # Direct call with very short timeout
            minimal_messages = [
                messages[0],  # System message
                {"role": "user", "content": user_message},  # Original user message
                {"role": "assistant", "content": None, "function_call": {"name": function_name, "arguments": json.dumps(function_args)}},
                {"role": "function", "name": function_name, "content": json.dumps(function_result)}
            ]
            
            logger.info(f"[CHAT] Making second OpenAI call with minimal context: {len(minimal_messages)} messages")
            
            try:
                second_response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=minimal_messages,
                    temperature=0.7,
                    max_tokens=1500,  # Reduced tokens
                    timeout=8  # Very short timeout - 8 seconds
                )
                if not second_response or not second_response.choices or len(second_response.choices) == 0:
                    logger.error("[CHAT] Empty response from second OpenAI call")
                    final_message = "I apologize, but I couldn't generate a complete response. Please try again."
                else:
                    final_message = second_response.choices[0].message.content
                    logger.info(f"[CHAT] Second OpenAI call successful")
            except Exception as second_error:
                error_str = str(second_error).lower()
                logger.error(f"[CHAT] Error in second OpenAI call: {second_error}")
                if 'timeout' in error_str or 'timed out' in error_str:
                    final_message = f"I completed the action ({function_name}), but the response generation timed out. Please check if it worked."
                else:
                    final_message = f"I completed the action ({function_name}), but had trouble generating a response. Please check if it worked."

            # Ensure we have a final_message; fallback to original assistant message if necessary
            if 'final_message' not in locals() or not final_message:
                try:
                    final_message = message.content
                except Exception:
                    final_message = "No response generated"
            
            # Validate final_message
            if not final_message or not isinstance(final_message, str):
                logger.warning(f"[CHAT] Invalid final_message: type={type(final_message)}, value={str(final_message)[:100]}")
                final_message = str(final_message) if final_message else "No response generated"
            
            logger.info(f"[CHAT] GPT Response preview: '{final_message[:100]}...' (length={len(final_message)})")
            
            # Prepare response first - don't wait for database save
            response_data = {
                'response': final_message,
                'function_called': function_called,
                'mode': 'openai'
            }
            
            # Return response immediately
            logger.info(f"[CHAT] Returning response immediately (length={len(final_message)})")
            response = jsonify(response_data)
            
            # Save to database in background (non-blocking) to prevent timeout
            if user_id and DATABASE_AVAILABLE:
                import threading
                def save_in_background():
                    try:
                        logger.info(f"[CHAT] Saving chat to database in background: user_id={user_id}")
                        save_chat_to_db(user_id, user_message, final_message, 'gpt-3.5-turbo', function_called, 'openai')
                        logger.info(f"[CHAT] Database save completed")
                    except Exception as db_save_error:
                        logger.error(f"[CHAT] Database save failed (non-critical): {db_save_error}")
                
                # Start background thread (non-blocking)
                threading.Thread(target=save_in_background, daemon=True).start()
            elif not user_id:
                logger.warning("[CHAT] user_id not provided, skipping database save")
            elif not DATABASE_AVAILABLE:
                logger.warning("[CHAT] Database not available, skipping database save")
            
            return response
        
        except Exception as e:
            error_str = str(e)
            # If OpenAI fails, fall back to keyword matching
            if 'quota' in error_str or '429' in error_str or '404' in error_str:
                print(f"OpenAI error, falling back to keyword matching: {error_str}")
            else:
                print(f"OpenAI error: {error_str}")
    
    # Fallback to keyword matching
    try:
        # Parse the command
        action_data = parse_command(user_message)
        
        # Execute the action
        result = execute_action(action_data)
        result['mode'] = 'keyword'
        
        # Get the response
        keyword_response = result.get('response', '')
        if not keyword_response or not isinstance(keyword_response, str):
            logger.warning(f"[CHAT] Invalid keyword response: type={type(keyword_response)}, value={str(keyword_response)[:100]}")
            keyword_response = str(keyword_response) if keyword_response else "No response generated"
        
        logger.info(f"[CHAT] Keyword Response preview: '{keyword_response[:100]}...' (length={len(keyword_response)})")
        
        # Save to database if user_id is provided
        if user_id and DATABASE_AVAILABLE:
            logger.info(f"[CHAT] Attempting to save chat to database: user_id={user_id}, mode=keyword")
            save_chat_to_db(
                user_id, 
                user_message, 
                keyword_response, 
                None, 
                result.get('function_called'), 
                'keyword'
            )
        elif not user_id:
            logger.warning("[CHAT] user_id not provided, skipping database save")
        elif not DATABASE_AVAILABLE:
            logger.warning("[CHAT] Database not available, skipping database save")
        
        return jsonify(result)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        error_response = f'Sorry, I encountered an error: {str(e)}'
        
        # Save error to database if user_id is provided
        if user_id and DATABASE_AVAILABLE:
            logger.info(f"[CHAT] Attempting to save error to database: user_id={user_id}, mode=error")
            save_chat_to_db(user_id, user_message, error_response, None, None, 'error')
        elif not user_id:
            logger.warning("[CHAT] user_id not provided, skipping error database save")
        elif not DATABASE_AVAILABLE:
            logger.warning("[CHAT] Database not available, skipping error database save")
        
        return jsonify({
            'response': error_response,
            'error': str(e)
        }), 500



def save_chat_to_db(user_id, user_message, gpt_response, model=None, function_called=None, mode=None):
    """Save chat conversation to database
    Stores user message in 'questions' column and GPT response in 'answers' column
    """
    if not DATABASE_AVAILABLE or not ChatWithGPT:
        logger.warning(f"[DB] Cannot save: DATABASE_AVAILABLE={DATABASE_AVAILABLE}, ChatWithGPT={ChatWithGPT}")
        return
    
    # Validate user_id
    if not user_id:
        logger.warning("[DB] Cannot save: user_id is None or empty")
        return
    
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        logger.error(f"[DB] Invalid user_id: {user_id} (type: {type(user_id)})")
        return
    
    # Validate messages
    if not user_message or not isinstance(user_message, str):
        logger.warning(f"[DB] Cannot save: invalid user_message. Type: {type(user_message)}, Value: {str(user_message)[:100]}")
        return
    
    if not gpt_response or not isinstance(gpt_response, str):
        logger.warning(f"[DB] Cannot save: invalid gpt_response. Type: {type(gpt_response)}, Value: {str(gpt_response)[:100]}")
        return
    
    # Clean and prepare the messages
    user_message_clean = str(user_message).strip()
    gpt_response_clean = str(gpt_response).strip()
    
    if not user_message_clean or not gpt_response_clean:
        logger.warning(f"[DB] Cannot save: empty message after cleaning. user_message length: {len(user_message_clean)}, gpt_response length: {len(gpt_response_clean)}")
        return
    
    try:
        db = SessionLocal()
        try:
            # Use 'questions' and 'answers' columns as per database structure
            chat_record = ChatWithGPT(
                user_id=user_id,
                questions=user_message_clean[:10000],  # User's question stored in 'questions' column
                answers=gpt_response_clean[:10000]  # GPT's answer stored in 'answers' column
            )
            db.add(chat_record)
            db.commit()
            logger.info(f"[DB] Chat saved successfully: user_id={user_id}, id={chat_record.id}, mode={mode}")
            logger.info(f"[DB] Question preview: '{user_message_clean[:100]}...' (length={len(user_message_clean)})")
            logger.info(f"[DB] Answer preview: '{gpt_response_clean[:100]}...' (length={len(gpt_response_clean)})")
        except Exception as e:
            db.rollback()
            logger.error(f"[DB] Error saving chat to database: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[DB] Database connection error: {e}", exc_info=True)


if __name__ == '__main__':
    print("=" * 60)
    print("ChatGPT Interface Server Starting (Hybrid Mode)")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"OpenAI API Key: {'[OK] Configured - Full ChatGPT mode' if USE_OPENAI else '[X] Not configured - Keyword mode'}")
    print(f"Mode: {'OpenAI + Fallback' if USE_OPENAI else 'Keyword-based only'}")
    print("=" * 60)
    print("\nServer running on http://72.62.162.44:5000")
    print("Open /chat_interface.html in your browser to start")
    print("\nFeatures:")
    if USE_OPENAI:
        print("  [OK] Full ChatGPT conversational AI")
        print("  [OK] Natural language understanding")
        print("  [OK] App launching via AI")
        print("  [OK] Automatic fallback if quota exceeded")
    else:
        print("  - Keyword-based app launching")
        print("  - Add OpenAI API key for full ChatGPT features")
    print("\nMake sure the backend is running on port 8000!")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
