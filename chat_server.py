"""
Chat Server - Connects OpenAI API with your backend
This provides a ChatGPT-like experience with email and app control
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

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
    user_message = data.get('message', '')
    history = data.get('history', [])
    
    if not OPENAI_API_KEY or OPENAI_API_KEY == 'your_openai_api_key_here':
        return jsonify({
            'response': '⚠️ OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.',
            'error': 'missing_api_key'
        })
    
    try:
        # Build messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": """You are a helpful AI assistant that can manage emails and launch applications. 
                You have access to the user's Gmail account and can launch apps on their computer.
                Be friendly, concise, and helpful. When performing actions, confirm what you did."""
            }
        ]
        
        # Add conversation history
        messages.extend(history[-10:])  # Keep last 10 messages for context
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
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
        
        return jsonify({
            'response': final_message,
            'function_called': function_called
        })
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({
            'response': f'Sorry, I encountered an error: {str(e)}',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print("=" * 60)
    print("ChatGPT Interface Server Starting...")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"OpenAI API Key: {'✓ Configured' if OPENAI_API_KEY and OPENAI_API_KEY != 'your_openai_api_key_here' else '✗ Not configured'}")
    print("=" * 60)
    print("\n🚀 Server running on http://localhost:5000")
    print("📱 Open chat_interface.html in your browser to start chatting")
    print("\nMake sure the backend is running on port 8000!")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
