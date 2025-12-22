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
    },
    {
        "name": "create_word_document",
        "description": "Create a new Microsoft Word document with optional title and initial content",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path where the document should be saved (e.g., 'C:\\Users\\Username\\Documents\\document.docx')"
                },
                "content": {
                    "type": "string",
                    "description": "Optional initial content for the document"
                },
                "title": {
                    "type": "string",
                    "description": "Optional document title (will be added as a centered heading)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "open_word_document",
        "description": "Open an existing Microsoft Word document and retrieve its content",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document to open"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "add_text_to_word",
        "description": "Add text to a Microsoft Word document with optional formatting (bold, italic, underline, font, size, color)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "text": {
                    "type": "string",
                    "description": "Text to add to the document"
                },
                "bold": {
                    "type": "boolean",
                    "description": "Make the text bold (default: false)"
                },
                "italic": {
                    "type": "boolean",
                    "description": "Make the text italic (default: false)"
                },
                "underline": {
                    "type": "boolean",
                    "description": "Underline the text (default: false)"
                },
                "font_name": {
                    "type": "string",
                    "description": "Font name (e.g., 'Arial', 'Times New Roman', 'Calibri')"
                },
                "font_size": {
                    "type": "integer",
                    "description": "Font size in points (e.g., 12, 14, 16)"
                },
                "color": {
                    "type": "string",
                    "description": "Text color in hex format (e.g., '#FF0000' for red, '#0000FF' for blue)"
                }
            },
            "required": ["file_path", "text"]
        }
    },
    {
        "name": "format_word_paragraph",
        "description": "Format a paragraph in a Microsoft Word document (alignment, spacing, indentation)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "paragraph_index": {
                    "type": "integer",
                    "description": "Index of the paragraph to format (0-based, first paragraph is 0)"
                },
                "alignment": {
                    "type": "string",
                    "enum": ["left", "center", "right", "justify"],
                    "description": "Paragraph alignment"
                },
                "line_spacing": {
                    "type": "number",
                    "description": "Line spacing multiplier (e.g., 1.0 for single, 1.5 for 1.5x, 2.0 for double)"
                },
                "space_before": {
                    "type": "number",
                    "description": "Space before paragraph in points"
                },
                "space_after": {
                    "type": "number",
                    "description": "Space after paragraph in points"
                },
                "left_indent": {
                    "type": "number",
                    "description": "Left indent in inches"
                },
                "right_indent": {
                    "type": "number",
                    "description": "Right indent in inches"
                }
            },
            "required": ["file_path", "paragraph_index"]
        }
    },
    {
        "name": "add_heading_to_word",
        "description": "Add a heading to a Microsoft Word document",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "text": {
                    "type": "string",
                    "description": "Heading text"
                },
                "level": {
                    "type": "integer",
                    "description": "Heading level from 1 to 9 (1 is the largest, 9 is the smallest)",
                    "minimum": 1,
                    "maximum": 9
                }
            },
            "required": ["file_path", "text"]
        }
    },
    {
        "name": "add_list_to_word",
        "description": "Add a bulleted or numbered list to a Microsoft Word document",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "List of items to add to the list"
                },
                "numbered": {
                    "type": "boolean",
                    "description": "True for numbered list, False for bulleted list (default: false)"
                }
            },
            "required": ["file_path", "items"]
        }
    },
    {
        "name": "add_table_to_word",
        "description": "Add a table to a Microsoft Word document",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "rows": {
                    "type": "integer",
                    "description": "Number of rows in the table",
                    "minimum": 1
                },
                "cols": {
                    "type": "integer",
                    "description": "Number of columns in the table",
                    "minimum": 1
                },
                "data": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "description": "Optional 2D array of data to populate the table (rows x columns)"
                },
                "header_row": {
                    "type": "boolean",
                    "description": "Whether the first row should be formatted as a header (bold text) (default: false)"
                }
            },
            "required": ["file_path", "rows", "cols"]
        }
    },
    {
        "name": "find_replace_in_word",
        "description": "Find and replace text in a Microsoft Word document",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "find_text": {
                    "type": "string",
                    "description": "Text to find in the document"
                },
                "replace_text": {
                    "type": "string",
                    "description": "Text to replace the found text with"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Whether to replace all occurrences (true) or just the first one (false) (default: true)"
                }
            },
            "required": ["file_path", "find_text", "replace_text"]
        }
    },
    {
        "name": "set_word_page_setup",
        "description": "Set page setup options for a Microsoft Word document (margins, orientation, page size)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                },
                "margins": {
                    "type": "object",
                    "properties": {
                        "top": {
                            "type": "number",
                            "description": "Top margin in inches"
                        },
                        "bottom": {
                            "type": "number",
                            "description": "Bottom margin in inches"
                        },
                        "left": {
                            "type": "number",
                            "description": "Left margin in inches"
                        },
                        "right": {
                            "type": "number",
                            "description": "Right margin in inches"
                        }
                    },
                    "description": "Dictionary with margin values in inches"
                },
                "orientation": {
                    "type": "string",
                    "enum": ["portrait", "landscape"],
                    "description": "Page orientation"
                },
                "page_size": {
                    "type": "string",
                    "enum": ["Letter", "A4", "Legal", "A3", "A5"],
                    "description": "Page size"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "save_word_document",
        "description": "Save a Microsoft Word document (or save as a new file with a different path)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Current path to the document"
                },
                "new_path": {
                    "type": "string",
                    "description": "Optional new path to save the document as (for 'Save As' functionality)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "get_word_document_info",
        "description": "Get information about a Microsoft Word document (file size, paragraph count, table count, preview)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Word document"
                }
            },
            "required": ["file_path"]
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
    },
    "create_word_document": {
        "endpoint": "/api/word/create",
        "method": "POST"
    },
    "open_word_document": {
        "endpoint": "/api/word/open",
        "method": "POST"
    },
    "add_text_to_word": {
        "endpoint": "/api/word/add-text",
        "method": "POST"
    },
    "format_word_paragraph": {
        "endpoint": "/api/word/format-paragraph",
        "method": "POST"
    },
    "add_heading_to_word": {
        "endpoint": "/api/word/add-heading",
        "method": "POST"
    },
    "add_list_to_word": {
        "endpoint": "/api/word/add-list",
        "method": "POST"
    },
    "add_table_to_word": {
        "endpoint": "/api/word/add-table",
        "method": "POST"
    },
    "find_replace_in_word": {
        "endpoint": "/api/word/find-replace",
        "method": "POST"
    },
    "set_word_page_setup": {
        "endpoint": "/api/word/page-setup",
        "method": "POST"
    },
    "save_word_document": {
        "endpoint": "/api/word/save",
        "method": "POST"
    },
    "get_word_document_info": {
        "endpoint": "/api/word/info",
        "method": "POST"
    }
}
