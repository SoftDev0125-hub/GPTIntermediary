"""
Serializers for Q&A Database API
"""

from rest_framework import serializers
from .models import Conversation, Message, QAPair, UserContext, SearchIndex


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for Message model"""

    class Meta:
        model = Message
        fields = [
            "id",
            "message_index",
            "role",
            "content",
            "function_name",
            "function_args",
            "function_result",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class QAPairSerializer(serializers.ModelSerializer):
    """Serializer for QAPair model"""

    class Meta:
        model = QAPair
        fields = [
            "id",
            "question",
            "answer",
            "context",
            "category",
            "tags",
            "confidence_score",
            "usefulness_rating",
            "times_referenced",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ConversationListSerializer(serializers.ModelSerializer):
    """Serializer for Conversation list view (summary)"""

    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_id",
            "conversation_type",
            "title",
            "user_email",
            "created_at",
            "updated_at",
            "message_count",
            "context_tags",
            "is_favorite",
            "is_archived",
        ]
        read_only_fields = [
            "id",
            "conversation_id",
            "created_at",
            "updated_at",
            "message_count",
        ]

    def get_message_count(self, obj):
        return obj.messages.count()


class ConversationDetailSerializer(serializers.ModelSerializer):
    """Serializer for Conversation detail view (with messages and Q&A pairs)"""

    messages = MessageSerializer(many=True, read_only=True)
    qa_pairs = QAPairSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_id",
            "conversation_type",
            "title",
            "description",
            "user_email",
            "created_at",
            "updated_at",
            "context_tags",
            "metadata",
            "message_count",
            "is_favorite",
            "is_archived",
            "relevance_score",
            "messages",
            "qa_pairs",
        ]
        read_only_fields = [
            "id",
            "conversation_id",
            "created_at",
            "updated_at",
            "message_count",
        ]


class ConversationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new conversations"""

    class Meta:
        model = Conversation
        fields = [
            "conversation_id",
            "conversation_type",
            "title",
            "description",
            "user_email",
            "context_tags",
        ]


class UserContextSerializer(serializers.ModelSerializer):
    """Serializer for UserContext model"""

    class Meta:
        model = UserContext
        fields = [
            "user_email",
            "preferred_conversation_type",
            "ai_model_preference",
            "frequently_used_functions",
            "common_tasks",
            "email_templates",
            "app_shortcuts",
            "recent_conversations",
            "learned_patterns",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class SearchIndexSerializer(serializers.ModelSerializer):
    """Serializer for SearchIndex model"""

    class Meta:
        model = SearchIndex
        fields = [
            "id",
            "search_type",
            "title",
            "content",
            "keywords",
            "user_email",
            "created_at",
            "relevance_score",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "relevance_score",
        ]


class ConversationSearchSerializer(serializers.Serializer):
    """Serializer for conversation search requests"""

    query = serializers.CharField(required=True, max_length=500)
    user_email = serializers.EmailField(required=False, allow_blank=True)
    conversation_type = serializers.CharField(required=False, allow_blank=True)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=100)
    offset = serializers.IntegerField(default=0, min_value=0)


class QAPairSearchSerializer(serializers.Serializer):
    """Serializer for Q&A pair search requests"""

    query = serializers.CharField(required=True, max_length=500)
    category = serializers.CharField(required=False, allow_blank=True)
    min_usefulness = serializers.IntegerField(default=0, min_value=0, max_value=5)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=100)
    offset = serializers.IntegerField(default=0, min_value=0)


class ConversationSummarySerializer(serializers.Serializer):
    """Serializer for conversation summary response"""

    conversation_id = serializers.CharField()
    title = serializers.CharField()
    conversation_type = serializers.CharField()
    message_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    key_topics = serializers.ListField(child=serializers.CharField())
    main_actions = serializers.ListField(child=serializers.CharField())
