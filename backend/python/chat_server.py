"""
Chat Server - Connects OpenAI API with your backend
This provides a ChatGPT-like experience with email and app control
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import openai
import re
import os
import requests
import json
import random
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys

def _get_project_root():
    """Project root: when frozen (PyInstaller exe), use exe directory; otherwise backend/python/../.."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(_get_project_root())
load_dotenv(_load_env_root / '.env')

# Robust env loader (fallback) to handle .env formatting variations
def _read_env_key_from_dotenv(key_name):
    val = os.getenv(key_name)
    if val:
        return val.strip()
    try:
        base = _get_project_root()
        env_path = os.path.join(base, '.env')
        if not os.path.exists(env_path):
            return ''
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' not in line or line.strip().startswith('#'):
                    continue
                k, v = line.split('=', 1)
                if k.strip() == key_name:
                    return v.strip().strip('"').strip("'")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to read .env fallback for {key_name}: {e}")
    return ''

# Read NewsAPI key
NEWSAPI_KEY = _read_env_key_from_dotenv('NEWSAPI_KEY')
if not NEWSAPI_KEY:
    logging.warning('NEWSAPI_KEY not configured; news features may be limited')

def fetch_latest_news(q=None, country='us', pageSize=10):
    """Fetch news using NewsAPI; use 'everything' for queries (newest first, last 7 days) and 'top-headlines' otherwise."""
    if not NEWSAPI_KEY:
        return []
    try:
        if q:
            from datetime import datetime, timedelta
            from_date = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
            params = {
                'apiKey': NEWSAPI_KEY,
                'q': q,
                'pageSize': min(pageSize, 20),
                'sortBy': 'publishedAt',
                'language': 'en',
                'from': from_date,
            }
            resp = requests.get('https://newsapi.org/v2/everything', params=params, timeout=10)
        else:
            params = {
                'apiKey': NEWSAPI_KEY,
                'country': country,
                'pageSize': min(pageSize, 20)
            }
            resp = requests.get('https://newsapi.org/v2/top-headlines', params=params, timeout=8)
        data = resp.json()
        if data.get('status') != 'ok':
            logger.warning(f"NewsAPI returned non-ok status: {data.get('message')}")
            return []
        articles = []
        for a in data.get('articles', []):
            articles.append({
                'title': a.get('title'),
                'source': (a.get('source') or {}).get('name'),
                'url': a.get('url'),
                'publishedAt': a.get('publishedAt'),
                'description': a.get('description')
            })
        logger.info(f"Fetched {len(articles)} articles for query='{q}'")
        return articles
    except Exception as e:
        logger.error(f"Failed to fetch news: {e}")
        return []

# Setup logging - use WARNING level to reduce logging overhead
logging.basicConfig(level=logging.WARNING)  # Changed from INFO to WARNING for faster performance
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Configure Flask for better request handling
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

# Configuration - read at startup; get_openai_client() re-reads from .env so Settings updates apply without restart
OPENAI_API_KEY = _read_env_key_from_dotenv('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY') or ''
BACKEND_URL = "http://localhost:8000"

# Initialize OpenAI - use a single client instance for better performance
# Reusing a client is faster than creating a new one for each request
from openai import OpenAI
_openai_client = None

def _current_openai_key():
    """Return current OpenAI API key (re-read from .env so Settings tab changes take effect)."""
    return (_read_env_key_from_dotenv('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY') or '').strip()

def get_openai_client():
    """Get or create OpenAI client instance. Re-reads key from .env so updated key in Settings is used."""
    global _openai_client, OPENAI_API_KEY
    current_key = _current_openai_key()
    if current_key != OPENAI_API_KEY:
        OPENAI_API_KEY = current_key
        _openai_client = None
    if _openai_client is None:
        _openai_client = OpenAI(
            api_key=OPENAI_API_KEY,
            timeout=(10.0, 90.0),  # Connect: 10s, Read: 90s (allow full response on slower PCs/networks)
            max_retries=0  # No retries - fail fast
        )
    return _openai_client


def analyze_emails_with_ai(emails, request_id=None, max_items=5):
    """Use OpenAI to analyze a small set of emails and produce a numbered summary.

    emails: list of dicts with keys 'from', 'subject', 'preview' (or similar)
    returns: string summary or None on failure
    """
    try:
        key = _current_openai_key()
        if not key or key == 'your_openai_api_key_here':
            return None

        client = get_openai_client()

        # Build a compact prompt with only necessary fields to save tokens
        # Also sanitize previews to remove HTML-like fragments and excessive whitespace
        parts = []
        import re as _re
        for i, e in enumerate(emails[:max_items], start=1):
            sender = (e.get('from') or e.get('from_name') or e.get('from_email') or 'Unknown').strip()
            subject = (e.get('subject') or '').replace('\n', ' ').strip()
            preview = (e.get('preview') or e.get('body') or '')
            # Remove HTML tags and long attribute-like fragments
            preview = _re.sub(r'<[^>]+>', ' ', preview)
            preview = _re.sub(r'\{[^}]{20,}\}', ' ', preview)
            # Remove common CSS properties (color, margin, padding, width, background-color, font, display, table rules)
            preview = _re.sub(r"\b(background-color|background|color|margin|padding|width|max-width|min-width|font|border|display|text-decoration|table|mso-[^:\s]+):[^;\n]+;?", ' ', preview, flags=_re.IGNORECASE)
            # Remove CSS selectors like .link:hover or .classname:active
            preview = _re.sub(r"\.[\w\-]+(?::[\w\-]+)?", ' ', preview)
            preview = _re.sub(r'\s+', ' ', preview).strip()
            # Truncate preview to conservative length
            if len(preview) > 240:
                preview = preview[:240].rsplit(' ', 1)[0] + '...'
            parts.append(f"Email {i} -- From: {sender} -- Subject: {subject} -- Preview: {preview}")

        user_content = (
            "You are a concise assistant that analyzes email previews and returns a strictly formatted plain-text summary.\n"
            "Output requirements (strict):\n"
            "1) The first line MUST be: 'A total of N emails have arrived.' where N is the number of emails analyzed.\n"
            "2) Follow with a numbered list starting at 1. Each item MUST follow this exact pattern (one line):\n"
            "   <index>. A new email has arrived from <sender> with the following content: <one-sentence summary>. Suggested actions: <action1>, <action2>.\n"
            "3) The one-sentence summary should be a single clear sentence (no newlines), 20-30 words maximum, capturing the main intent.\n"
            "4) Suggested actions should be 1-2 short verbs (Reply, Archive, Mark as important, Schedule, Ignore, Read later).\n"
            "5) Do NOT include any extra commentary, explanations, code, or metadata. Do NOT use bullets other than the numbered list.\n"
            "6) Remove any HTML, CSS, or long technical fragments from the preview when summarizing.\n\n"
            "Here are the emails to analyze:\n\n" + "\n".join(parts)
        )

        messages = [
            {"role": "system", "content": "You are a concise email assistant."},
            {"role": "user", "content": user_content}
        ]

        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=600,
            temperature=0.2,
            stream=False
        )

        if resp and hasattr(resp, 'choices') and resp.choices:
            return resp.choices[0].message.content
    except Exception as e:
        logger.warning(f"[CHAT-{request_id}] Email AI analysis failed: {e}")
    return None

# User credentials (mock - in production, this would come from user authentication)
# For now, we'll simulate that ChatGPT has the user's OAuth tokens
USER_CREDENTIALS = {
    "access_token": os.getenv('USER_ACCESS_TOKEN', 'mock_access_token'),
    "refresh_token": os.getenv('USER_REFRESH_TOKEN', 'mock_refresh_token'),
    "email": os.getenv('USER_EMAIL', 'user@gmail.com')
}

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

# Function definitions for OpenAI
FUNCTIONS = [
    {
        "name": "send_email",
        "description": "Send an email to a recipient. First account (EMAIL1) vs second (EMAIL2): use from_second_account=true ONLY when the user clearly says to send from the second account (e.g. 'using my second account', 'from the second account', 'from EMAIL2', 'with my second account', 'account 2'). Otherwise use the first account (from_second_account=false).",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject"
                },
                "body": {
                    "type": "string",
                    "description": "Email body content"
                },
                "from_second_account": {
                    "type": "boolean",
                    "description": "When true, send from the second Gmail account (EMAIL2). Use when the user says 'send from second account', 'using my second account', 'with my second account', or 'from EMAIL2'.",
                    "default": False
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_unread_emails",
        "description": "Get unread emails. The user has two accounts: EMAIL1 (first) and EMAIL2 (second). Distinguish from the user's words: account='first' when they say first account, account 1, 1st account, primary/main account, only first; account='second' when they say second account, account 2, 2nd account, only second; account='both' when they ask for new emails without specifying or say both accounts.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to retrieve per account (default 25)",
                    "default": 25
                },
                "account": {
                    "type": "string",
                    "description": "Which account(s): 'first' = EMAIL1 only (user said first account/account 1/primary); 'second' = EMAIL2 only (user said second account/account 2); 'both' = both (default). Infer from user wording.",
                    "enum": ["first", "second", "both"],
                    "default": "both"
                }
            }
        }
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an email. Always reply from the account that received that email. Each listed email is labeled (EMAIL1) or (EMAIL2): set from_second_account=true when replying to an email shown as (EMAIL2); false when (EMAIL1).",
        "parameters": {
            "type": "object",
            "properties": {
                "sender_email": {
                    "type": "string",
                    "description": "Email address of the sender to reply to"
                },
                "body": {
                    "type": "string",
                    "description": "Reply message content"
                },
                "from_second_account": {
                    "type": "boolean",
                    "description": "True when the email being replied to was in the second account (EMAIL2). Check the email list labels.",
                    "default": False
                }
            },
            "required": ["sender_email", "body"]
        }
    },
    {
        "name": "clean_gmail",
        "description": "Permanently delete all emails from a Gmail account. Use when the user asks to clean Gmail, delete all emails, or wipe inbox. use_second_account=true when they say second account/account 2/EMAIL2; false when they say first account/account 1/EMAIL1.",
        "parameters": {
            "type": "object",
            "properties": {
                "use_second_account": {
                    "type": "boolean",
                    "description": "True = second account (EMAIL2) only; False = first account (EMAIL1) only. Match the account the user asked to clean.",
                    "default": False
                }
            }
        }
    },
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
        "name": "find_email",
        "description": "Look up a person's email address by name. Checks the user's contacts first, then web search (Bing) if not found. Use when the user asks for someone's email (e.g. 'What is John's email?', 'Find the email address of Jane').",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full name or display name of the person (e.g. John Smith, Jane Doe)"
                },
                "company": {
                    "type": "string",
                    "description": "Optional company name to narrow search (e.g. Microsoft, Acme Corp)"
                }
            },
            "required": ["name"]
        }
    }
]


