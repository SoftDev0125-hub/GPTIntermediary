"""
Enhanced Chat Server - With Memory and Advanced Features
Integrates with Django Q&A Database for conversation persistence
Supports GPT-4 for better responses
Includes Context Analyzer for handling relative references
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import requests
import json
from dotenv import load_dotenv
from datetime import datetime
from services.context_analyzer import ContextAnalyzer

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BACKEND_URL = "http://localhost:8000"
DJANGO_QA_URL = "http://localhost:8001/api"

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# Model selection (can use gpt-4 if available, otherwise gpt-3.5-turbo)
GPT_MODEL = os.getenv('GPT_MODEL', 'gpt-3.5-turbo')  # Change to 'gpt-4' for better responses

# User credentials
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
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body content"}
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
                "limit": {"type": "integer", "description": "Number of emails to retrieve", "default": 10}
            }
        }
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an email from a specific sender",
        "parameters": {
            "type": "object",
            "properties": {
                "sender_email": {"type": "string", "description": "Email address of the sender"},
                "body": {"type": "string", "description": "Reply message content"}
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
                "app_name": {"type": "string", "description": "Name of the app to launch"}
            },
            "required": ["app_name"]
        }
    }
]


class ConversationManager:
    """Manages conversation persistence with Django Q&A database"""
    
    def __init__(self):
        self.current_conversation_id = None
        self.rules = {}  # Store user rules/preferences, e.g., {"code_language": "Python"}

    def add_rule(self, key, value):
        """Add or update a rule/preference for the conversation"""
        self.rules[key] = value

    def get_rules(self):
        """Return all current rules/preferences as a dict"""
        return self.rules.copy()

    def clear_rules(self):
        """Clear all rules/preferences (if needed)"""
        self.rules = {}
    
    def create_conversation(self, user_id="default_user"):
        """Create a new conversation in the database"""
        try:
            response = requests.post(
                f"{DJANGO_QA_URL}/conversations/",
                json={
                    "title": f"Chat - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "user_id": user_id,
                    "conversation_type": "chat"
                }
            )
            if response.status_code == 201:
                self.current_conversation_id = response.json()['id']
                return self.current_conversation_id
        except:
            pass
        return None
    
    def add_message(self, role, content, function_name=None):
        """Add a message to the current conversation"""
        if not self.current_conversation_id:
            self.create_conversation()
        
        try:
            requests.post(
                f"{DJANGO_QA_URL}/conversations/{self.current_conversation_id}/add_message/",
                json={
                    "role": role,
                    "content": content,
                    "function_name": function_name
                }
            )
        except:
            pass
    
    def add_qa_pair(self, question, answer, category="general"):
        """Store Q&A pair for future learning"""
        if not self.current_conversation_id:
            return
        
        try:
            requests.post(
                f"{DJANGO_QA_URL}/conversations/{self.current_conversation_id}/add_qa_pair/",
                json={
                    "question": question,
                    "answer": answer,
                    "category": category
                }
            )
        except:
            pass
    
    def search_similar(self, question):
        """Search for similar previous Q&A pairs"""
        try:
            response = requests.post(
                f"{DJANGO_QA_URL}/qa-pairs/search/",
                json={"query": question, "limit": 3}
            )
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return []


conversation_manager = ConversationManager()
context_analyzer = ContextAnalyzer(max_history=50)  # Analyze contextual references


def call_backend_function(function_name, arguments):
    """Call the backend API with function arguments"""
    
    if function_name in ['send_email', 'get_unread_emails', 'reply_to_email']:
        arguments['user_credentials'] = USER_CREDENTIALS
    
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
        response = requests.post(url, json=arguments, timeout=10)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "running", "service": "Enhanced ChatGPT Server"})


@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages with memory and learning"""
    data = request.json
    user_message = data.get('message', '')
    history = data.get('history', [])
    
    if not OPENAI_API_KEY or OPENAI_API_KEY == 'your_openai_api_key_here':
        return jsonify({
            'response': '⚠️ OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.',
            'error': 'missing_api_key'
        })
    
    try:
        # Analyze references in user message
        auth_result = context_analyzer.authenticate_reference(user_message)
        # Enhanced: Replace 'in above case' and similar with actual previous Q&A
        enhanced_message = user_message
        # Find if user message contains a reference to 'above case' or similar
        import re
        above_case_pattern = re.compile(r"\b(in\s+(the\s+)?(above|previous|aforementioned)\s+case|in\s+that\s+case)\b", re.IGNORECASE)
        if above_case_pattern.search(user_message):
            # Try to get the last Q&A from conversation_manager or context_analyzer
            last_qa = None
            # Try to get from conversation_manager (if Q&A pairs are stored)
            if hasattr(conversation_manager, 'conversation_history') and conversation_manager.conversation_history:
                # Find last user/assistant pair
                for msg in reversed(conversation_manager.conversation_history):
                    if msg['role'] == 'assistant':
                        last_qa = msg['content']
                        break
            # Fallback: try context_analyzer history
            if not last_qa and context_analyzer.conversation_history:
                for msg in reversed(context_analyzer.conversation_history):
                    if msg['role'] == 'assistant':
                        last_qa = msg['content']
                        break
            if last_qa:
                # Replace the reference with the actual last answer
                enhanced_message = above_case_pattern.sub(f"Regarding the previous answer: {last_qa}", user_message)
            else:
                enhanced_message = above_case_pattern.sub("(reference not found)", user_message)
        else:
            # Use existing context analyzer logic for other references
            enhanced_message = context_analyzer.resolve_references_in_message(user_message)
        context_analyzer.add_message("user", user_message)

        # Detect and store new rules/preferences from user message
        # Example: "From now on, use Python" → rule: code_language=Python
        # This is a simple pattern; you can expand with more NLP if needed
        import re
        rule_match = re.search(r"from now(?:\s+on)?[,\s]+(.*)", user_message, re.IGNORECASE)
        if rule_match:
            rule_text = rule_match.group(1).strip()
            # Example: "use Python" → key: code_language, value: Python
            if "use python" in rule_text.lower():
                conversation_manager.add_rule("code_language", "Python")
            elif "use javascript" in rule_text.lower():
                conversation_manager.add_rule("code_language", "JavaScript")
            else:
                # Store generic rule
                conversation_manager.add_rule("custom_rule", rule_text)

        # Retrieve all current rules
        rules = conversation_manager.get_rules()
        rules_text = ""
        if rules:
            rules_text = "\n\nCurrent user rules/preferences:\n"
            for k, v in rules.items():
                rules_text += f"- {k}: {v}\n"

        # Search for similar previous conversations
        similar_qa = conversation_manager.search_similar(user_message)
        context_from_history = ""
        if similar_qa:
            context_from_history = "\n\nRelevant from previous conversations:\n"
            for qa in similar_qa[:2]:
                context_from_history += f"Q: {qa['question']}\nA: {qa['answer']}\n\n"


        # Modular system prompt construction
        capabilities = (
            "You are a versatile AI assistant with multiple capabilities:\n"
            "\n📧 Email Management: Send, read, and reply to emails via user's Gmail"
            "\n🚀 App Control: Launch applications on the user's computer"
            "\n💡 General Knowledge: Answer questions on technology, science, business, education, etc."
            "\n✍️ Writing & Editing: Create emails, essays, articles, scripts, marketing copy, resumes"
            "\n💻 Code Help: Write, debug, explain code; convert between languages"
            "\n📚 Learning Aid: Tutor in subjects (math, programming, languages); summarize complex material; create practice questions"
            "\n🎯 Brainstorming: Generate business ideas, project plans, outlines, workflows"
            "\n🌐 Translation: Translate between languages; rephrase content (simpler/professional)"
            "\n🔧 Problem Solving: Analyze situations, help with logic problems, suggest optimized solutions"
        )

        context_awareness = (
            "CONTEXT AWARENESS:\n"
            "You MUST understand and respond to relative references in conversations.\n"
            "1. 'from now...' / 'henceforth' / 'going forward':\n"
            "   - This establishes a NEW RULE or PREFERENCE for all future responses.\n"
            "   - You MUST acknowledge: '✅ Understood. From now on, I will [action]'\n"
            "   - You MUST apply this rule to ALL subsequent responses in the conversation.\n"
            "   - Example: 'From now on, use Python' → All code examples must use Python.\n"
            "2. 'in above case...' / 'in that case' / 'aforementioned':\n"
            "   - This refers to the MOST RECENT context/scenario just discussed.\n"
            "   - You MUST identify what 'above case' refers to.\n"
            "   - You MUST acknowledge: '✅ Regarding [the scenario], ...'\n"
            "   - Include the referenced context in your response.\n"
            "3. 'previously...' / 'earlier' / 'as discussed':\n"
            "   - This references something mentioned EARLIER in the conversation.\n"
            "   - You MUST recall that earlier discussion.\n"
            "   - You MUST acknowledge: '✅ Yes, you mentioned [topic]...'\n"
            "   - Build upon that previous context.\n"
            "4. When you see these references:\n"
            "   - ALWAYS acknowledge you understood the reference.\n"
            "   - ALWAYS apply the referenced context to your answer.\n"
            "   - If unclear, ask for clarification: 'Are you referring to [X]?'\n"
            "IMPORTANT: Context information may be appended below in [Context: ...] tags - USE IT!\n"
        )

        # Compose context and rules for the system prompt
        context_section = ""
        if context_from_history:
            context_section += f"\n[Context: Previous Q&A]\n{context_from_history}"
        if rules_text:
            context_section += f"\n[Context: User Rules]\n{rules_text}"

        system_prompt = f"{capabilities}\n\n{context_awareness}{context_section}\n\nBe friendly, concise, and helpful. Provide step-by-step guidance when needed. When performing actions (email/app), confirm what you did."

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": enhanced_message})
        conversation_manager.add_message("user", user_message)

        # Call OpenAI
        response = openai.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            functions=FUNCTIONS,
            function_call="auto",
            temperature=0.7
        )
        
        message = response.choices[0].message
        function_called = None
        
        # Handle function calling
        if message.function_call:
            function_name = message.function_call.name
            function_args = json.loads(message.function_call.arguments)
            
            # Call backend function
            function_result = call_backend_function(function_name, function_args)
            function_called = function_name
            
            # Store function call
            conversation_manager.add_message(
                "assistant",
                f"Called {function_name}",
                function_name=function_name
            )
            
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
            
            # Get final response
            second_response = openai.chat.completions.create(
                model=GPT_MODEL,
                messages=messages,
                temperature=0.7
            )
            
            final_message = second_response.choices[0].message.content
        else:
            final_message = message.content
        
        # Store assistant response
        conversation_manager.add_message("assistant", final_message)
        context_analyzer.add_message("assistant", final_message)
        
        # Store as Q&A pair for learning
        conversation_manager.add_qa_pair(
            question=user_message,
            answer=final_message,
            category="chat"
        )
        
        # Include reference authentication in response
        response_data = {
            'response': final_message,
            'function_called': function_called
        }
        
        # Add reference info if references were found
        if auth_result['found_references']:
            response_data['references_detected'] = {
                'types': auth_result['found_references'],
                'is_valid': auth_result['is_valid'],
                'issues': auth_result['issues']
            }
        
        return jsonify(response_data)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({
            'response': f'Sorry, I encountered an error: {str(e)}',
            'error': str(e)
        }), 500


