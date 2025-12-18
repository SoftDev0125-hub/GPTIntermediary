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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BACKEND_URL = "http://localhost:8000"

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

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
        
        response = requests.post(url, json=arguments, timeout=10)
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
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading login page: {str(e)}", 500


@app.route('/chat_interface.html')
def chat_interface():
    """Serve the chat interface HTML (requires authentication)"""
    try:
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_interface.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading chat interface: {str(e)}", 500


@app.route('/admin_panel.html')
def admin_panel():
    """Serve the admin panel HTML (requires admin authentication)"""
    try:
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'admin_panel.html')
        return send_file(html_path)
    except Exception as e:
        return f"Error loading admin panel: {str(e)}", 500

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


@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages and function calling"""
    data = request.json
    user_message = data.get('message', '').strip()
    history = data.get('history', [])
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
        # Get conversation history from database if user_id is available
        db_history = []
        if user_id and DATABASE_AVAILABLE:
            db_history = get_conversation_history_from_db(user_id, limit=20)  # Get last 20 conversation pairs
            logger.info(f"[CHAT] Loaded {len(db_history)} messages from database history")
        
        # Build messages for OpenAI
        system_content = """You are a helpful AI assistant that can manage emails and launch applications. 
You have access to the user's Gmail account and can launch apps on their computer.
Be friendly, concise, and helpful. When performing actions, confirm what you did.

IMPORTANT: You have access to the user's previous conversation history from past sessions. 
This history contains valuable context about:
- Topics the user has discussed
- Questions they've asked before
- Your previous answers and explanations
- User preferences and interests
- Ongoing projects or tasks

CRITICAL INSTRUCTIONS FOR USING CONVERSATION HISTORY:
1. ANALYZE the conversation history carefully before responding
2. REFERENCE specific previous discussions when relevant
3. BUILD UPON previous answers rather than repeating them
4. MAINTAIN continuity - if the user asks follow-up questions, connect them to previous context
5. LEARN from patterns - notice what topics interest the user and provide deeper insights
6. REMEMBER preferences - if the user preferred certain formats or approaches, use them again
7. PROVIDE MORE ACCURATE answers by leveraging what you've discussed before