def call_backend_function(function_name, arguments, caller_credentials=None):
    """Call the backend API with function arguments"""
    
    # Add user credentials to email functions (first account only). When sending from second account, backend uses .env.
    if function_name in ['send_email', 'get_unread_emails', 'reply_to_email', 'clean_gmail']:
        use_second = arguments.get('use_second_gmail') is True or (
            isinstance(arguments.get('use_second_gmail'), str) and str(arguments.get('use_second_gmail')).strip().lower() == 'true'
        )
        if not use_second:
            creds = None
            if caller_credentials and isinstance(caller_credentials, dict) and caller_credentials.get('access_token'):
                creds = caller_credentials
            elif USER_CREDENTIALS and USER_CREDENTIALS.get('access_token') and 'mock' not in (USER_CREDENTIALS.get('access_token') or '').lower():
                creds = USER_CREDENTIALS
            if creds:
                arguments['user_credentials'] = creds
    
    # Map function names to endpoints
    endpoint_map = {
        'send_email': '/api/email/send',
        'get_unread_emails': '/api/email/unread',
        'reply_to_email': '/api/email/reply',
        'clean_gmail': '/api/email/delete-all',
        'launch_app': '/api/app/launch',
        'find_email': '/api/contacts/find-email'
    }
    
    endpoint = endpoint_map.get(function_name)
    if not endpoint:
        return {"error": f"Unknown function: {function_name}"}
    
    try:
        url = f"{BACKEND_URL}{endpoint}"
        print(f"Calling backend: {url}")
        print(f"Arguments: {json.dumps(arguments, indent=2)}")
        # Use longer timeout for email operations which may take longer
        timeout_sec = 5
        if function_name in ('get_unread_emails', 'reply_to_email', 'send_email'):
            timeout_sec = 25
        if function_name == 'clean_gmail':
            timeout_sec = 300  # Delete-all can take a long time for large mailboxes
        import time as _time
        t0 = _time.time()
        response = requests.post(url, json=arguments, timeout=timeout_sec)
        duration = _time.time() - t0
        print(f"Backend call duration: {duration:.2f}s")
        try:
            result = response.json()
        except Exception:
            result = {'raw_text': response.text}

        # Attach HTTP status for caller to react (e.g., 409 candidates)
        if isinstance(result, dict):
            result['_http_status'] = response.status_code
        else:
            result = {'data': result, '_http_status': response.status_code}

        print(f"Backend response (status={response.status_code}): {json.dumps(result, indent=2)}")
        return result
    
    except Exception as e:
        print(f"Backend error: {str(e)}")
        return {"error": str(e)}


@app.route('/')
def index():
    """Serve the login page"""
    try:
        project_root = _get_project_root()
        html_path = os.path.join(project_root, 'frontend', 'login.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading login page: {str(e)}", 500


@app.route('/chat_interface.html')
def chat_interface():
    """Serve the chat interface HTML (requires authentication)"""
    try:
        project_root = _get_project_root()
        html_path = os.path.join(project_root, 'frontend', 'chat_interface.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading chat interface: {str(e)}", 500


@app.route('/admin_panel.html')
def admin_panel():
    """Serve the admin panel HTML (requires admin authentication)"""
    try:
        project_root = _get_project_root()
        html_path = os.path.join(project_root, 'frontend', 'admin_panel.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading admin panel: {str(e)}", 500


@app.route('/styles.css')
def styles():
    """Serve the main stylesheet for the frontend pages"""
    try:
        project_root = _get_project_root()
        css_path = os.path.join(project_root, 'frontend', 'styles.css')
        return send_file(css_path)
    except Exception as e:
        return f"Error loading styles.css: {str(e)}", 500


# Proxy WhatsApp REST API so the frontend can use same-origin (no CORS) when served from chat server
WHATSAPP_NODE_URL = os.environ.get("WHATSAPP_NODE_URL", "http://127.0.0.1:3000")


@app.route('/api/whatsapp/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy_whatsapp(subpath):
    """Proxy WhatsApp API requests to the Node server so browser uses same origin (port 5000)."""
    url = f"{WHATSAPP_NODE_URL.rstrip('/')}/api/whatsapp/{subpath}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8')}"
    try:
        kwargs = {"timeout": 30}
        if request.method == 'GET':
            r = requests.get(url, **kwargs)
        elif request.method in ('POST', 'PUT'):
            # Forward JSON body so Node server receives it correctly
            body = request.get_data(as_text=True)
            try:
                payload = request.get_json(silent=True)
                if payload is not None:
                    kwargs["json"] = payload
                else:
                    kwargs["data"] = body
                    kwargs["headers"] = {"Content-Type": request.headers.get("Content-Type", "application/json")}
            except Exception:
                kwargs["data"] = body
                kwargs["headers"] = {"Content-Type": request.headers.get("Content-Type", "application/json")}
            if request.method == 'POST':
                r = requests.post(url, **kwargs)
            else:
                r = requests.put(url, **kwargs)
        elif request.method == 'DELETE':
            r = requests.delete(url, **kwargs)
        else:
            return jsonify({"error": "Method not allowed"}), 405
        ct = r.headers.get('Content-Type', 'application/json')
        return r.content, r.status_code, {'Content-Type': ct}
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "WhatsApp server not reachable. Make sure the app started the WhatsApp server (port 3000)."}), 503
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "WhatsApp server did not respond in time."}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 502


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "running", "service": "ChatGPT Interface Server"})


@app.route('/get_user_credentials', methods=['GET'])
def get_user_credentials():
    """Get user credentials for frontend"""
    return jsonify({
        "access_token": USER_CREDENTIALS.get("access_token"),
        "refresh_token": USER_CREDENTIALS.get("refresh_token"),
        "email": USER_CREDENTIALS.get("email")
    })


