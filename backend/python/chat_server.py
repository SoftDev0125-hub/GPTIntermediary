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

# Load project root .env only (GPTIntermediary/.env)
_load_env_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_load_env_root / '.env')

# Robust env loader (fallback) to handle .env formatting variations
def _read_env_key_from_dotenv(key_name):
    val = os.getenv(key_name)
    if val:
        return val.strip()
    try:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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
    """Fetch news using NewsAPI; use 'everything' for queries and 'top-headlines' otherwise."""
    if not NEWSAPI_KEY:
        return []
    try:
        if q:
            params = {
                'apiKey': NEWSAPI_KEY,
                'q': q,
                'pageSize': min(pageSize, 20),
                'sortBy': 'publishedAt',
                'language': 'en'
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

# Configuration
OPENAI_API_KEY = _read_env_key_from_dotenv('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY') or ''
BACKEND_URL = "http://localhost:8000"

# Initialize OpenAI - use a single client instance for better performance
# Reusing a client is faster than creating a new one for each request
from openai import OpenAI
_openai_client = None

def get_openai_client():
    """Get or create OpenAI client instance"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            api_key=OPENAI_API_KEY,
            timeout=(5.0, 12.0),  # Connect: 5s, Read: 12s (shorter for faster responses)
            max_retries=0  # No retries - fail fast
        )
    return _openai_client


def analyze_emails_with_ai(emails, request_id=None, max_items=5):
    """Use OpenAI to analyze a small set of emails and produce a numbered summary.

    emails: list of dicts with keys 'from', 'subject', 'preview' (or similar)
    returns: string summary or None on failure
    """
    try:
        if not OPENAI_API_KEY or OPENAI_API_KEY == 'your_openai_api_key_here':
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
                    "description": "Email subject"
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
        "description": "Get unread emails from the user's inbox",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to retrieve (default 10)",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an email from a specific sender",
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
                }
            },
            "required": ["sender_email", "body"]
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
    
    # Add user credentials to email functions. Prefer caller-provided credentials
    if function_name in ['send_email', 'get_unread_emails', 'reply_to_email']:
        if caller_credentials and isinstance(caller_credentials, dict) and caller_credentials.get('access_token'):
            arguments['user_credentials'] = caller_credentials
        else:
            arguments['user_credentials'] = USER_CREDENTIALS
    
    # Map function names to endpoints
    endpoint_map = {
        'send_email': '/api/email/send',
        'get_unread_emails': '/api/email/unread',
        'reply_to_email': '/api/email/reply',
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
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        html_path = os.path.join(project_root, 'frontend', 'login.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading login page: {str(e)}", 500


@app.route('/chat_interface.html')
def chat_interface():
    """Serve the chat interface HTML (requires authentication)"""
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        html_path = os.path.join(project_root, 'frontend', 'chat_interface.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading chat interface: {str(e)}", 500


@app.route('/admin_panel.html')
def admin_panel():
    """Serve the admin panel HTML (requires admin authentication)"""
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        html_path = os.path.join(project_root, 'frontend', 'admin_panel.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading admin panel: {str(e)}", 500


@app.route('/styles.css')
def styles():
    """Serve the main stylesheet for the frontend pages"""
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        css_path = os.path.join(project_root, 'frontend', 'styles.css')
        return send_file(css_path)
    except Exception as e:
        return f"Error loading styles.css: {str(e)}", 500

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
    
    if not OPENAI_API_KEY or OPENAI_API_KEY == 'your_openai_api_key_here':
        return jsonify({
            'response': '[WARNING] OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.',
            'error': 'missing_api_key'
        })
    
    if not user_message:
        return jsonify({
            'response': 'Please enter a message.',
            'error': True
        })

    # Quick command: handle direct "Send <message> to <recipient>" by generating
    # an AI-written subject/body and sending via backend /api/email/send
    try:
        m_cmd = re.match(r"^\s*send\s+(.+?)\s+to\s+(.+)$", user_message, re.IGNORECASE)
        if m_cmd:
            original_text = m_cmd.group(1).strip()
            recipient = m_cmd.group(2).strip()

            # Prepare a prompt for the OpenAI client to generate a friendly subject and body
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
                        f"Recipient: {recipient}\n\n"
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
                'to': recipient,
                'subject': subject,
                'body': body
            }

            # Use provided caller credentials if present
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
    
    # Fast-path: if user asks about new emails, query Gmail primary inbox directly and return analyzed summary
    try:
        # Detect queries asking about new emails or emails from a specific sender
        if re.search(r"\b(any\s+new\s+emails|new\s+emails|check.*email|check.*emails)\b", user_message, re.IGNORECASE) or re.search(r"\b(emails?|mail|messages?)\b.*\bfrom\b", user_message, re.IGNORECASE):
            caller_creds = data.get('user_credentials') if isinstance(data, dict) else None
            # Try to detect a specific sender in the user's question ("from Alice" / "from alice@example.com")
            sender_match = None
            try:
                m = re.search(r"\bfrom\s+([\"']?)([^\"'\?]+?)\1(?=\s|$|\?)", user_message, re.IGNORECASE)
                if not m:
                    m = re.search(r"(?:emails?|mail|messages?)\s+(?:from)\s+([^\?]+)", user_message, re.IGNORECASE)
                if m:
                    sender_match = m.groups()[-1].strip()
            except Exception:
                sender_match = None

            # Build Gmail query; restrict to Primary inbox unread by default
            base_query = 'in:inbox category:primary is:unread'
            if sender_match:
                # If sender appears to be an email address, use it directly; otherwise quote the name
                sender_term = sender_match
                if '@' in sender_term:
                    sender_part = f'from:{sender_term}'
                else:
                    # Quote name for Gmail search
                    safe_name = sender_term.replace('"', '').strip()
                    sender_part = f'from:"{safe_name}"'
                query = f"{base_query} {sender_part}"
            else:
                query = base_query

            # Request messages to populate the chat "Recent messages" section
            args = {'limit': 50, 'query': query}
            result = call_backend_function('get_unread_emails', args, caller_credentials=caller_creds)

            # Handle backend errors
            if not isinstance(result, dict):
                return jsonify({'response': 'Could not contact email backend.', 'error': True}), 500

            if result.get('_http_status') == 401 or result.get('error') == 'auth_error':
                return jsonify({'response': 'Email access requires authentication. Please connect your Gmail account.', 'error': 'auth_error'}), 401

            if result.get('_http_status') == 429 or result.get('error') == 'insufficient_quota':
                return jsonify({'response': 'Email service is currently rate limited. Please try again later.', 'error': 'rate_limit'}), 429

            if not result.get('success'):
                # Return backend message if present
                err = result.get('message') or result.get('error') or str(result)
                return jsonify({'response': f'Failed to fetch emails: {err}', 'error': True}), 500

            emails = result.get('emails', [])
            total_unread = result.get('total_unread', len(emails))

            # Analyze emails: top senders, urgency, previews
            from collections import Counter
            import html
            urgency_keywords = ['urgent', 'asap', 'immediately', 'action required', 'deadline', 'due', 'important']

            if not emails:
                return jsonify({'response': f"📧 No new emails in Primary tab. (total unread: {total_unread})", 'function_called': 'get_unread_emails'})

            senders = [((e.get('from_name') or e.get('from_email') or '').strip()) for e in emails]
            sender_counts = Counter(senders)
            top = sender_counts.most_common(3)

            flagged = []
            previews = []
            import re as _re
            # Show up to MAX_UNREAD_EMAILS (default 50) in the "recent messages" section
            try:
                preview_limit = min(len(emails), int(os.getenv('MAX_UNREAD_EMAILS', '50')))
            except Exception:
                preview_limit = min(len(emails), 50)

            for e in emails[:preview_limit]:
                subj = (e.get('subject') or '').strip()
                body = (e.get('body') or '')
                snippet = _re.sub(r'<[^>]+>', '', body or '')
                snippet = html.unescape(snippet)
                snippet = snippet.replace('\n', ' ').strip()
                preview = (snippet[:140] + '...') if len(snippet) > 140 else snippet
                previews.append({'from': e.get('from_name') or e.get('from_email'), 'subject': subj, 'preview': preview})

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
                # Use a compact, markdown-friendly numbered list
                preview_lines.append(f"{idx}. **{subject}** — _{sender}_\n   {preview_text}")

            # Prefer AI analysis when available; otherwise synthesize a summary locally
            ai_enabled = bool(OPENAI_API_KEY and OPENAI_API_KEY != 'your_openai_api_key_here')
            ai_result = None

            # If sender-specific query, prepare compact email payloads (use full body when available)
            try:
                compact_for_ai = []
                for e in emails[:10]:
                    compact_for_ai.append({
                        'from': e.get('from_name') or e.get('from_email'),
                        'subject': e.get('subject'),
                        'preview': (e.get('body') or e.get('preview') or '')[:480]
                    })
                if ai_enabled and compact_for_ai:
                    ai_result = analyze_emails_with_ai(compact_for_ai, request_id=request_id, max_items=min(10, len(compact_for_ai)))
            except Exception:
                ai_result = None

            # If AI produced a structured summary, return it verbatim (it includes total count per contract)
            if ai_result and isinstance(ai_result, str) and ai_result.strip():
                response_text = ai_result
                # Also provide machine-readable emails (with truncated snippets)
                emails_list = []
                for e in emails:
                    emails_list.append({
                        'sender': e.get('from_name') or e.get('from_email'),
                        'subject': e.get('subject'),
                        'snippet': (e.get('body') or e.get('preview') or '')[:300],
                        'received_at': e.get('date') or e.get('received') or None
                    })
                return jsonify({
                    'response': response_text,
                    'function_called': 'get_unread_emails',
                    'total_unread': total_unread,
                    'emails': emails_list,
                    'ai_summary': ai_result
                })

            # Local fallback: generate concise one-sentence summaries per message
            import html
            import re as _rs
            def _local_one_sentence(subject, body, sender, max_words=25):
                text = (subject or '') + ' ' + (body or '')
                text = _rs.sub(r'<[^>]+>', ' ', text)
                text = html.unescape(text)
                text = _rs.sub(r'\\s+', ' ', text).strip()
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

            emails_list = []
            numbered_lines = []
            for idx, e in enumerate(emails[:preview_limit], start=1):
                sender = e.get('from_name') or e.get('from_email') or 'Unknown'
                subject = e.get('subject') or ''
                body = e.get('body') or e.get('preview') or ''
                summary = _local_one_sentence(subject, body, sender)
                # Machine-readable entry
                emails_list.append({
                    'sender': sender,
                    'subject': subject,
                    'snippet': (body or '')[:300],
                    'summary': summary,
                    'received_at': e.get('date') or e.get('received') or None
                })
                # Human-readable numbered lines (exact format requested)
                numbered_lines.append(f"{idx}. {sender}:")
                numbered_lines.append(summary)

            header = f"You have received {total_unread} new emails."
            body_text = "\n".join(numbered_lines) if numbered_lines else "No new messages found."
            response_text = header + "\n\n" + body_text

            return jsonify({
                'response': response_text,
                'function_called': 'get_unread_emails',
                'total_unread': total_unread,
                'emails': emails_list,
                'ai_summary': None
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
Be conversational and helpful, like ChatGPT."""
        
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
            
            # Execute the function
            function_result = call_backend_function(function_name, function_args, caller_credentials=data.get('user_credentials'))
            
            # For app launches, return immediately without second OpenAI call for speed
            if function_name == 'launch_app':
                if function_result.get('success'):
                    final_message = function_result.get('message', f"✅ Successfully launched {function_args.get('app_name', 'the app')}")
                else:
                    final_message = function_result.get('detail', function_result.get('error', f"❌ Failed to launch {function_args.get('app_name', 'the app')}"))
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
    api_status = '[OK] Configured' if OPENAI_API_KEY and OPENAI_API_KEY != 'your_openai_api_key_here' else '[X] Not configured'
    print(f"OpenAI API Key: {api_status}")
    print("=" * 60)
    print("\n[*] Server running on http://localhost:5000")
    print("[*] Open http://localhost:5000/chat_interface.html in your browser to start chatting")
    print("\n[*] Make sure the backend is running on port 8000!")
    print("=" * 60)
    
    # Run without Flask debug/reloader so the process stays single-threaded
    # and parent process (`app.py`) can correctly detect its status.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