When answering:
- If the question relates to a previous topic, acknowledge it and expand on previous discussions
- Use the history to understand the user's knowledge level and adjust explanations accordingly
- Connect new questions to previous conversations when there's a relationship
- Provide more personalized responses based on what you know about the user from history"""
        
        # Add context about history if available
        if db_history:
            history_summary = f"\n\nCONVERSATION HISTORY CONTEXT:\nYou have access to {len(db_history)} previous messages from past conversations with this user. Use this history to provide contextually aware and accurate responses."
            system_content += history_summary
        
        messages = [
            {
                "role": "system",
                "content": system_content
            }
        ]
        
        # Add database conversation history first (most relevant context)
        if db_history:
            # Keep last 20 messages from database (10 conversation pairs) to provide good context
            recent_history = db_history[-20:]
            messages.extend(recent_history)
            logger.info(f"[CHAT] Added {len(recent_history)} messages from database to context")
            logger.info(f"[CHAT] History preview: First Q: {recent_history[0]['content'][:50] if recent_history else 'None'}... | Last A: {recent_history[-1]['content'][:50] if recent_history else 'None'}...")
        
        # Add frontend-provided history (if any) - this takes precedence for current session
        if history:
            messages.extend(history[-10:])  # Keep last 10 messages from current session
            logger.info(f"[CHAT] Added {len(history[-10:])} messages from frontend history")
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        logger.info(f"[CHAT] Total messages in context: {len(messages)} (1 system + {len(messages)-1} conversation messages)")
        
        # Call OpenAI with function calling
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            functions=FUNCTIONS,
            function_call="auto"
        )
        
        message = response.choices[0].message
        function_called = None
        
        # Check if function was called
        if message.function_call:
            function_name = message.function_call.name
            function_args = json.loads(message.function_call.arguments)
            
            print(f"Function called: {function_name}")
            print(f"Arguments: {function_args}")
            
            # Call backend function
            function_result = call_backend_function(function_name, function_args)
            function_called = function_name
            
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
            second_response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
            
            final_message = second_response.choices[0].message.content
        else:
            final_message = message.content
        
        # Validate final_message
        if not final_message or not isinstance(final_message, str):
            logger.warning(f"[CHAT] Invalid final_message: type={type(final_message)}, value={str(final_message)[:100]}")
            final_message = str(final_message) if final_message else "No response generated"
        
        logger.info(f"[CHAT] GPT Response preview: '{final_message[:100]}...' (length={len(final_message)})")
        
        # Save to database if user_id is provided
        if user_id and DATABASE_AVAILABLE:
            logger.info(f"[CHAT] Attempting to save chat to database: user_id={user_id}, mode=openai")
            save_chat_to_db(user_id, user_message, final_message, 'gpt-3.5-turbo', function_called, 'openai')
        elif not user_id:
            logger.warning("[CHAT] user_id not provided, skipping database save")
        elif not DATABASE_AVAILABLE:
            logger.warning("[CHAT] Database not available, skipping database save")
        
        return jsonify({
            'response': final_message,
            'function_called': function_called
        })
    
    except Exception as e:
        error_str = str(e)
        logger.error(f"[CHAT] Error: {error_str}")
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


def get_conversation_history_from_db(user_id, limit=20):
    """Retrieve previous conversation history from database for context
    
    Args:
        user_id: User ID to get conversations for
        limit: Maximum number of conversation pairs to retrieve (default 20)
    
    Returns:
        List of message dictionaries in OpenAI format: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    """
    if not DATABASE_AVAILABLE or not ChatWithGPT or not user_id:
        return []
    
    try:
        db = SessionLocal()
        try:
            # Get recent conversations for this user, ordered by most recent first
            conversations = db.query(ChatWithGPT).filter(
                ChatWithGPT.user_id == int(user_id)
            ).order_by(
                ChatWithGPT.created_at.desc()
            ).limit(limit).all()
            
            if not conversations:
                logger.info(f"[DB] No previous conversations found for user_id={user_id}")
                return []
            
            # Convert to OpenAI message format (most recent first, then reverse to chronological order)
            history = []
            for conv in reversed(conversations):
                if conv.questions and conv.answers:
                    # Clean and validate the content
                    question = str(conv.questions).strip()
                    answer = str(conv.answers).strip()
                    
                    if question and answer:  # Only add non-empty conversations
                        history.append({
                            "role": "user",
                            "content": question
                        })
                        history.append({
                            "role": "assistant",
                            "content": answer
                        })
            
            logger.info(f"[DB] Retrieved {len(history)} messages ({len(history)//2} conversation pairs) from database history for user_id={user_id}")
            
            # Log sample topics for debugging
            if history:
                sample_topics = []
                for i in range(0, min(6, len(history)), 2):
                    if i < len(history):
                        topic_preview = history[i]['content'][:40].replace('\n', ' ')
                        sample_topics.append(topic_preview)
                logger.info(f"[DB] Sample topics from history: {', '.join(sample_topics)}...")
            
            return history
        except Exception as e:
            logger.error(f"[DB] Error retrieving conversation history: {e}", exc_info=True)
            return []
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[DB] Database connection error retrieving history: {e}", exc_info=True)
        return []


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
    print("ChatGPT Interface Server Starting...")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    # Use ASCII-safe characters for Windows compatibility
    api_status = '[OK] Configured' if OPENAI_API_KEY and OPENAI_API_KEY != 'your_openai_api_key_here' else '[X] Not configured'
    print(f"OpenAI API Key: {api_status}")
    print("=" * 60)
    print("\n[*] Server running on http://localhost:5000")
    print("[*] Open chat_interface.html in your browser to start chatting")
    print("\n[*] Make sure the backend is running on port 8000!")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
