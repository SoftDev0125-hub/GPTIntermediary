"""
ChatGPT Function Definitions
These function definitions can be used with ChatGPT's function calling API
"""

CHATGPT_FUNCTIONS = [
    {
        "name": "send_email",
        "description": "Send an email to a specified recipient via the user's Gmail account (uses the email account logged into ChatGPT)",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "The recipient's email address (e.g., user@gmail.com)"
                },
                "subject": {
                    "type": "string",
                    "description": "The subject line of the email"
                },
                "body": {
                    "type": "string",
                    "description": "The content/body of the email in plain text"
                },
                "html": {
                    "type": "string",
                    "description": "Optional HTML formatted version of the email body"
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_unread_emails",
        "description": "Retrieve and display unread emails from the user's Gmail inbox (uses the email account logged into ChatGPT)",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of unread emails to retrieve (default: 10)",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an email from a specific sender or message ID using the user's Gmail account (uses the email account logged into ChatGPT)",
        "parameters": {
            "type": "object",
            "properties": {
                "sender_email": {
                    "type": "string",
                    "description": "The email address of the sender to reply to (the system will find the most recent email from this sender)"
                },
                "message_id": {
                    "type": "string",
                    "description": "The specific message ID to reply to (optional, use if you have the exact message ID)"
                },
                "body": {
                    "type": "string",
                    "description": "The reply message content in plain text"
                },
                "html": {
                    "type": "string",
                    "description": "Optional HTML formatted version of the reply"
                }
            },
            "required": ["body"]
        }
    },
    {
        "name": "launch_app",
        "description": "Launch an application on the system",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The name of the application to launch (e.g., 'notepad', 'chrome', 'calculator', 'vscode', etc.)"
                },
                "args": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "Optional command-line arguments to pass to the application"
                }
            },
            "required": ["app_name"]
        }
    }
]


# Function mapping for internal use
FUNCTION_MAPPING = {
    "send_email": {
        "endpoint": "/api/email/send",
        "method": "POST"
    },
    "get_unread_emails": {
        "endpoint": "/api/email/unread",
        "method": "POST"
    },
    "reply_to_email": {
        "endpoint": "/api/email/reply",
        "method": "POST"
    },
    "launch_app": {
        "endpoint": "/api/app/launch",
        "method": "POST"
    }
}
