"""
Chat Server - Connects OpenAI API with your backend
This provides a ChatGPT-like experience with email and app control
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import openai
import os
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# Setup logging - use WARNING level to reduce logging overhead
logging.basicConfig(level=logging.WARNING)  # Changed from INFO to WARNING for faster performance
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Configure Flask for better request handling
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BACKEND_URL = "http://72.62.162.44:8000"

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
    }
]


def call_backend_function(function_name, arguments):
    """Call the backend API with function arguments"""
    
    # Add user credentials to email functions
    if function_name in ['send_email', 'get_unread_emails', 'reply_to_email']:
        arguments['user_credentials'] = USER_CREDENTIALS
    
    # Map function names to endpoints
    endpoint_map = {
        'send_email': '/api/email/send',
        'get_unread_emails': '/api/email/unread',
        'reply_to_email': '/api/email/reply',
        'launch_app': '/api/app/launch'
    }
    
    endpoint = endpoint_map.get(function_name)
    if not endpoint:
        return {"error": f"Unknown function: {function_name}"}
    
    try:
        url = f"{BACKEND_URL}{endpoint}"
        print(f"Calling backend: {url}")
        print(f"Arguments: {json.dumps(arguments, indent=2)}")
        
        response = requests.post(url, json=arguments, timeout=5)  # Reduced to 5 seconds
        result = response.json()
        
        print(f"Backend response: {json.dumps(result, indent=2)}")
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
        
        total_context = len(messages)
        logger.info(f"[CHAT] Total messages in context: {total_context}")
        
        # Direct call - minimize logging overhead
        api_start_time = time.time()
        try:
            # Use shared OpenAI client for better performance (faster than creating new client each time)
            client = get_openai_client()
            
            # Enable function calling for app launching and email functions
            # Use stream=False explicitly to ensure we get complete response immediately
            # Increased max_tokens for comprehensive responses
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
            logger.info(f"[CHAT-{request_id}] API call completed in {api_duration:.2f} seconds")
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
            function_result = call_backend_function(function_name, function_args)
            
            # For app launches, return immediately without second OpenAI call for speed
            if function_name == 'launch_app':
                if function_result.get('success'):
                    final_message = function_result.get('message', f"✅ Successfully launched {function_args.get('app_name', 'the app')}")
                else:
                    final_message = function_result.get('detail', function_result.get('error', f"❌ Failed to launch {function_args.get('app_name', 'the app')}"))
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
    print("\n[*] Server running on http://72.62.162.44:5000")
    print("[*] Open http://72.62.162.44:5000/chat_interface.html in your browser to start chatting")
    print("\n[*] Make sure the backend is running on port 8000!")
    print("=" * 60)
    
    # Run without Flask debug/reloader so the process stays single-threaded
    # and parent process (`app.py`) can correctly detect its status.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