@app.route('/new_conversation', methods=['POST'])
def new_conversation():
    """Start a new conversation"""
    conversation_manager.create_conversation()
    context_analyzer.clear_history()
    return jsonify({"status": "new conversation started"})


@app.route('/analyze_context', methods=['POST'])
def analyze_context():
    """Analyze contextual references in a given text
    
    Request body:
    {
        "text": "In the above case, from now on we should..."
    }
    
    Returns:
    {
        "text": "...",
        "found_references": ["above_case", "from_now"],
        "is_valid": true,
        "context": { ... }
    }
    """
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    
    auth_result = context_analyzer.authenticate_reference(text)
    
    return jsonify({
        'text': text,
        'found_references': auth_result['found_references'],
        'is_valid': auth_result['is_valid'],
        'issues': auth_result['issues'],
        'context_found': len(auth_result['context']) > 0,
        'context_details': auth_result['context']
    })


@app.route('/context_stats', methods=['GET'])
def context_stats():
    """Get conversation context statistics"""
    stats = context_analyzer.get_stats()
    
    return jsonify({
        'conversation_stats': stats,
        'total_messages': stats['total_messages'],
        'messages_with_references': stats['messages_with_references'],
        'reference_types_used': stats['reference_types_found']
    })


@app.route('/context_history', methods=['GET'])
def context_history():
    """Get full conversation context"""
    return jsonify({
        'context': context_analyzer.get_full_context(),
        'total_messages': len(context_analyzer.conversation_history)
    })


if __name__ == '__main__':
    print("=" * 60)
    print("Enhanced ChatGPT Server with Memory")
    print("=" * 60)
    print(f"Model: {GPT_MODEL}")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Django Q&A URL: {DJANGO_QA_URL}")
    print(f"OpenAI API Key: {'✓ Configured' if OPENAI_API_KEY else '✗ Not configured'}")
    print("=" * 60)
    print("\n🚀 Server running on http://localhost:5000")
    print("📱 Open chat_interface.html in your browser")
    print("\n💡 Features:")
    print("  - Conversation memory (saved to database)")
    print("  - Learning from previous Q&A")
    print("  - All ChatGPT capabilities enabled")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)

    # Provide credentials for frontend
    @app.route('/get_user_credentials', methods=['GET'])
    def get_user_credentials():
        import os
        return {
            "access_token": os.getenv('USER_ACCESS_TOKEN', ''),
            "refresh_token": os.getenv('USER_REFRESH_TOKEN', ''),
            "email": os.getenv('USER_EMAIL', '')
        }
