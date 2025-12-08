"""
Django management utility for Q&A database operations
Provides commands for conversation analysis, Q&A extraction, and context learning
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Avg, Q
from django.utils import timezone
from core.models import Conversation, Message, QAPair, UserContext, SearchIndex
import re
from datetime import timedelta


class Command(BaseCommand):
    help = "Manage Q&A database - analyze conversations and extract Q&A pairs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--action",
            type=str,
            required=True,
            choices=[
                "extract_qa",
                "analyze_conversation",
                "learn_patterns",
                "cleanup_old",
                "generate_stats",
                "build_search_index",
                "update_context",
            ],
            help="Action to perform",
        )
        parser.add_argument(
            "--conversation-id",
            type=str,
            help="Conversation ID to process",
        )
        parser.add_argument(
            "--user-email",
            type=str,
            help="User email for filtering",
        )
        parser.add_argument(
            "--days-old",
            type=int,
            default=30,
            help="Number of days to consider as old",
        )
        parser.add_argument(
            "--min-rating",
            type=int,
            default=3,
            help="Minimum usefulness rating for stats",
        )

    def handle(self, *args, **options):
        action = options["action"]

        if action == "extract_qa":
            self.extract_qa_from_conversations(
                conversation_id=options.get("conversation_id"),
                user_email=options.get("user_email"),
            )
        elif action == "analyze_conversation":
            if not options.get("conversation_id"):
                raise CommandError(
                    "conversation-id argument required for analyze_conversation"
                )
            self.analyze_conversation(options["conversation_id"])
        elif action == "learn_patterns":
            self.learn_user_patterns(user_email=options.get("user_email"))
        elif action == "cleanup_old":
            self.cleanup_old_conversations(days=options["days_old"])
        elif action == "generate_stats":
            self.generate_statistics(user_email=options.get("user_email"))
        elif action == "build_search_index":
            self.build_search_index()
        elif action == "update_context":
            if not options.get("user_email"):
                raise CommandError("user-email argument required for update_context")
            self.update_user_context(options["user_email"])

    def extract_qa_from_conversations(self, conversation_id=None, user_email=None):
        """Extract Q&A pairs from conversation messages"""
        self.stdout.write(
            self.style.SUCCESS("Starting Q&A extraction from conversations...")
        )

        conversations = Conversation.objects.all()

        if conversation_id:
            conversations = conversations.filter(conversation_id=conversation_id)
        if user_email:
            conversations = conversations.filter(user_email=user_email)

        for conversation in conversations:
            messages = conversation.messages.all().order_by("message_index")

            if messages.count() < 2:
                continue

            # Look for user-assistant message pairs
            for i in range(len(list(messages)) - 1):
                msg_list = list(messages)
                user_msg = msg_list[i]
                assistant_msg = msg_list[i + 1]

                if (
                    user_msg.role == "user"
                    and assistant_msg.role == "assistant"
                    and not user_msg.function_name
                ):
                    # Check if Q&A pair already exists
                    existing = QAPair.objects.filter(
                        conversation=conversation,
                        question=user_msg.content[:100],  # First 100 chars
                    ).exists()

                    if not existing:
                        # Extract category from function calls if present
                        category = "general"
                        if assistant_msg.function_name:
                            category = self._categorize_function(
                                assistant_msg.function_name
                            )

                        QAPair.objects.create(
                            conversation=conversation,
                            question=user_msg.content,
                            answer=assistant_msg.content,
                            context=assistant_msg.function_result,
                            category=category,
                            tags=[category],
                            confidence_score=0.8,
                        )

                        self.stdout.write(
                            f"  Extracted Q&A pair from conversation {conversation.conversation_id}"
                        )

        self.stdout.write(
            self.style.SUCCESS("Q&A extraction completed successfully!")
        )

    def analyze_conversation(self, conversation_id):
        """Analyze a single conversation for insights"""
        self.stdout.write(self.style.SUCCESS(f"Analyzing conversation {conversation_id}..."))

        try:
            conversation = Conversation.objects.get(conversation_id=conversation_id)
        except Conversation.DoesNotExist:
            raise CommandError(f"Conversation {conversation_id} not found")

        messages = conversation.messages.all().order_by("message_index")
        qa_pairs = conversation.qa_pairs.all()

        # Analyze message types
        user_count = messages.filter(role="user").count()
        assistant_count = messages.filter(role="assistant").count()
        function_calls = messages.filter(function_name__isnull=False).count()

        # Extract topics from content
        topics = self._extract_topics(
            " ".join([m.content for m in messages[:10]])
        )

        analysis = {
            "conversation_id": conversation.conversation_id,
            "title": conversation.title,
            "type": conversation.conversation_type,
            "total_messages": messages.count(),
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "function_calls": function_calls,
            "qa_pairs_extracted": qa_pairs.count(),
            "detected_topics": topics,
            "avg_message_length": sum(len(m.content) for m in messages)
            / messages.count()
            if messages.exists()
            else 0,
            "created": conversation.created_at.isoformat(),
            "updated": conversation.updated_at.isoformat(),
        }

        self.stdout.write(self.style.SUCCESS("\nConversation Analysis:"))
        self.stdout.write(f"  Title: {analysis['title']}")
        self.stdout.write(f"  Type: {analysis['type']}")
        self.stdout.write(f"  Total Messages: {analysis['total_messages']}")
        self.stdout.write(f"  User Messages: {analysis['user_messages']}")
        self.stdout.write(f"  Assistant Messages: {analysis['assistant_messages']}")
        self.stdout.write(f"  Function Calls: {analysis['function_calls']}")
        self.stdout.write(f"  Q&A Pairs: {analysis['qa_pairs_extracted']}")
        self.stdout.write(f"  Topics: {', '.join(analysis['detected_topics'])}")

    def learn_user_patterns(self, user_email=None):
        """Learn patterns from user conversations"""
        self.stdout.write(self.style.SUCCESS("Learning user patterns..."))

        users = UserContext.objects.all()
        if user_email:
            users = users.filter(user_email=user_email)

        for user in users:
            # Get user's conversations
            conversations = Conversation.objects.filter(user_email=user.user_email)
            messages = Message.objects.filter(conversation__in=conversations)

            # Find most common functions
            function_counts = (
                messages.filter(function_name__isnull=False)
                .values("function_name")
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            functions = [
                item["function_name"]
                for item in function_counts[:5]
            ]

            # Find common conversation types
            type_counts = (
                conversations.values("conversation_type")
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            tasks = [
                item["conversation_type"]
                for item in type_counts[:5]
            ]

            # Update user context
            user.frequently_used_functions = functions
            user.common_tasks = tasks
            user.learned_patterns = {
                "preferred_function": functions[0] if functions else None,
                "common_conversation_type": tasks[0] if tasks else "chat",
                "total_conversations": conversations.count(),
                "total_messages": messages.count(),
            }
            user.save()

            self.stdout.write(
                f"  Updated patterns for {user.user_email}: {len(functions)} functions, {len(tasks)} tasks"
            )

        self.stdout.write(self.style.SUCCESS("Pattern learning completed!"))

    def cleanup_old_conversations(self, days=30):
        """Archive conversations older than specified days"""
        self.stdout.write(
            self.style.SUCCESS(f"Cleaning up conversations older than {days} days...")
        )

        cutoff_date = timezone.now() - timedelta(days=days)
        old_conversations = Conversation.objects.filter(
            updated_at__lt=cutoff_date, is_archived=False
        )

        count = old_conversations.count()
        old_conversations.update(is_archived=True)

        self.stdout.write(
            self.style.SUCCESS(f"Archived {count} conversations older than {days} days")
        )

    def generate_statistics(self, user_email=None):
        """Generate comprehensive statistics"""
        self.stdout.write(self.style.SUCCESS("Generating statistics..."))

        conversations = Conversation.objects.all()
        qa_pairs = QAPair.objects.all()

        if user_email:
            conversations = conversations.filter(user_email=user_email)
            qa_pairs = qa_pairs.filter(conversation__user_email=user_email)

        stats = {
            "total_conversations": conversations.count(),
            "total_messages": Message.objects.filter(
                conversation__in=conversations
            ).count(),
            "total_qa_pairs": qa_pairs.count(),
            "avg_conversation_length": conversations.aggregate(
                avg=Avg("message_count")
            )["avg"],
            "conversation_by_type": dict(
                conversations.values("conversation_type").annotate(count=Count("id")).values_list(
                    "conversation_type", "count"
                )
            ),
            "qa_quality": {
                "avg_usefulness_rating": qa_pairs.aggregate(
                    avg=Avg("usefulness_rating")
                )["avg"],
                "high_quality_pairs": qa_pairs.filter(usefulness_rating__gte=4).count(),
                "most_referenced": qa_pairs.order_by("-times_referenced").first().question[:50]
                if qa_pairs.exists()
                else "N/A",
            },
        }

        self.stdout.write(self.style.SUCCESS("\nStatistics:"))
        self.stdout.write(f"  Total Conversations: {stats['total_conversations']}")
        self.stdout.write(f"  Total Messages: {stats['total_messages']}")
        self.stdout.write(f"  Total Q&A Pairs: {stats['total_qa_pairs']}")
        self.stdout.write(
            f"  Avg Conversation Length: {stats['avg_conversation_length']:.1f} messages"
        )
        self.stdout.write(f"  By Type: {stats['conversation_by_type']}")
        self.stdout.write(
            f"  Avg Q&A Quality: {stats['qa_quality']['avg_usefulness_rating']:.2f}/5.0"
        )

    def build_search_index(self):
        """Build search index for conversations and Q&A pairs"""
        self.stdout.write(self.style.SUCCESS("Building search index..."))

        # Clear existing index
        SearchIndex.objects.all().delete()

        # Index conversations
        for conversation in Conversation.objects.all():
            SearchIndex.objects.create(
                search_type="conversation",
                reference_id=conversation.id,
                title=conversation.title,
                content=conversation.description or "",
                keywords=conversation.context_tags,
                user_email=conversation.user_email,
                relevance_score=conversation.relevance_score,
            )

        # Index Q&A pairs
        for qa_pair in QAPair.objects.all():
            SearchIndex.objects.create(
                search_type="qa",
                reference_id=qa_pair.id,
                title=qa_pair.question[:255],
                content=qa_pair.answer,
                keywords=qa_pair.tags,
                user_email=qa_pair.conversation.user_email,
                relevance_score=qa_pair.usefulness_rating / 5.0,
            )

        # Index messages
        for message in Message.objects.filter(role="assistant")[:1000]:  # Limit to recent
            SearchIndex.objects.create(
                search_type="message",
                reference_id=message.id,
                title=f"Message from {message.conversation.title}",
                content=message.content,
                keywords=[message.conversation.conversation_type],
                user_email=message.conversation.user_email,
                relevance_score=0.5,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Built search index: {SearchIndex.objects.count()} entries"
            )
        )

    def update_user_context(self, user_email):
        """Update user context with recent data"""
        self.stdout.write(self.style.SUCCESS(f"Updating context for {user_email}..."))

        user_context, created = UserContext.objects.get_or_create(
            user_email=user_email
        )

        # Get recent conversations
        recent = Conversation.objects.filter(user_email=user_email).order_by(
            "-updated_at"
        )[:20]
        user_context.recent_conversations = [
            c.conversation_id for c in recent
        ]

        # Get frequently used functions
        function_counts = (
            Message.objects.filter(conversation__user_email=user_email)
            .filter(function_name__isnull=False)
            .values("function_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )
        user_context.frequently_used_functions = [
            f["function_name"] for f in function_counts
        ]

        user_context.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated context: {len(user_context.recent_conversations)} recent conversations"
            )
        )

    def _categorize_function(self, function_name):
        """Categorize function by name"""
        categories = {
            "launch_app": "app_launch",
            "send_email": "email",
            "compose_email": "email",
            "search_emails": "email",
            "create_task": "task",
        }
        return categories.get(function_name, "general")

    def _extract_topics(self, text, limit=5):
        """Extract potential topics from text"""
        # Simple keyword extraction - can be enhanced with NLP
        keywords = [
            "email",
            "app",
            "task",
            "calendar",
            "meeting",
            "attachment",
            "draft",
            "send",
            "reply",
            "forward",
        ]
        found = [k for k in keywords if k.lower() in text.lower()]
        return found[:limit] if found else ["general"]
