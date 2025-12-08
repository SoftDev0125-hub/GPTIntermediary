"""
Q&A Database Models for ChatGPT Backend
Stores conversation history and learned patterns
"""

from django.db import models
from django.utils import timezone
import json


class Conversation(models.Model):
    """
    Stores individual conversations with ChatGPT
    """
    CONVERSATION_TYPES = [
        ("chat", "Chat"),
        ("email", "Email Composition"),
        ("app_launch", "App Launch"),
        ("task", "Task Automation"),
        ("mixed", "Mixed Functions"),
    ]

    conversation_id = models.CharField(max_length=255, unique=True, db_index=True)
    conversation_type = models.CharField(
        max_length=20, choices=CONVERSATION_TYPES, default="chat"
    )
    user_email = models.EmailField(null=True, blank=True)
    title = models.CharField(max_length=255, default="Untitled Conversation")
    description = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Context and metadata
    context_tags = models.JSONField(default=list, blank=True)  # ["email", "draft", "urgent"]
    metadata = models.JSONField(default=dict, blank=True)  # Custom metadata
    
    # Engagement metrics
    message_count = models.IntegerField(default=0)
    is_archived = models.BooleanField(default=False, db_index=True)
    is_favorite = models.BooleanField(default=False)
    relevance_score = models.FloatField(default=0.0)  # For ranking similar conversations
    
    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user_email", "-created_at"]),
            models.Index(fields=["conversation_type", "-updated_at"]),
            models.Index(fields=["is_archived", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.conversation_type})"

    def to_dict(self):
        return {
            "conversation_id": self.conversation_id,
            "conversation_type": self.conversation_type,
            "title": self.title,
            "description": self.description,
            "user_email": self.user_email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message_count": self.message_count,
            "context_tags": self.context_tags,
            "is_favorite": self.is_favorite,
        }


class Message(models.Model):
    """
    Stores individual messages in a conversation
    """
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    
    # Function calling support
    function_name = models.CharField(max_length=100, null=True, blank=True)
    function_args = models.JSONField(null=True, blank=True)
    function_result = models.JSONField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    message_index = models.IntegerField()  # Position in conversation
    
    # Embedding for semantic search
    embedding = models.BinaryField(null=True, blank=True)
    embedding_model = models.CharField(max_length=50, default="ada-002", blank=True)
    
    class Meta:
        ordering = ["message_index"]
        unique_together = ["conversation", "message_index"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["role", "function_name"]),
        ]

    def __str__(self):
        return f"Message {self.message_index} - {self.role} ({self.conversation.id})"

    def to_dict(self):
        data = {
            "message_index": self.message_index,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }
        if self.function_name:
            data["function_name"] = self.function_name
            data["function_args"] = self.function_args
            data["function_result"] = self.function_result
        return data


class QAPair(models.Model):
    """
    Stores Q&A pairs extracted from conversations for learning
    """
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="qa_pairs"
    )
    
    question = models.TextField()
    answer = models.TextField()
    context = models.TextField(blank=True, null=True)  # Additional context
    
    # Classification
    category = models.CharField(max_length=100, blank=True)  # "email", "app_launch", etc.
    tags = models.JSONField(default=list, blank=True)  # Custom tags
    
    # Quality metrics
    confidence_score = models.FloatField(default=1.0)  # 0-1 confidence in this pair
    usefulness_rating = models.IntegerField(default=0)  # 0-5 user rating
    times_referenced = models.IntegerField(default=0)  # How often this Q&A was used
    
    # Temporal info
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Embeddings for semantic similarity
    question_embedding = models.BinaryField(null=True, blank=True)
    answer_embedding = models.BinaryField(null=True, blank=True)
    embedding_model = models.CharField(max_length=50, default="ada-002", blank=True)
    
    class Meta:
        ordering = ["-times_referenced", "-updated_at"]
        indexes = [
            models.Index(fields=["category", "-times_referenced"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["usefulness_rating", "-times_referenced"]),
        ]

    def __str__(self):
        return f"Q&A: {self.question[:50]}..."

    def to_dict(self):
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "context": self.context,
            "category": self.category,
            "tags": self.tags,
            "confidence_score": self.confidence_score,
            "usefulness_rating": self.usefulness_rating,
            "times_referenced": self.times_referenced,
            "created_at": self.created_at.isoformat(),
        }


class UserContext(models.Model):
    """
    Stores user-specific context and preferences for conversation enhancement
    """
    user_email = models.EmailField(unique=True, db_index=True)
    
    # User preferences
    preferred_conversation_type = models.CharField(max_length=20, default="mixed")
    ai_model_preference = models.CharField(
        max_length=50, default="gpt-4", blank=True
    )  # "gpt-3.5-turbo", "gpt-4", etc.
    
    # Learning data
    frequently_used_functions = models.JSONField(default=list)  # Most used app/functions
    common_tasks = models.JSONField(default=list)  # Frequently performed tasks
    email_templates = models.JSONField(default=dict)  # Stored email drafts/templates
    app_shortcuts = models.JSONField(default=dict)  # App names and shortcuts
    
    # Context memory
    recent_conversations = models.JSONField(default=list, blank=True)  # Last N conversation IDs
    learned_patterns = models.JSONField(default=dict, blank=True)  # Behavioral patterns
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "User Contexts"

    def __str__(self):
        return f"Context for {self.user_email}"

    def to_dict(self):
        return {
            "user_email": self.user_email,
            "preferred_conversation_type": self.preferred_conversation_type,
            "ai_model_preference": self.ai_model_preference,
            "frequently_used_functions": self.frequently_used_functions,
            "common_tasks": self.common_tasks,
            "recent_conversations": self.recent_conversations,
            "updated_at": self.updated_at.isoformat(),
        }


class SearchIndex(models.Model):
    """
    Index for efficient search across Q&A pairs and conversations
    """
    SEARCH_TYPES = [
        ("qa", "Q&A Pair"),
        ("message", "Message"),
        ("conversation", "Conversation"),
    ]

    search_type = models.CharField(max_length=20, choices=SEARCH_TYPES)
    reference_id = models.IntegerField()  # ID of the referenced object
    
    # Indexed fields
    title = models.CharField(max_length=255, db_index=True)
    content = models.TextField()
    keywords = models.JSONField(default=list)
    
    # Metadata
    user_email = models.EmailField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    relevance_score = models.FloatField(default=0.0)
    
    class Meta:
        indexes = [
            models.Index(fields=["search_type", "user_email", "-relevance_score"]),
            models.Index(fields=["-relevance_score", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.search_type.upper()}: {self.title[:50]}"