# Request counter for debugging
_request_counter = 0

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages and function calling"""
    global _request_counter
    import time
    request_start_time = time.time()
    _request_counter += 1
    request_id = f"req-{_request_counter}"  # Sequential request ID for tracking
    
    data = request.json
    user_message = data.get('message', '').strip()

    user_id = data.get('user_id')  # Get user_id from request
    
    logger.info(f"[CHAT-{request_id}] Request #{_request_counter} started at {request_start_time:.2f}, message='{user_message[:50]}...'")
    
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
    
    current_key = _current_openai_key()
    if not current_key or current_key == 'your_openai_api_key_here':
        return jsonify({
            'response': '[WARNING] OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.',
            'error': 'missing_api_key'
        })
    
    if not user_message:
        return jsonify({
            'response': 'Please enter a message.',
            'error': True
        })

    # Fast-path: "Clean my Gmail" / "Delete all emails" -> call delete-all backend directly
    try:
        clean_pattern = re.search(
            r"\b(clean\s+(my\s+)?gmail|delete\s+all\s+(my\s+)?emails?|clear\s+(my\s+)?(gmail|email)|wipe\s+(my\s+)?(gmail|inbox)|empty\s+(my\s+)?(gmail|inbox))\b",
            user_message,
            re.IGNORECASE
        )
        if clean_pattern:
            caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
            result = call_backend_function('clean_gmail', {}, caller_credentials=caller_creds)
            if isinstance(result, dict) and result.get('success'):
                count = result.get('data', {}).get('deleted_count', 0)
                msg = result.get('message', f'Permanently deleted {count} emails from your Gmail account.')
                return jsonify({'response': msg, 'function_called': 'clean_gmail'})
            err = result.get('error') or result.get('detail') or result.get('message') or str(result)
            return jsonify({'response': f"Could not clean Gmail: {err}", 'error': True, 'function_called': 'clean_gmail'}), 500
    except Exception as e_cmd:
        print(f"Direct clean Gmail handling failed: {e_cmd}")

    # Fast-path: "Reply to xxx" — fetch that person's email, analyze with AI, create and send reply
    try:
        reply_match = re.search(
            r"\b(?:please\s+)?reply\s+(?:to\s+)?(?:the\s+)?(?:email\s+from\s+)?(.+?)(?:\s*\.)?\s*$",
            user_message,
            re.IGNORECASE
        )
        if reply_match:
            target_spec = reply_match.group(1).strip().strip('"\',.')
            if target_spec:
                caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
                # Fetch unread from both accounts to find an email from this sender
                base_query = "in:inbox category:primary is:unread"
                res1 = call_backend_function("get_unread_emails", {"limit": 30, "query": base_query}, caller_credentials=caller_creds)
                res2 = call_backend_function("get_unread_emails", {"limit": 30, "query": base_query, "use_second_gmail": True}, caller_credentials=caller_creds)
                emails1 = [dict(e, account="EMAIL1") for e in (res1.get("emails") or []) if isinstance(e, dict)] if isinstance(res1, dict) and res1.get("success") else []
                emails2 = [dict(e, account="EMAIL2") for e in (res2.get("emails") or []) if isinstance(e, dict)] if isinstance(res2, dict) and res2.get("success") else []
                combined = emails1 + emails2
                target_spec_lower = target_spec.lower()
                def sender_matches(em):
                    from_email = (em.get("from_email") or em.get("from") or "").strip().lower()
                    from_name = (em.get("from_name") or "").strip().lower()
                    if not from_email and not from_name:
                        return False
                    if "@" in target_spec_lower:
                        return target_spec_lower in from_email or from_email == target_spec_lower
                    return target_spec_lower in from_name or target_spec_lower in from_email or (from_name and target_spec_lower in from_name)
                target_email = next((e for e in combined if sender_matches(e)), None)
                if not target_email:
                    return jsonify({
                        "response": f"No unread email found from \"{target_spec}\". Check the name or try listing your emails first.",
                        "function_called": None
                    })
                from_email = (target_email.get("from_email") or target_email.get("from") or "").strip()
                from_name = target_email.get("from_name") or ""
                subject = target_email.get("subject") or ""
                body_raw = target_email.get("body") or target_email.get("snippet") or ""
                if body_raw and len(body_raw) > 1200:
                    body_raw = body_raw[:1200] + "..."
                use_second = target_email.get("account") == "EMAIL2"
                # Draft reply using AI
                try:
                    client = get_openai_client()
                    sys_content = (
                        "You are a helpful assistant that drafts short, professional email replies. "
                        "Return only the reply body text (no subject, no quotes). Keep it concise (2–5 sentences). "
                        "Match the tone of the original message when appropriate."
                    )
                    user_content = (
                        f"Draft a reply to this email.\n\n"
                        f"From: {from_name or from_email}\nSubject: {subject}\n\n"
                        f"Content:\n{body_raw}\n\n"
                        "Return only the reply body text."
                    )
                    gen = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "system", "content": sys_content}, {"role": "user", "content": user_content}],
                        max_tokens=400,
                        temperature=0.4,
                        stream=False,
                    )
                    draft = (gen.choices[0].message.content or "").strip() if gen and gen.choices else ""
                except Exception as ai_err:
                    print(f"AI reply draft failed: {ai_err}")
                    draft = "Thank you for your message. I will get back to you soon.\n\nBest regards."
                if not draft:
                    draft = "Thank you for your message. I will get back to you soon.\n\nBest regards."
                reply_args = {"sender_email": from_email, "body": draft}
                if use_second:
                    reply_args["use_second_gmail"] = True
                result = call_backend_function("reply_to_email", reply_args, caller_credentials=caller_creds if not use_second else None)
                if isinstance(result, dict) and result.get("success"):
                    display_name = from_name or from_email
                    return jsonify({
                        "response": f"Reply sent to {display_name}.",
                        "function_called": "reply_to_email"
                    })
                err = result.get("error") or result.get("detail") or result.get("message") or str(result) if isinstance(result, dict) else str(result)
                return jsonify({"response": f"Could not send reply: {err}", "error": True, "function_called": "reply_to_email"}), 500
    except Exception as e_reply:
        print(f"Direct reply-to handling failed: {e_reply}")

    # Quick command: handle direct "Send <message> to <recipient>" by generating
    # an AI-written subject/body and sending via backend /api/email/send
    # Skip when user clearly means WhatsApp so the WhatsApp block can handle it
    try:
        want_whatsapp = bool(re.search(r"\b(whats\s*app|whatsapp|on\s+whatsapp|via\s+whatsapp)\b", user_message, re.IGNORECASE))
        m_cmd = None
        if not want_whatsapp:
            # Match "send X to Y" at start, or "Can you / Please / I want to send X to Y"
            m_cmd = re.match(r"^\s*send\s+(.+?)\s+to\s+(.+)$", user_message, re.IGNORECASE)
            if not m_cmd:
                m_cmd = re.match(r"^\s*(?:can you|please|could you|would you|i want to|i'd like to)\s+send\s+(.+?)\s+to\s+(.+)$", user_message, re.IGNORECASE)
        if m_cmd:
            original_text = m_cmd.group(1).strip()
            recipient = m_cmd.group(2).strip()

            # Detect second-account send and strip that phrase from recipient BEFORE composing,
            # so we create the email the same way as for the first account (clean recipient + same content).
            second_account_pattern = re.compile(
                r"\b(from\s+the\s+second\s+account|from\s+second\s+account|from\s+EMAIL2|from\s+account\s+2"
                r"|using\s+(?:my\s+)?(?:the\s+)?second\s+account|with\s+(?:my\s+)?(?:the\s+)?second\s+account"
                r"|(?:using|with)\s+my\s+second\s+account|my\s+second\s+account)\b",
                re.IGNORECASE
            )
            send_from_second = data.get('send_from_second_account', False) if isinstance(data, dict) else False
            if second_account_pattern.search(user_message):
                send_from_second = True
            recipient_stripped = re.sub(
                r"\s+(?:from\s+the\s+second\s+account|from\s+second\s+account|from\s+EMAIL2|from\s+account\s+2"
                r"|using\s+(?:my\s+)?(?:the\s+)?second\s+account|with\s+(?:my\s+)?(?:the\s+)?second\s+account"
                r"|(?:using|with)\s+my\s+second\s+account|my\s+second\s+account)\s*$",
                "",
                recipient,
                flags=re.IGNORECASE
            ).strip()
            recipient_for_compose = recipient_stripped or recipient

            # Prepare a prompt for the OpenAI client to generate a friendly subject and body
            # (same composition for first or second account: clean recipient + original_text)
            try:
                client = get_openai_client()
                ai_system = {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that composes short, friendly professional emails. "
                        "Return a JSON object only (no extra text) with two keys: 'subject' and 'body'. "
                        "Subject should be concise (under 78 characters). Body should include a short greeting, the message content, "
                        "and a brief closing/signature. Preserve the user's intent described in the prompt."
                    )
                }
                ai_user = {
                    "role": "user",
                    "content": (
                        f"Compose an email based on this brief description: {original_text}\n\n"
                        f"Recipient: {recipient_for_compose}\n\n"
                        "Return only valid JSON with 'subject' and 'body' fields."
                    )
                }

                gen_resp = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[ai_system, ai_user],
                    max_tokens=700,
                    temperature=0.7,
                    stream=False,
                )

                ai_msg = gen_resp.choices[0].message.content if gen_resp and hasattr(gen_resp.choices[0].message, 'content') else None
                subject = None
                body = None
                if ai_msg:
                    try:
                        # Parse JSON output from the model
                        parsed = json.loads(ai_msg)
                        subject = parsed.get('subject')
                        body = parsed.get('body')
                    except Exception:
                        # Fallback: try to extract simple Subject: and Body: blocks
                        try:
                            m_sub = re.search(r"\"subject\"\s*:\s*\"([\s\S]*?)\"", ai_msg)
                            m_body = re.search(r"\"body\"\s*:\s*\"([\s\S]*?)\"", ai_msg)
                            if m_sub:
                                subject = m_sub.group(1)
                            if m_body:
                                body = m_body.group(1)
                        except Exception:
                            subject = None
                            body = None

                # Final fallbacks
                if not subject:
                    subject = (original_text[:60] + '...') if len(original_text) > 60 else (original_text or 'Message from assistant')
                if not body:
                    body = f"Hello,\n\n{original_text}\n\nBest regards,\nYour assistant"

            except Exception as ai_err:
                print(f"AI generation failed: {ai_err}")
                # Use simple fallbacks if AI generation fails
                subject = (original_text[:60] + '...') if len(original_text) > 60 else (original_text or 'Message from assistant')
                body = f"Hello,\n\n{original_text}\n\nBest regards,\nYour assistant"

            args = {
                'to': recipient_for_compose,
                'subject': subject,
                'body': body
            }
            if send_from_second:
                args['use_second_gmail'] = True

            caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
            result = call_backend_function('send_email', args, caller_credentials=caller_creds)

            # Build friendly feedback for the user
            try:
                # Handle resolver candidate response (409) from backend
                if isinstance(result, dict) and result.get('_http_status') == 409:
                    # FastAPI encodes detail as a string; try to extract JSON candidates
                    detail = result.get('detail') or result.get('message') or result.get('data')
                    try:
                        cand_payload = json.loads(detail) if isinstance(detail, str) else detail
                    except Exception:
                        cand_payload = {'message': 'Resolver returned candidates', 'candidates': []}
                    candidates = cand_payload.get('candidates') if isinstance(cand_payload, dict) else None
                    # Return candidate list and instruction to confirm
                    return jsonify({
                        'response': "I couldn't find that email in your contacts. I found possible addresses. Please confirm before I send.",
                        'candidates': candidates,
                        'instruction': "If one of these is correct, resend the request with request.confirm=true",
                        'function_called': None
                    })

                if isinstance(result, dict):
                    results_list = result.get('data', {}).get('results') if result.get('data') else result.get('results')
                    if isinstance(results_list, list) and len(results_list) > 0:
                        parts = []
                        for r in results_list:
                            to_addr = r.get('to_normalized') or r.get('to') or r.get('matched') or str(r.get('to'))
                            if r.get('success'):
                                parts.append(f"✅ Sent to {to_addr}")
                            else:
                                err = r.get('error') or r.get('detail') or r.get('message') or 'unknown error'
                                parts.append(f"❌ Failed to send to {to_addr}: {err}")
                        summary = '; '.join(parts)
                        # Friendly assistant reply
                        resp_text = f"I've composed a friendly email and attempted to send it. Subject: '{subject}'. {summary}"
                    else:
                        # Generic success/error handling
                        if result.get('success'):
                            resp_text = result.get('message') or f"Email sent (subject: '{subject}')."
                        else:
                            resp_text = result.get('message') or result.get('error') or json.dumps(result)
                else:
                    resp_text = str(result)
            except Exception:
                resp_text = str(result)

            return jsonify({'response': resp_text, 'function_called': 'send_email'})
    except Exception as e_cmd:
        # Fall through to normal processing if direct command handling fails
        print(f"Direct send command handling failed: {e_cmd}")

    # Fast-path: WhatsApp commands in Chat tab (unread/news, per-contact unread, show history, send message, reply)
    try:
        wa_trigger = bool(re.search(r"\b(whats\s*app|whatsapp)\b", user_message, re.IGNORECASE))
        if wa_trigger:
            def _wa_call(method: str, subpath: str, payload: dict = None, timeout_sec: int = 45):
                base = WHATSAPP_NODE_URL.rstrip('/')
                url = f"{base}/api/whatsapp/{subpath.lstrip('/')}"
                try:
                    if method == 'GET':
                        r = requests.get(url, timeout=timeout_sec)
                    else:
                        r = requests.post(url, json=(payload or {}), timeout=timeout_sec)
                    return r.json() if r.content else {}
                except requests.exceptions.RequestException as e:
                    return {'success': False, 'error': str(e) or 'Request failed'}
                except (ValueError, TypeError) as e:
                    return {'success': False, 'error': 'Invalid response from WhatsApp server'}

            def _fmt_ts(ts):
                try:
                    if ts is None:
                        return ''
                    # WhatsApp timestamps are seconds since epoch
                    import datetime as _dt
                    return _dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    return str(ts or '')

            # 0) Reply to [contact] on WhatsApp — analyze last message, synthesize reply, send
            m_reply = re.search(
                r"\breply\s+to\s+(.+?)\s+on\s+(?:my\s+)?(?:whats\s*app|whatsapp)\s*(?:account)?\s*$",
                user_message, re.IGNORECASE
            )
            if not m_reply:
                m_reply = re.search(
                    r"\breply\s+on\s+(?:my\s+)?(?:whats\s*app|whatsapp)\s+to\s+(.+?)\s*$",
                    user_message, re.IGNORECASE
                )
            if m_reply:
                who = m_reply.group(1).strip().strip('"\'.')
                resolved = _wa_call('POST', 'resolve', {'query': who, 'include_groups': True, 'max_candidates': 5}, timeout_sec=60)
                if not isinstance(resolved, dict) or not resolved.get('success') or not resolved.get('match'):
                    err = (resolved or {}).get('error') or 'Could not resolve contact'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True})
                contact_id = resolved['match'].get('contact_id')
                contact_name = resolved['match'].get('name') or who
                msgs_res = _wa_call('POST', 'messages', {'contact_id': contact_id, 'limit': 30}, timeout_sec=90)
                if not isinstance(msgs_res, dict) or not msgs_res.get('success'):
                    err = (msgs_res or {}).get('error') or 'Failed to load messages'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True}), 500
                messages = msgs_res.get('messages') or []
                last_from_them = None
                for m in reversed(messages):
                    if not m.get('fromMe'):
                        last_from_them = m
                        break
                if not last_from_them:
                    return jsonify({'response': f"WhatsApp: No message from **{contact_name}** to reply to.", 'function_called': 'whatsapp_reply'})
                incoming_body = (last_from_them.get('body') or '').strip()
                if not incoming_body and last_from_them.get('hasMedia'):
                    incoming_body = f"[Media: {last_from_them.get('type') or 'attachment'}]"
                # Synthesize reply with OpenAI
                reply_text = None
                try:
                    client_ai = get_openai_client()
                    sys_content = (
                        "You are a helpful assistant that drafts short, natural WhatsApp replies. "
                        "Return only the reply text (no quotes, no 'Reply:' or attribution). Keep it concise (1-3 sentences). "
                        "Match the tone of the original message when appropriate."
                    )
                    user_content = f"Draft a reply to this WhatsApp message from {contact_name}.\n\nMessage: {incoming_body}\n\nReply (text only):"
                    gen = client_ai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "system", "content": sys_content}, {"role": "user", "content": user_content}],
                        max_tokens=300,
                        temperature=0.4,
                        stream=False,
                    )
                    if gen and gen.choices:
                        reply_text = (gen.choices[0].message.content or "").strip()
                except Exception as ai_err:
                    logger.warning(f"WhatsApp reply AI draft failed: {ai_err}")
                if not reply_text:
                    reply_text = "Thanks for your message. I'll get back to you soon."
                send_res = _wa_call('POST', 'send', {'contact_id': contact_id, 'text': reply_text}, timeout_sec=60)
                if isinstance(send_res, dict) and send_res.get('success'):
                    return jsonify({'response': f"✅ Replied to **{contact_name}** on WhatsApp: _{reply_text}_", 'function_called': 'whatsapp_reply'})
                err = (send_res or {}).get('error') or (send_res or {}).get('message') or 'Failed to send'
                return jsonify({'response': f"WhatsApp: Could not send reply to {contact_name}: {err}", 'error': True, 'function_called': 'whatsapp_reply'}), 500

            # 1) Send message — match multiple phrasings (we're already in wa_trigger)
            recipient = None
            text = None
            # "send message to John: Hello" or "send message to John - Hello"
            m_send_a = re.search(
                r"\bsend\s+(?:a\s+)?(?:whats\s*app\s+)?message\s+to\s+(.+?)[\:\-]\s*(.+)$",
                user_message, re.IGNORECASE
            )
            if m_send_a:
                recipient = str(m_send_a.group(1)).strip().strip('"\'.')
                text = str(m_send_a.group(2)).strip()
            if not (recipient and text):
                # "send Hello to John on whatsapp" or "send Hello to John"
                m_send_b = re.search(
                    r"\bsend\s+(.+?)\s+to\s+(.+?)\s*$",
                    user_message, re.IGNORECASE | re.DOTALL
                )
                if m_send_b:
                    text = str(m_send_b.group(1)).strip().strip('"\'.')
                    recipient = str(m_send_b.group(2)).strip().strip('"\'.')
                    # Remove trailing " on/whatsapp" / " via whatsapp" from recipient
                    recipient = re.sub(r"\s+(?:on|via)\s+(?:my\s+)?(?:whats\s*app|whatsapp)\s*$", "", recipient, flags=re.IGNORECASE).strip()
            if not (recipient and text):
                # "on whatsapp send Hello to John" or "via whatsapp send Hello to John"
                m_send_c = re.search(
                    r"(?:on\s+|via\s+)(?:my\s+)?(?:whats\s*app|whatsapp)\s+send\s+(.+?)\s+to\s+(.+?)\s*$",
                    user_message, re.IGNORECASE | re.DOTALL
                )
                if m_send_c:
                    text = str(m_send_c.group(1)).strip().strip('"\'.')
                    recipient = str(m_send_c.group(2)).strip().strip('"\'.')
                    recipient = re.sub(r"\s+(?:on|via)\s+(?:my\s+)?(?:whats\s*app|whatsapp)\s*$", "", recipient, flags=re.IGNORECASE).strip()

            if recipient and text:
                resolved = _wa_call('POST', 'resolve', {'query': recipient, 'include_groups': True, 'max_candidates': 5}, timeout_sec=60)
                if not isinstance(resolved, dict) or not resolved.get('success') or not resolved.get('match'):
                    err = (resolved or {}).get('error') or 'Could not resolve contact'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True})

                contact_id = (resolved.get('match') or {}).get('contact_id')
                contact_name = (resolved.get('match') or {}).get('name') or recipient
                if not contact_id:
                    return jsonify({'response': f"WhatsApp: Could not resolve contact for '{recipient}'.", 'error': True})

                send_res = _wa_call('POST', 'send', {'contact_id': contact_id, 'text': text}, timeout_sec=60)
                if isinstance(send_res, dict) and send_res.get('success'):
                    return jsonify({'response': f"✅ Sent WhatsApp message to **{contact_name}**.", 'function_called': 'whatsapp_send'})
                err = (send_res or {}).get('error') or (send_res or {}).get('message') or 'Failed to send'
                return jsonify({'response': f"❌ Could not send WhatsApp message to {contact_name}: {err}", 'error': True, 'function_called': 'whatsapp_send'}), 500

            # 2) Show conversation/history with a contact: up to 20 messages
            m_hist = re.search(
                r"\b(?:show|display|open|get)\b.*\b(?:conversation|chat|messages|communications)\b.*\bwith\s+(.+?)(?:\s+on\s+(?:whats\s*app|whatsapp))?\b",
                user_message, re.IGNORECASE
            )
            if m_hist:
                who = m_hist.group(1).strip().strip('"\'.')
                resolved = _wa_call('POST', 'resolve', {'query': who, 'include_groups': True, 'max_candidates': 5}, timeout_sec=60)
                if not isinstance(resolved, dict) or not resolved.get('success') or not resolved.get('match'):
                    err = (resolved or {}).get('error') or 'Could not resolve contact'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True})

                contact_id = resolved['match'].get('contact_id')
                contact_name = resolved['match'].get('name') or who
                msgs = _wa_call('POST', 'messages', {'contact_id': contact_id, 'limit': 20}, timeout_sec=90)
                if not isinstance(msgs, dict) or not msgs.get('success'):
                    err = (msgs or {}).get('error') or 'Failed to load messages'
                    return jsonify({'response': f"WhatsApp: couldn't load messages for {contact_name}: {err}", 'error': True}), 500

                lines = [f"WhatsApp conversation with **{contact_name}** (showing up to 20 messages):"]
                for m in (msgs.get('messages') or [])[-20:]:
                    direction = "Me" if m.get('fromMe') else (contact_name or "Them")
                    body = (m.get('body') or '').strip()
                    if not body and m.get('hasMedia'):
                        body = f"[Media: {m.get('type') or 'attachment'}]"
                    ts = _fmt_ts(m.get('timestamp'))
                    prefix = f"- [{ts}] **{direction}**:" if ts else f"- **{direction}**:"
                    lines.append(f"{prefix} {body}")
                return jsonify({'response': "\n".join(lines), 'function_called': 'whatsapp_history'})

            # 3) New messages from a specific contact
            m_from = re.search(
                r"\b(?:any\s+)?new\s+(?:messages?|news)\s+from\s+(.+?)\s+on\s+(?:whats\s*app|whatsapp)\b",
                user_message, re.IGNORECASE
            )
            if not m_from:
                m_from = re.search(r"\bnew\s+(?:messages?|news)\s+from\s+(.+?)\s*(?:on\s+)?(?:whats\s*app|whatsapp)\b", user_message, re.IGNORECASE)

            if m_from:
                who = m_from.group(1).strip().strip('"\'.')
                chk = _wa_call('POST', 'unread/last', {'query': who}, timeout_sec=60)
                if not isinstance(chk, dict) or not chk.get('success'):
                    err = (chk or {}).get('error') or 'Failed to check unread'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True}), 500
                contact = (chk.get('contact') or {})
                contact_name = contact.get('name') or who
                if not chk.get('has_new'):
                    return jsonify({'response': f"WhatsApp: **no new messages** from **{contact_name}**.", 'function_called': 'whatsapp_unread_from'})
                msg = chk.get('message') or {}
                ts = _fmt_ts(msg.get('timestamp'))
                body = (msg.get('body') or '').strip()
                if not body and msg.get('has_media'):
                    body = f"[Media: {msg.get('type') or 'attachment'}]"
                header = f"WhatsApp: new message from **{contact_name}**"
                if ts:
                    header += f" at {ts}"
                return jsonify({'response': f"{header}\n\n{body}", 'function_called': 'whatsapp_unread_from'})

            # 4) New messages across all contacts
            m_any = re.search(r"\b(any|are there|check|show|list|get)\b.*\b(new|unread)\b.*\b(messages?|news)\b", user_message, re.IGNORECASE) \
                or re.search(r"\b(new|unread)\b.*\b(messages?|news)\b", user_message, re.IGNORECASE)
            if m_any:
                data_unread = _wa_call('GET', 'unread/recent', None, timeout_sec=90)
                if not isinstance(data_unread, dict) or not data_unread.get('success'):
                    err = (data_unread or {}).get('error') or 'Failed to fetch unread'
                    return jsonify({'response': f"WhatsApp: {err}.", 'error': True}), 500
                items = data_unread.get('messages') or []
                if not items:
                    return jsonify({'response': "WhatsApp: **no new messages**.", 'function_called': 'whatsapp_unread_all'})
                lines = [f"WhatsApp: **{len(items)}** contact(s) have unread messages (showing latest unread per contact):"]
                for idx, it in enumerate(items, start=1):
                    name = it.get('name') or it.get('contact_id') or 'Unknown'
                    ts = _fmt_ts(it.get('last_message_time'))
                    body = (it.get('last_message') or '').strip()
                    if not body and it.get('last_message_has_media'):
                        body = f"[Media: {it.get('last_message_type') or 'attachment'}]"
                    unread_count = it.get('unread_count') or 0
                    ts_part = f" [{ts}]" if ts else ""
                    lines.append(f"{idx}. **{name}**{ts_part} (unread: {unread_count})\n   {body}")
                return jsonify({'response': "\n".join(lines), 'function_called': 'whatsapp_unread_all'})
    except Exception as e_wa:
        logger.exception(f"Fast-path WhatsApp handling failed: {e_wa}")
    
    # Fast-path: if user asks about new emails, query Gmail (one or both accounts)
    try:
        email_trigger = (
            re.search(r"\b(any\s+new\s+emails?|new\s+emails?|(are\s+there|do\s+I\s+have)\s+(any\s+)?(new\s+)?emails?)\b", user_message, re.IGNORECASE)
            or re.search(r"\b(check|show|list|get|fetch|read|display)\s+(my\s+)?(unread\s+)?(primary\s+)?(emails?|inbox|mail)\b", user_message, re.IGNORECASE)
            or re.search(r"\b(my\s+)?unread\s+emails?\b", user_message, re.IGNORECASE)
            or re.search(r"\b(what(?:'s| is)\s+)?(in\s+)?my\s+(email|inbox)\b", user_message, re.IGNORECASE)
            or re.search(r"\b(emails?|mail|messages?)\b.*\bfrom\b", user_message, re.IGNORECASE)
        )
        if email_trigger:
            caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
            # Which account(s): first only, second only, or both (EMAIL1 first then EMAIL2).
            # Use broad patterns so we reliably distinguish "first account" vs "second account" in user instructions.
            first_account_pattern = re.compile(
                r"\b("
                r"first\s+account|(?:my|the)\s+first\s+account|account\s+1|1st\s+account|"
                r"email\s*1|EMAIL1|in\s+(?:the\s+)?first\s+account|account\s+one|"
                r"only\s+first|first\s+only|first\s+Gmail|Gmail\s*1|"
                r"primary\s+account|main\s+account|first\s+inbox|inbox\s+1"
                r")\b",
                re.IGNORECASE
            )
            second_account_pattern = re.compile(
                r"\b("
                r"second\s+account|(?:my|the)\s+second\s+account|account\s+2|2nd\s+account|"
                r"email\s*2|EMAIL2|in\s+(?:the\s+)?second\s+account|account\s+two|"
                r"only\s+second|second\s+only|second\s+Gmail|Gmail\s*2|"
                r"second\s+inbox|inbox\s+2"
                r")\b",
                re.IGNORECASE
            )
            want_first_only = bool(first_account_pattern.search(user_message))
            want_second_only = bool(second_account_pattern.search(user_message))
            if want_first_only and want_second_only:
                want_first_only, want_second_only = False, False
            if not want_first_only and not want_second_only:
                want_both = True
            else:
                want_both = False

            sender_match = None
            try:
                m = re.search(r"\bfrom\s+([\"']?)([^\"'\?]+?)\1(?=\s|$|\?)", user_message, re.IGNORECASE)
                if not m:
                    m = re.search(r"(?:emails?|mail|messages?)\s+(?:from)\s+([^\?]+)", user_message, re.IGNORECASE)
                if m:
                    sender_match = m.groups()[-1].strip()
            except Exception:
                sender_match = None

            base_query = 'in:inbox category:primary is:unread'
            if sender_match:
                sender_term = sender_match
                if '@' in sender_term:
                    sender_part = f'from:{sender_term}'
                else:
                    safe_name = sender_term.replace('"', '').strip()
                    sender_part = f'from:"{safe_name}"'
                query = f"{base_query} {sender_part}"
            else:
                query = base_query

            email_page_token = data.get('email_page_token') if isinstance(data, dict) else None
            email_page_token_2 = data.get('email_page_token_2') if isinstance(data, dict) else None
            want_more = bool(re.search(
                r"\b(more|next\s*(50\s*)?emails?|show\s+more|load\s+more|another\s+50|next\s+50)\b",
                user_message, re.IGNORECASE
            ))
            # Single-account view: show 50; both accounts: 25 per account (50 total)
            limit_per = 50 if (want_second_only or want_first_only) else 25

            def fetch_one(use_second, page_tok):
                a = {'limit': limit_per, 'query': query}
                if page_tok:
                    a['page_token'] = page_tok
                if use_second:
                    a['use_second_gmail'] = True
                return call_backend_function('get_unread_emails', a, caller_credentials=caller_creds)

            if want_second_only:
                result1 = None
                result2 = fetch_one(True, email_page_token_2 if want_more else None)
                if not isinstance(result2, dict) or not result2.get('success'):
                    result = result2
                    emails = []
                    total_unread = 0
                    next_page_token = None
                    next_page_token_2 = None
                    account_label = "EMAIL2"
                else:
                    emails = [dict(e, account='EMAIL2') for e in (result2.get('emails') or []) if isinstance(e, dict)]
                    total_unread = result2.get('total_unread', len(emails))
                    next_page_token = None
                    next_page_token_2 = result2.get('next_page_token')
                    result = result2
                    account_label = "EMAIL2"
            elif want_first_only:
                result1 = fetch_one(False, email_page_token if want_more else None)
                result2 = None
                if not isinstance(result1, dict) or not result1.get('success'):
                    result = result1
                    emails = []
                    total_unread = 0
                    next_page_token = None
                    next_page_token_2 = None
                    account_label = "EMAIL1"
                else:
                    emails = [dict(e, account='EMAIL1') for e in (result1.get('emails') or []) if isinstance(e, dict)]
                    total_unread = result1.get('total_unread', len(emails))
                    next_page_token = result1.get('next_page_token')
                    next_page_token_2 = None
                    result = result1
                    account_label = "EMAIL1"
            else:
                result1 = fetch_one(False, email_page_token if want_more else None)
                result2 = fetch_one(True, email_page_token_2 if want_more else None)
                if not isinstance(result1, dict) or not result1.get('success'):
                    result = result1
                    emails = []
                    total_unread = 0
                    next_page_token = None
                    next_page_token_2 = None
                    account_label = "EMAIL1 + EMAIL2"
                else:
                    emails1 = [dict(e, account='EMAIL1') for e in (result1.get('emails') or []) if isinstance(e, dict)]
                    emails2 = [dict(e, account='EMAIL2') for e in (result2.get('emails') or []) if isinstance(e, dict)] if isinstance(result2, dict) and result2.get('success') else []
                    emails = emails1 + emails2
                    total_unread = result1.get('total_unread', len(emails1)) + (result2.get('total_unread', len(emails2)) if isinstance(result2, dict) and result2.get('success') else 0)
                    next_page_token = result1.get('next_page_token')
                    next_page_token_2 = result2.get('next_page_token') if isinstance(result2, dict) and result2.get('success') else None
                    result = result1
                account_label = "EMAIL1 + EMAIL2"

            if want_second_only and result and not result.get('success'):
                if result.get('_http_status') == 401 or result.get('error') == 'auth_error':
                    return jsonify({'response': 'Email access requires authentication. Please connect your Gmail account.', 'error': 'auth_error'}), 401
                if result.get('_http_status') == 429 or result.get('error') == 'insufficient_quota':
                    return jsonify({'response': 'Email service is currently rate limited. Please try again later.', 'error': 'rate_limit'}), 429
                err = result.get('detail') or result.get('message') or result.get('error') or str(result)
                return jsonify({'response': f'📧 Failed to fetch emails: {err}', 'error': err}), 500
            if want_first_only and result1 and not result1.get('success'):
                if result1.get('_http_status') == 401 or result1.get('error') == 'auth_error':
                    return jsonify({'response': 'Email access requires authentication. Please connect your Gmail account.', 'error': 'auth_error'}), 401
                if result1.get('_http_status') == 429 or result1.get('error') == 'insufficient_quota':
                    return jsonify({'response': 'Email service is currently rate limited. Please try again later.', 'error': 'rate_limit'}), 429
                err = result1.get('detail') or result1.get('message') or result1.get('error') or str(result1)
                return jsonify({'response': f'📧 Failed to fetch emails: {err}', 'error': err}), 500
            if want_both and result1 and not result1.get('success'):
                if result1.get('_http_status') == 401 or result1.get('error') == 'auth_error':
                    return jsonify({'response': 'Email access requires authentication. Please connect your Gmail account.', 'error': 'auth_error'}), 401
                if result1.get('_http_status') == 429 or result1.get('error') == 'insufficient_quota':
                    return jsonify({'response': 'Email service is currently rate limited. Please try again later.', 'error': 'rate_limit'}), 429
                err = result1.get('detail') or result1.get('message') or result1.get('error') or str(result1)
                return jsonify({'response': f'📧 Failed to fetch emails: {err}', 'error': err}), 500

            # Analyze emails: top senders, urgency, previews
            from collections import Counter
            import html
            urgency_keywords = ['urgent', 'asap', 'immediately', 'action required', 'deadline', 'due', 'important']

            if not emails:
                return jsonify({
                    'response': f"📧 No new emails in {account_label}. (total unread: {total_unread})",
                    'function_called': 'get_unread_emails',
                    'next_page_token': next_page_token,
                    'next_page_token_2': next_page_token_2
                })

            senders = [((e.get('from_name') or e.get('from_email') or '').strip()) for e in emails]
            sender_counts = Counter(senders)
            top = sender_counts.most_common(3)

            flagged = []
            previews = []
            import re as _re

            def _strip_html_css(raw):
                """Convert HTML/CSS email body to plain text for display."""
                if not raw:
                    return ''
                s = str(raw)
                s = _re.sub(r'<style\b[^>]*>[\s\S]*?</style>', ' ', s, flags=_re.IGNORECASE | _re.DOTALL)
                s = _re.sub(r'<script\b[^>]*>[\s\S]*?</script>', ' ', s, flags=_re.IGNORECASE | _re.DOTALL)
                s = _re.sub(r'<[^>]+>', ' ', s)
                s = html.unescape(s)
                s = _re.sub(r'\s+', ' ', s).strip()
                return s

            # Chat tab: show up to 50 emails in the response (or all if fewer)
            preview_limit = min(len(emails), 50)

            for e in emails[:preview_limit]:
                subj = (e.get('subject') or '').strip()
                body = (e.get('body') or '')
                snippet = _strip_html_css(body)
                preview = (snippet[:140] + '...') if len(snippet) > 140 else snippet
                previews.append({'from': e.get('from_name') or e.get('from_email'), 'subject': subj, 'preview': preview, 'account': e.get('account')})

                low = (subj + ' ' + (snippet or '')).lower()
                if any(k in low for k in urgency_keywords):
                    flagged.append({'from': e.get('from_name') or e.get('from_email'), 'subject': subj})

            top_senders_str = ', '.join([f"{s[0]} ({s[1]})" for s in top if s[0]]) or 'Various'
            flagged_str = ''
            if flagged:
                flagged_list = '; '.join([f"{f['from']}: {f['subject']}" for f in flagged[:5]])
                flagged_str = f"\n⚠️ Urgent/Action-required: {len(flagged)} — {flagged_list}"

            preview_lines = []
            # Respect preview_limit when showing recent message previews
            for idx, p in enumerate(previews[:preview_limit], start=1):
                sender = (p.get('from') or p.get('from_email') or 'Unknown')
                # remove angle brackets and stray quotes
                sender = _re.sub(r'[<>"\']', '', str(sender)).strip()
                subject = (p.get('subject') or '(no subject)').replace('\n', ' ').strip()
                preview_text = (p.get('preview') or '').replace('\n', ' ').strip()
                preview_text = _re.sub(r'\s+', ' ', preview_text)
                # truncate to a conservative single-line preview
                if len(preview_text) > 120:
                    preview_text = preview_text[:117].rsplit(' ', 1)[0] + '...'
                account_tag = p.get('account', '')
                account_str = f" [{account_tag}]" if account_tag else ""
                preview_lines.append(f"{idx}. **{subject}** — _{sender}_{account_str}\n   {preview_text}")

            # NOTE: We intentionally avoid AI-generated email summaries here because they often
            # mention the number of emails shown (e.g. 10) which can contradict the true unread count.

            # Local fallback: generate concise one-sentence summaries per message
            def _local_one_sentence(subject, body, sender, max_words=25):
                body_plain = _strip_html_css(body or '')
                text = ((subject or '') + ' ' + body_plain).strip()
                text = _re.sub(r'\s+', ' ', text)
                if not text:
                    return f"A short message from {sender}."
                low = text.lower()
                if any(k in low for k in ['invoice', 'payment', 'receipt', 'bill', 'charged']):
                    return f"Payment/finance-related message concerning {subject or 'your account'}."
                if any(k in low for k in ['schedule', 'meeting', 'call', 'reschedule']):
                    return f"Request to schedule or update a meeting regarding {subject or 'the topic'}."
                words = text.split()[:max_words]
                sentence = ' '.join(words).strip()
                if not sentence.endswith('.'):
                    sentence = sentence.rstrip('.,;:') + '.'
                return sentence

            from email.utils import parsedate_to_datetime as _parsedate_to_datetime
            emails_list = []
            numbered_lines = []

            def _fmt_received(raw_date: str) -> str:
                try:
                    dt = _parsedate_to_datetime(raw_date)
                    if getattr(dt, "tzinfo", None):
                        dt = dt.astimezone()
                    return dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    return (raw_date or "").strip()

            for idx, e in enumerate(emails[:preview_limit], start=1):
                sender = e.get('from_name') or e.get('from_email') or 'Unknown'
                subject = e.get('subject') or '(no subject)'
                body = e.get('body') or e.get('preview') or ''
                summary = _local_one_sentence(subject, body, sender)
                received_raw = e.get('date') or e.get('received') or ''
                received = _fmt_received(str(received_raw))

                body_plain = _strip_html_css(body)
                emails_list.append({
                    'sender': sender,
                    'subject': subject,
                    'snippet': (body_plain or '')[:300],
                    'summary': summary,
                    'received_at': received_raw or None,
                    'account': e.get('account')
                })

                acc = e.get('account', '')
                acc_suffix = f" ({acc})" if acc else ""
                numbered_lines.append(f"{idx}. [{received}] {subject} - {sender}{acc_suffix}")
                if summary:
                    numbered_lines.append(f"   {summary}")

            if total_unread > preview_limit:
                numbered_lines.append("\n...")

            header = f"📧 You have {total_unread} unread emails in {account_label}."
            body_text = "\n".join(numbered_lines) if numbered_lines else "No unread emails found."
            response_text = header + "\n\n" + body_text
            if next_page_token or next_page_token_2:
                response_text += "\n\nSay **'show more'** to load the next unread emails."
            elif total_unread > preview_limit:
                remaining = max(0, total_unread - preview_limit)
                response_text += f"\n\nShowing {preview_limit} of {total_unread}. Say 'show more' for the next batch."

            return jsonify({
                'response': response_text,
                'function_called': 'get_unread_emails',
                'total_unread': total_unread,
                'emails': emails_list,
                'ai_summary': None,
                'next_page_token': next_page_token,
                'next_page_token_2': next_page_token_2
            })
    except Exception as _e:
        logger.exception(f"Fast-path email check failed: {_e}")
        # Fall through to normal processing if fast-path fails
    try:
        # DISABLED: Database history retrieval to prevent timeout
        # The database query was causing timeouts, so we skip it entirely
        # Each question is now answered independently without past context

        
        # Build messages for OpenAI - comprehensive system prompt
        system_content = """You are a helpful AI assistant. Provide thorough, detailed, and well-formatted responses. 
