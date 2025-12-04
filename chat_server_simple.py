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
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY
USE_OPENAI = OPENAI_API_KEY and OPENAI_API_KEY != 'your_openai_api_key_here'

BACKEND_URL = "http://localhost:8000"

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
                "max_results": {
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
    """Parse user message and determine action"""
    message_lower = message.lower()
    
    # App launch patterns
    launch_patterns = [
        r'open\s+(\w+)',
        r'launch\s+(\w+)',
        r'start\s+(\w+)',
        r'run\s+(\w+)',
    ]
    
    for pattern in launch_patterns:
        match = re.search(pattern, message_lower)
        if match:
            app_name = match.group(1)
            return {'action': 'launch_app', 'app_name': app_name}
    
    # Email sending patterns
    send_patterns = [
        r"send\s+['\"](.+?)['\"]\s+to\s+([\w\.-]+@[\w\.-]+)",
        r"email\s+['\"](.+?)['\"]\s+to\s+([\w\.-]+@[\w\.-]+)",
        r"send\s+email\s+to\s+([\w\.-]+@[\w\.-]+).*?['\"](.+?)['\"]",
    ]
    
    for pattern in send_patterns:
        match = re.search(pattern, message)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                # Extract message and email (order depends on pattern)
                if '@' in groups[0]:
                    email = groups[0]
                    msg = groups[1] if len(groups) > 1 else "Hi"
                else:
                    msg = groups[0]
                    email = groups[1]
                return {
                    'action': 'send_email',
                    'to': email,
                    'subject': msg,
                    'body': msg
                }
    
    # Email patterns (placeholder - needs real OAuth)
    if 'unread' in message_lower and 'email' in message_lower:
        return {'action': 'get_emails'}
    
    if 'send email' in message_lower or 'email to' in message_lower:
        return {'action': 'send_email', 'needs_oauth': True}
    
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
    
    elif action == 'get_emails':
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/email/unread",
                json={"user_credentials": USER_CREDENTIALS, "max_results": 10}
            )
            result = response.json()
            
            if response.status_code == 200 and result.get('success'):
                emails = result.get('emails', [])
                if emails:
                    email_list = "\n".join([f"• From: {e['from']} - {e['subject']}" for e in emails[:5]])
                    return {
                        'response': f"📧 You have {len(emails)} unread emails:\n{email_list}",
                        'function_called': 'get_emails'
                    }
                else:
                    return {
                        'response': "📧 No unread emails found.",
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
        if action_data.get('needs_oauth'):
            return {
                'response': "📧 Sending emails requires Gmail OAuth authentication. This feature needs real user credentials.",
                'function_called': None
            }
        
        try:
            email_data = {
                "user_credentials": USER_CREDENTIALS,
                "to": action_data.get('to'),
                "subject": action_data.get('subject'),
                "body": action_data.get('body')
            }
            response = requests.post(
                f"{BACKEND_URL}/api/email/send",
                json=email_data
            )
            result = response.json()
            
            if response.status_code == 200 and result.get('success'):
                return {
                    'response': f"✅ Email sent to {action_data.get('to')}!",
                    'function_called': 'send_email'
                }
            else:
                return {
                    'response': f"❌ {result.get('error', 'Failed to send email. OAuth required.')}",
                    'error': True
                }
        except Exception as e:
            return {
                'response': f"❌ Error sending email: {str(e)}",
                'error': True
            }
    
    else:
        # Default chat response
        return {
            'response': """I can help you launch applications! Try saying:
• "Open Notepad"
• "Launch Calculator"
• "Start Chrome"
• "Run Paint"

Available apps: notepad, calc, calculator, chrome, firefox, edge, vscode, code, excel, word, powerpoint, outlook, paint, mspaint

📧 Email features require OpenAI API credits or ChatGPT integration.""",
            'function_called': None
        }


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "running", "service": "ChatGPT Interface Server (No OpenAI)"})


@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages with OpenAI + fallback"""
    data = request.json
    user_message = data.get('message', '')
    history = data.get('history', [])
    
    if not user_message:
        return jsonify({
            'response': 'Please enter a message.',
            'error': True
        })
    
    # Try OpenAI first if available
    if USE_OPENAI:
        try:
            # Build messages for OpenAI
            messages = [
                {
                    "role": "system",
                    "content": """You are a helpful AI assistant that can launch applications and manage emails on the user's computer.
                    You can:
                    1. Have natural conversations and answer questions
                    2. Launch applications (notepad, calculator, chrome, etc.)
                    3. Send emails via Gmail
                    4. Check unread emails
                    5. Reply to emails
                    
                    Be friendly, conversational, and helpful. When users ask you to send emails, use the send_email function with proper to/subject/body parameters.
                    For casual messages like "Send 'hi' to xxx@yyy.com", use "hi" as both subject and body."""
                }
            ]
            
            # Add conversation history
            messages.extend(history[-10:])
            
            # Add current user message
            messages.append({"role": "user", "content": user_message})
            
            # Call OpenAI with function calling
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                functions=FUNCTIONS,
                function_call="auto",
                temperature=0.7
            )
            
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
                        json={"app_name": app_name}
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
                        json=email_data
                    )
                    function_result = backend_response.json()
                    function_called = function_name
                
                elif function_name == 'get_unread_emails':
                    email_data = {
                        "user_credentials": USER_CREDENTIALS,
                        "max_results": function_args.get('max_results', 10)
                    }
                    backend_response = requests.post(
                        f"{BACKEND_URL}/api/email/unread",
                        json=email_data
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
                        json=email_data
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
                    second_response = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=messages
                    )
                    
                    final_message = second_response.choices[0].message.content
                else:
                    final_message = message.content
            else:
                final_message = message.content
            
            return jsonify({
                'response': final_message,
                'function_called': function_called,
                'mode': 'openai'
            })
        
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
        
        return jsonify(result)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({
            'response': f'Sorry, I encountered an error: {str(e)}',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print("=" * 60)
    print("ChatGPT Interface Server Starting (Hybrid Mode)")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"OpenAI API Key: {'✓ Configured - Full ChatGPT mode' if USE_OPENAI else '✗ Not configured - Keyword mode'}")
    print(f"Mode: {'OpenAI + Fallback' if USE_OPENAI else 'Keyword-based only'}")
    print("=" * 60)
    print("\n🚀 Server running on http://localhost:5000")
    print("📱 Open chat_interface.html in your browser to start")
    print("\n💡 Features:")
    if USE_OPENAI:
        print("  ✓ Full ChatGPT conversational AI")
        print("  ✓ Natural language understanding")
        print("  ✓ App launching via AI")
        print("  ✓ Automatic fallback if quota exceeded")
    else:
        print("  • Keyword-based app launching")
        print("  • Add OpenAI API key for full ChatGPT features")
    print("\nMake sure the backend is running on port 8000!")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