When asked for lists, provide complete lists with proper formatting (numbered or bulleted). 
Use markdown formatting for better readability (bold, lists, code blocks, etc.).
Be conversational and helpful, like ChatGPT.

**Two Gmail accounts — always distinguish first vs second from the user's words:**
- **First account** = EMAIL1. Treat as first when the user says: first account, my first account, account 1, 1st account, email 1, primary account, main account, first Gmail, only first, first only, "in my first account", "from the first account".
- **Second account** = EMAIL2. Treat as second when the user says: second account, my second account, account 2, 2nd account, email 2, second Gmail, only second, second only, "in my second account", "from the second account", "using my second account", "with my second account".

**get_unread_emails:** Set account='first' when the user asks only for first account/EMAIL1/account 1; set account='second' when they ask only for second account/EMAIL2/account 2; set account='both' when they ask for "new emails" without specifying, or "both accounts".
**send_email:** Set from_second_account=true only when the user clearly asks to send FROM the second account (e.g. "send ... using my second account", "from the second account", "from EMAIL2"). Otherwise use the first account (from_second_account=false).
**reply_to_email:** Reply from the account that received the email. If the email was listed with (EMAIL2), set from_second_account=true; if (EMAIL1), set from_second_account=false.
**clean_gmail:** Set use_second_account=true when the user asks to clean/delete from the second account only; false for first account only."""
        
        messages = [
            {
                "role": "system",
                "content": system_content
            }
        ]
        
        # Get conversation history from frontend (limited to prevent timeout)
        conversation_history = data.get('history', [])
        if conversation_history and isinstance(conversation_history, list):
            # Limit history to last 10 messages (5 exchanges) to prevent timeout
            recent_history = conversation_history[-10:]
            for msg in recent_history:
                if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                    messages.append({
                        "role": msg['role'],
                        "content": str(msg['content'])[:2000]  # Limit individual message length
                    })
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

            # News detection (broader): detect queries asking for latest news/updates/headlines
        try:
            is_news_query = False

            news_keywords_re = re.compile(r"\b(news|headline|headlines|latest|recent|today|breaking|updates|update|in the news|what(?:'s| is) new|any updates)\b", re.IGNORECASE)
            if news_keywords_re.search(user_message):
                is_news_query = True

            # Detect present-tense 'who is the current X' or 'who is president' style questions
            if re.search(r"\bwho\s+is\b", user_message, re.IGNORECASE) and re.search(r"\b(current|today|now|president|prime minister|leader|king|queen|chancellor|pm|president of)\b", user_message, re.IGNORECASE):
                is_news_query = True

            # Also consider phrasing like 'tell me about X' or 'give me the latest on X' as news queries
            if re.search(r"\b(?:tell me|give me|show me|what(?:'s| is| are)|any news)\b.*\babout\b", user_message, re.IGNORECASE):
                is_news_query = True

            topic = None
            # Try to extract topic after 'about' or after news keywords or 'who is' patterns
            m = re.search(r"news(?:\s+(?:about|on|for)\s+)(.+)$", user_message, re.IGNORECASE)
            if not m:
                m = re.search(r"who\s+is\s+(?:the\s+)?(current\s+)?(.+)$", user_message, re.IGNORECASE)
            if not m:
                m = re.search(r"(?:about|on|regarding|re)\s+([A-Za-z0-9\-&,()'\"\s]+)", user_message, re.IGNORECASE)
            if not m:
                m = re.search(r"(?:latest|headlines|news)\s+(?:about|on|for)?\s*(.+)", user_message, re.IGNORECASE)

            if m:
                # choose the last capture group that is non-empty
                groups = [g for g in m.groups() if g]
                if groups:
                    topic = groups[-1].strip().strip('?.!')

            news_snippet = None
            if is_news_query and NEWSAPI_KEY:
                try:
                    articles = fetch_latest_news(q=topic, country='us', pageSize=10)
                    if articles:
                        lines = []
                        for a in articles:
                            title = a.get('title') or ''
                            src = a.get('source') or ''
                            desc = a.get('description') or ''
                            url = a.get('url') or ''
                            lines.append(f"- {title} ({src})\n  {desc}\n  {url}")
                        news_snippet = "\n\nNewsAPI - Recent articles (most recent first):\n" + "\n".join(lines)
                        # Insert as a system message right after the system prompt so the model can use it
                        messages.insert(1, {"role": "system", "content": news_snippet})
                        logger.info(f"[CHAT-{request_id}] Included {len(articles)} news articles in prompt (topic='{topic}')")
                except Exception as e:
                    logger.warning(f"[CHAT-{request_id}] News fetch failed: {e}")
            # Fallback: if no explicit news query detected, attempt to infer a topic
            # from capitalized proper-noun phrases (e.g., person/place/org) and fetch recent news.
            if not news_snippet and not is_news_query and NEWSAPI_KEY:
                try:
                    # Find capitalized phrases (2+ words) or single notable capitalized words
                    proper_nouns = re.findall(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3})\b", user_message)
                    # If none, try single capitalized words that are not sentence-start
                    if not proper_nouns:
                        proper_nouns = re.findall(r"\b(?!I\b)([A-Z][a-z]{2,})\b", user_message)
                    # Choose the longest candidate as topic
                    if proper_nouns:
                        candidates = sorted(set([p.strip() for p in proper_nouns]), key=lambda s: -len(s))
                        inferred_topic = candidates[0]
                        articles = fetch_latest_news(q=inferred_topic, country='us', pageSize=8)
                        if articles:
                            lines = []
                            for a in articles:
                                title = a.get('title') or ''
                                src = a.get('source') or ''
                                desc = a.get('description') or ''
                                url = a.get('url') or ''
                                lines.append(f"- {title} ({src})\n  {desc}\n  {url}")
                            news_snippet = "\n\nNewsAPI - Recent articles (most recent first):\n" + "\n".join(lines)
                            messages.insert(1, {"role": "system", "content": news_snippet})
                            logger.info(f"[CHAT-{request_id}] Fallback included {len(articles)} news articles for inferred topic='{inferred_topic}'")
                except Exception as e:
                    logger.debug(f"[CHAT-{request_id}] News fallback failed: {e}")
        except Exception as e:
            logger.debug(f"News detection error: {e}")

        # Bing grounding: inject web search results (like ChatGPT.com with Bing) when Bing key is set
        try:
            from services.contact_resolver import bing_web_search_grounding, email_finder_keys_status
            if email_finder_keys_status().get("bing_configured"):
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
                        bing_snippet = "\n".join(lines)
                        messages.insert(1, {"role": "system", "content": bing_snippet})
                        logger.info(f"[CHAT-{request_id}] Bing grounding: injected {len(results)} web snippets")
        except Exception as e:
            logger.debug(f"[CHAT-{request_id}] Bing grounding failed: {e}")
        
        total_context = len(messages)
        logger.info(f"[CHAT] Total messages in context: {total_context}")
        
        # Direct call - minimize logging overhead
        api_start_time = time.time()
        try:
            # Use shared OpenAI client for better performance (faster than creating new client each time)
            client = get_openai_client()

            # Retry with exponential backoff for transient errors (rate limits, timeouts)
            max_retries = int(os.getenv('OPENAI_MAX_RETRIES', '4'))
            base_delay = float(os.getenv('OPENAI_RETRY_BASE_DELAY', '1.0'))
            last_exception = None
            response = None
            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo",  # Fast model
                        messages=messages,  # Use full conversation history
                        functions=FUNCTIONS,  # Enable function calling for app launch, email, etc.
                        function_call="auto",  # Let the model decide when to call functions
                        max_tokens=4000,  # Increased for comprehensive responses (lists, detailed answers)
                        temperature=0.7,
                        stream=False,  # No streaming - get complete response immediately
                    )
                    api_duration = time.time() - api_start_time
                    logger.info(f"[CHAT-{request_id}] API call completed in {api_duration:.2f} seconds (attempt {attempt+1})")
                    last_exception = None
                    break
                except Exception as api_error:
                    last_exception = api_error
                    err_str = str(api_error).lower()
                    # If quota is insufficient, don't retry — fail fast with clear message
                    if 'insufficient_quota' in err_str or ('quota' in err_str and 'exceed' in err_str):
                        logger.error(f"[CHAT-{request_id}] OpenAI quota error (no retries): {err_str}", exc_info=True)
                        # Raise a specific exception to be handled by outer except
                        raise Exception(f"insufficient_quota: {err_str}")

                    is_rate = 'rate limit' in err_str or '429' in err_str
                    is_timeout = 'timeout' in err_str or 'timed out' in err_str or 'read timeout' in err_str
                    # Decide whether to retry on this error
                    if attempt < (max_retries - 1) and (is_rate or is_timeout or 'could not connect' in err_str or 'connection' in err_str):
                        sleep_for = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(f"[CHAT-{request_id}] Transient OpenAI error (attempt {attempt+1}/{max_retries}): {err_str}. Retrying in {sleep_for:.1f}s")
                        time.sleep(sleep_for)
                        continue
                    # No more retries, re-raise to be handled by outer except
                    logger.error(f"[CHAT-{request_id}] OpenAI API error (no more retries): {err_str}", exc_info=True)
                    raise
        except Exception as api_error:
            error_str = str(api_error).lower()
            logger.error(f"[CHAT-{request_id}] OpenAI API error: {error_str}", exc_info=True)
            
            # Check for specific error types
            elapsed_time = time.time() - api_start_time
            if 'timeout' in error_str or 'timed out' in error_str or 'read timeout' in error_str:
                logger.error(f"[CHAT-{request_id}] OpenAI API timeout after {elapsed_time:.2f} seconds")
                return jsonify({
                    'response': f"I apologize, but the request took too long ({elapsed_time:.1f}s). This might be due to network issues or OpenAI API being slow. Please try again.",
                    'function_called': None,
                    'error': 'timeout'
                }), 500
            elif 'insufficient_quota' in error_str or ('quota' in error_str and 'exceed' in error_str):
                return jsonify({
                    'response': "I apologize, but your OpenAI quota appears to be exhausted. Please check your OpenAI plan and billing details.",
                    'function_called': None,
                    'error': 'insufficient_quota'
                }), 429
            elif 'rate limit' in error_str or '429' in error_str:
                return jsonify({
                    'response': "I apologize, but I'm receiving too many requests. Please wait a moment and try again.",
                    'function_called': None,
                    'error': 'rate_limit'
                }), 429
            elif 'invalid' in error_str or '401' in error_str or '403' in error_str:
                return jsonify({
                    'response': "I apologize, but there's an authentication issue. Please check your OpenAI API key.",
                    'function_called': None,
                    'error': 'auth_error'
                }), 500
            else:
                return jsonify({
                    'response': f"I apologize, but I encountered an error: {str(api_error)}. Please try again.",
                    'function_called': None,
                    'error': str(api_error)
                }), 500
        
        # Validate response immediately
        if not response:
            logger.error(f"[CHAT-{request_id}] Response is None")
            return jsonify({
                'response': "I apologize, but I received no response. Please try again.",
                'function_called': None,
                'error': 'no_response'
            }), 500
        
        if not hasattr(response, 'choices') or not response.choices or len(response.choices) == 0:
            logger.error(f"[CHAT-{request_id}] Empty or invalid response from OpenAI")
            return jsonify({
                'response': "I apologize, but I received an invalid response. Please try again.",
                'function_called': None,
                'error': 'invalid_response'
            }), 500
        
        message = response.choices[0].message
        function_called = None
        final_message = None
        _response_extra = None  # e.g. next_page_token(s) for get_unread_emails
        
        # Check if a function was called
        if hasattr(message, 'function_call') and message.function_call:
            # Function was called - execute it
            function_name = message.function_call.name
            try:
                function_args = json.loads(message.function_call.arguments)
            except json.JSONDecodeError:
                function_args = {}
            
            logger.warning(f"[CHAT-{request_id}] Function called: {function_name} with args: {function_args}")
            function_called = function_name
            function_args = dict(function_args) if isinstance(function_args, dict) else {}

            # Map frontend/function account flags to backend use_second_gmail (always send a boolean)
            if function_name == 'send_email':
                from_second = function_args.get('from_second_account')
                from_second = from_second is True or (isinstance(from_second, str) and from_second.strip().lower() == 'true')
                from_ui = bool(data.get('send_from_second_account', False)) if isinstance(data, dict) else False
                # Also detect "second account" in the user's message (e.g. "send ... using my second account")
                msg_lower = (user_message or '').lower()
                from_message = bool(re.search(
                    r"\b(from\s+the\s+second\s+account|from\s+second\s+account|using\s+(?:my\s+)?(?:the\s+)?second\s+account|"
                    r"with\s+(?:my\s+)?(?:the\s+)?second\s+account|my\s+second\s+account|from\s+EMAIL2|account\s+2)\b",
                    msg_lower
                ))
                function_args['use_second_gmail'] = bool(from_second or from_ui or from_message)
            elif function_name == 'reply_to_email':
                function_args['use_second_gmail'] = function_args.get('from_second_account', False)
            elif function_name == 'clean_gmail':
                function_args['use_second_gmail'] = function_args.get('use_second_account', False)

            # get_unread_emails: support account first / second / both (EMAIL1 first then EMAIL2)
            if function_name == 'get_unread_emails':
                account_raw = (function_args.get('account') or 'both')
                account = str(account_raw).strip().lower()
                # Normalize so we reliably distinguish first vs second (e.g. "1" -> first, "2" -> second)
                if account in ('1', 'one', 'account1', 'email1', 'first account', 'primary'):
                    account = 'first'
                elif account in ('2', 'two', 'account2', 'email2', 'second account'):
                    account = 'second'
                elif account not in ('first', 'second', 'both'):
                    account = 'both'
                # Single account: 50; both: 25 per account
                limit_per = 50 if account in ('first', 'second') else min(25, max(1, int(function_args.get('limit') or 25)))
                query = function_args.get('query') or 'in:inbox category:primary is:unread'
                page1 = data.get('email_page_token') if isinstance(data, dict) else None
                page2 = data.get('email_page_token_2') if isinstance(data, dict) else None
                caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
                if account == 'second':
                    args2 = {'limit': limit_per, 'query': query, 'use_second_gmail': True}
                    if page2:
                        args2['page_token'] = page2
                    function_result = call_backend_function('get_unread_emails', args2, caller_credentials=caller_creds)
                    if isinstance(function_result, dict) and function_result.get('emails'):
                        function_result['emails'] = [dict(e, account='EMAIL2') for e in function_result['emails'] if isinstance(e, dict)]
                elif account == 'first':
                    args1 = {'limit': limit_per, 'query': query}
                    if page1:
                        args1['page_token'] = page1
                    function_result = call_backend_function('get_unread_emails', args1, caller_credentials=caller_creds)
                    if isinstance(function_result, dict) and function_result.get('emails'):
                        function_result['emails'] = [dict(e, account='EMAIL1') for e in function_result['emails'] if isinstance(e, dict)]
                else:
                    args1 = {'limit': limit_per, 'query': query}
                    if page1:
                        args1['page_token'] = page1
                    args2 = {'limit': limit_per, 'query': query, 'use_second_gmail': True}
                    if page2:
                        args2['page_token'] = page2
                    res1 = call_backend_function('get_unread_emails', args1, caller_credentials=caller_creds)
                    res2 = call_backend_function('get_unread_emails', args2, caller_credentials=caller_creds)
                    emails1 = [dict(e, account='EMAIL1') for e in (res1.get('emails') or []) if isinstance(e, dict)]
                    emails2 = [dict(e, account='EMAIL2') for e in (res2.get('emails') or []) if isinstance(e, dict)] if isinstance(res2, dict) and res2.get('success') else []
                    function_result = {
                        'success': res1.get('success', False),
                        'emails': emails1 + emails2,
                        'total_unread': res1.get('total_unread', len(emails1)) + (res2.get('total_unread', len(emails2)) if isinstance(res2, dict) and res2.get('success') else 0),
                        'next_page_token': res1.get('next_page_token'),
                        'next_page_token_2': res2.get('next_page_token') if isinstance(res2, dict) and res2.get('success') else None
                    }
                    if not res1.get('success'):
                        function_result['error'] = res1.get('detail') or res1.get('message') or res1.get('error') or 'Failed to fetch emails'
            else:
                function_result = call_backend_function(function_name, function_args, caller_credentials=data.get('user_credentials'))
            
            # For app launches, return immediately without second OpenAI call for speed
            if function_name == 'launch_app':
                if function_result.get('success'):
                    final_message = function_result.get('message', f"✅ Successfully launched {function_args.get('app_name', 'the app')}")
                else:
                    final_message = function_result.get('detail', function_result.get('error', f"❌ Failed to launch {function_args.get('app_name', 'the app')}"))
            elif function_name == 'get_unread_emails':
                if not function_result.get('success'):
                    final_message = function_result.get('message') or function_result.get('error') or function_result.get('detail') or 'Failed to fetch emails'
                else:
                    emails_raw = function_result.get('emails', []) or []
                    emails = [e for e in emails_raw if isinstance(e, dict)]
                    total_unread = function_result.get('total_unread', len(emails))
                    if not emails:
                        final_message = f"📧 No new emails. (total unread: {total_unread})"
                    else:
                        from email.utils import parsedate_to_datetime as _pd
                        lines = []
                        for idx, e in enumerate(emails[:50], start=1):
                            sender = e.get('from_name') or e.get('from_email') or 'Unknown'
                            subj = (e.get('subject') or '(no subject)').replace('\n', ' ').strip()
                            raw_date = e.get('date') or e.get('received') or ''
                            try:
                                dt = _pd(str(raw_date))
                                date_str = dt.strftime("%Y-%m-%d %H:%M") if getattr(dt, 'strftime', None) else str(raw_date)[:16]
                            except Exception:
                                date_str = str(raw_date)[:16] if raw_date else ''
                            acc = e.get('account', '')
                            acc_suffix = f" ({acc})" if acc else ""
                            lines.append(f"{idx}. [{date_str}] {subj} — {sender}{acc_suffix}")
                        final_message = f"📧 You have {total_unread} unread emails.\n\n" + "\n".join(lines)
                        if total_unread > len(emails):
                            final_message += "\n\nSay 'show more' for the next page."
                if function_result.get('next_page_token') is not None or function_result.get('next_page_token_2') is not None:
                    _response_extra = {'next_page_token': function_result.get('next_page_token'), 'next_page_token_2': function_result.get('next_page_token_2')}
            elif function_name == 'find_email':
                # Email lookup: DB first, then Bing (or show method to find). Return clear message.
                status = function_result.get('_http_status', 0)
                if status == 200 and function_result.get('success'):
                    src = function_result.get('source', '')
                    name_d = function_result.get('name', function_args.get('name', ''))
                    email = function_result.get('email', '')
                    if src == 'database':
                        final_message = f"📧 **From your contacts** — **{name_d}**: {email}"
                    else:
                        final_message = f"📧 **Found via web search** (saved to your contacts) — **{name_d}**: {email}"
                elif status == 400:
                    final_message = "🔍 " + (function_result.get('detail', 'Email finder is not configured. Add BING_API_KEY to .env or Settings to look up emails by name.'))
                elif status == 404:
                    final_message = "🔍 " + (function_result.get('detail', f'No email found.')) + "\n\n_You can add contacts manually in Settings if you know the email._"
                else:
                    final_message = "🔍 " + (function_result.get('detail', function_result.get('error', 'Could not look up email. Please try again.')))
            else:
                # For other functions, add function result to messages and call OpenAI again to get the response
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": function_name,
                        "arguments": message.function_call.arguments
                    }
                })
                messages.append({
                    "role": "function",
                    "name": function_name,
                    "content": json.dumps(function_result)
                })
                
                # Second API call to get the final response
                try:
                    logger.warning(f"[CHAT-{request_id}] Making second API call after function execution")
                    response2 = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=messages,  # Use full conversation history
                        functions=FUNCTIONS,
                        function_call="auto",
                        max_tokens=4000,  # Increased for comprehensive responses
                        temperature=0.7,
                        stream=False,
                    )
                    
                    message2 = response2.choices[0].message
                    if hasattr(message2, 'content') and message2.content:
                        final_message = message2.content
                    else:
                        final_message = f"Executed {function_name}. Result: {json.dumps(function_result)}"
                except Exception as second_call_error:
                    logger.error(f"[CHAT-{request_id}] Second API call failed: {second_call_error}")
                    # Fallback: use function result directly
                    if function_result.get('success'):
                        final_message = function_result.get('message', f"Successfully executed {function_name}")
                    else:
                        final_message = function_result.get('error', f"Executed {function_name} but got an error")
        
        # If no function was called, use direct response
        if final_message is None:
            if not hasattr(message, 'content'):
                logger.error(f"[CHAT-{request_id}] Message has no content attribute")
                return jsonify({
                    'response': "I apologize, but I couldn't generate a response. Please try again.",
                    'function_called': None,
                    'error': 'no_content'
                }), 500
            
            if not message.content:
                logger.warning(f"[CHAT-{request_id}] Message content is None or empty")
                final_message = "I apologize, but I couldn't generate a response. Please try again."
            else:
                final_message = message.content
        
        # Validate final_message
        if not final_message or not isinstance(final_message, str):
            logger.warning(f"[CHAT] Invalid final_message: type={type(final_message)}, value={str(final_message)[:100]}")
            final_message = str(final_message) if final_message else "No response generated"
        
        logger.info(f"[CHAT] GPT Response preview: '{final_message[:100]}...' (length={len(final_message)})")
        
        # Prepare response first - don't wait for database save
        response_data = {
            'response': final_message,
            'function_called': function_called
        }
        if _response_extra:
            response_data.update(_response_extra)

        
        
        # Return response immediately
        total_duration = time.time() - request_start_time
        logger.info(f"[CHAT-{request_id}] Total request duration: {total_duration:.2f} seconds (response length={len(final_message)})")
        logger.info(f"[CHAT-{request_id}] Returning response: {response_data}")
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
        logger.error(f"[CHAT] Error: {error_str}")
        error_response = f'Sorry, I encountered an error: {str(e)}'
        
        # Don't save errors to database in blocking way - return immediately
        # Save error to database if user_id is provided (non-blocking)
        if user_id and DATABASE_AVAILABLE:
            import threading
            def save_error_in_background():
                try:
                    logger.info(f"[CHAT] Saving error to database in background: user_id={user_id}, mode=error")
                    save_chat_to_db(user_id, user_message, error_response, None, None, 'error')
                except Exception as db_save_error:
                    logger.error(f"[CHAT] Database save failed (non-critical): {db_save_error}")
            threading.Thread(target=save_error_in_background, daemon=True).start()
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
            # Minimal logging in background thread - only log errors
            # logger.info(f"[DB] Chat saved successfully: user_id={user_id}, id={chat_record.id}, mode={mode}")
        except Exception as e:
            db.rollback()
            logger.error(f"[DB] Error saving chat to database: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[DB] Database connection error: {e}", exc_info=True)


if __name__ == '__main__':
    print("=" * 60)
    print("ChatGPT Interface Server Starting...")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    # Use ASCII-safe characters for Windows compatibility
    _key = _current_openai_key()
    api_status = '[OK] Configured' if (_key and _key != 'your_openai_api_key_here') else '[X] Not configured'
    print(f"OpenAI API Key: {api_status}")
    print("=" * 60)
    print("\n[*] Server running on http://localhost:5000")
    print("[*] Open http://localhost:5000/chat_interface.html in your browser to start chatting")
    print("\n[*] Make sure the backend is running on port 8000!")
    print("=" * 60)
    
    # Run without Flask debug/reloader so the process stays single-threaded
    # and parent process (`app.py`) can correctly detect its status.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
