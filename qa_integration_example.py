"""
Q&A Database Integration Example
Shows how to integrate the Q&A database with the existing chat server
"""

import requests
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
QA_API_BASE = "http://localhost:8000/api"
CONVERSATION_TYPE_MAPPING = {
    "email": "email",
    "app_launch": "app_launch",
    "task": "task",
    "word": "word",
    "general": "chat",
}


class QADatabaseClient:
    """Client for Q&A Database API"""

    def __init__(self, base_url: str = QA_API_BASE):
        self.base_url = base_url
        self.session = requests.Session()

    def create_conversation(
        self,
        title: str,
        user_email: str,
        conversation_type: str = "chat",
        description: str = None,
        tags: List[str] = None,
    ) -> Dict:
        """Create a new conversation"""
        data = {
            "conversation_id": str(uuid.uuid4()),
            "conversation_type": conversation_type,
            "title": title,
            "user_email": user_email,
            "description": description,
            "context_tags": tags or [],
        }

        response = self.session.post(
            f"{self.base_url}/conversations/", json=data
        )

        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise Exception(f"Failed to create conversation: {response.text}")

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        function_name: str = None,
        function_args: Dict = None,
        function_result: Dict = None,
    ) -> Dict:
        """Add a message to a conversation"""
        data = {
            "role": role,
            "content": content,
            "function_name": function_name,
            "function_args": function_args,
            "function_result": function_result,
        }

        response = self.session.post(
            f"{self.base_url}/conversations/{conversation_id}/add_message/",
            json=data,
        )

        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise Exception(f"Failed to add message: {response.text}")

    def add_qa_pair(
        self,
        conversation_id: int,
        question: str,
        answer: str,
        category: str = "general",
        tags: List[str] = None,
        rating: int = 3,
    ) -> Dict:
        """Add a Q&A pair to a conversation"""
        data = {
            "question": question,
            "answer": answer,
            "category": category,
            "tags": tags or [category],
            "usefulness_rating": rating,
            "confidence_score": 0.8,
        }

        response = self.session.post(
            f"{self.base_url}/conversations/{conversation_id}/add_qa_pair/",
            json=data,
        )

        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise Exception(f"Failed to add Q&A pair: {response.text}")

    def search_qa_pairs(
        self,
        query: str,
        category: str = None,
        min_usefulness: int = 0,
        limit: int = 10,
    ) -> List[Dict]:
        """Search for Q&A pairs"""
        data = {
            "query": query,
            "category": category,
            "min_usefulness": min_usefulness,
            "limit": limit,
        }

        response = self.session.post(
            f"{self.base_url}/qa-pairs/search/", json=data
        )

        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            return []

    def search_conversations(
        self,
        query: str,
        user_email: str = None,
        conversation_type: str = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Search for conversations"""
        data = {
            "query": query,
            "user_email": user_email,
            "conversation_type": conversation_type,
            "limit": limit,
        }

        response = self.session.post(
            f"{self.base_url}/conversations/search/", json=data
        )

        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            return []

    def get_user_context(self, user_email: str) -> Dict:
        """Get user context and preferences"""
        response = self.session.get(
            f"{self.base_url}/user-context/{user_email}/"
        )

        if response.status_code == 200:
            return response.json()
        else:
            return None

    def get_recent_qa_for_context(
        self, user_email: str, limit: int = 5
    ) -> str:
        """Get high-quality Q&A pairs for providing context to ChatGPT"""
        data = {
            "query": "*",  # Match all
            "min_usefulness": 4,
            "limit": limit,
        }

        response = self.session.post(
            f"{self.base_url}/qa-pairs/search/", json=data
        )

        if response.status_code == 200:
            qa_pairs = response.json().get("results", [])

            # Format as context for ChatGPT
            context_lines = []
            for qa in qa_pairs:
                context_lines.append(
                    f"Q: {qa['question'][:100]}\nA: {qa['answer'][:200]}"
                )

            return "\n\n".join(context_lines)
        else:
            return ""

    def rate_qa_pair(self, qa_pair_id: int, rating: int) -> Dict:
        """Rate a Q&A pair"""
        if not 0 <= rating <= 5:
            raise ValueError("Rating must be between 0 and 5")

        data = {"rating": rating}

        response = self.session.post(
            f"{self.base_url}/qa-pairs/{qa_pair_id}/rate/", json=data
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to rate Q&A pair: {response.text}")

    def get_user_stats(self, user_email: str) -> Dict:
        """Get statistics for a user"""
        response = self.session.get(
            f"{self.base_url}/conversations/stats/?user_email={user_email}"
        )

        if response.status_code == 200:
            return response.json()
        else:
            return None


# Integration with Chat Server Example
class ChatWithQADatabase:
    """Chat handler that integrates with Q&A database"""

    def __init__(self, user_email: str):
        self.user_email = user_email
        self.qa_client = QADatabaseClient()
        self.current_conversation = None
        self.current_conversation_id = None

    def start_conversation(self, title: str, conv_type: str = "chat"):
        """Start a new conversation session"""
        self.current_conversation = self.qa_client.create_conversation(
            title=title,
            user_email=self.user_email,
            conversation_type=conv_type,
            tags=self._get_context_tags(conv_type),
        )
        self.current_conversation_id = self.current_conversation["id"]
        print(f"Started conversation: {self.current_conversation['conversation_id']}")

    def _get_context_tags(self, conv_type: str) -> List[str]:
        """Get context tags based on conversation type"""
        tags_map = {
            "email": ["email", "compose"],
            "app_launch": ["app", "launch"],
            "task": ["task", "automation"],
            "word": ["word", "document", "office"],
            "chat": ["general", "chat"],
        }
        return tags_map.get(conv_type, ["general"])

    def get_context_for_question(self, question: str) -> str:
        """Get relevant context from past Q&A pairs"""
        print(f"Searching for context: {question}")

        # Search for relevant Q&A pairs
        qa_results = self.qa_client.search_qa_pairs(
            query=question, limit=3, min_usefulness=3
        )

        if not qa_results:
            print("No relevant past Q&A found")
            return ""

        context_lines = [
            "Based on past interactions:"
        ]

        for qa in qa_results:
            context_lines.append(
                f"\n- Q: {qa['question']}"
                f"\n  A: {qa['answer']}"
            )

        return "\n".join(context_lines)

    def save_exchange(
        self,
        user_question: str,
        assistant_answer: str,
        function_name: str = None,
        function_args: Dict = None,
        function_result: Dict = None,
        rating: int = 5,
    ):
        """Save user question and assistant answer"""
        if not self.current_conversation_id:
            raise Exception("No active conversation. Call start_conversation first.")

        # Save user message
        self.qa_client.add_message(
            self.current_conversation_id,
            role="user",
            content=user_question,
        )

        # Save assistant message
        self.qa_client.add_message(
            self.current_conversation_id,
            role="assistant",
            content=assistant_answer,
            function_name=function_name,
            function_args=function_args,
            function_result=function_result,
        )

        # Extract and save Q&A pair
        category = self._categorize_question(user_question)
        self.qa_client.add_qa_pair(
            self.current_conversation_id,
            question=user_question,
            answer=assistant_answer,
            category=category,
            rating=rating,
        )

        print(f"Saved exchange for: {user_question[:50]}...")

    def _categorize_question(self, question: str) -> str:
        """Categorize question based on keywords"""
        keywords = {
            "email": ["email", "send", "draft", "compose", "message"],
            "app": ["app", "launch", "open", "run", "start"],
            "task": ["task", "schedule", "remind", "meeting"],
        }

        question_lower = question.lower()
        for category, words in keywords.items():
            if any(word in question_lower for word in words):
                return category

        return "general"

    def end_conversation(self):
        """End the current conversation session"""
        print(f"Ended conversation: {self.current_conversation['conversation_id']}")
        self.current_conversation = None
        self.current_conversation_id = None


# Example Usage
def main():
    """Example usage of Q&A database integration"""

    print("=" * 60)
    print("Q&A Database Integration Example")
    print("=" * 60)

    user_email = "user@example.com"

    # Initialize chat handler
    chat = ChatWithQADatabase(user_email)

    # Start a conversation
    chat.start_conversation(
        title="Email Composition Session",
        conv_type="email"
    )

    # Example 1: Get context for a question
    print("\n1. Getting context for a new question...")
    context = chat.get_context_for_question("How to draft a professional email?")
    print(context)

    # Example 2: Save a user-assistant exchange
    print("\n2. Saving exchange to database...")
    chat.save_exchange(
        user_question="Draft an email to John about the project deadline",
        assistant_answer="Subject: Project Deadline\n\nDear John,\n\nI wanted to reach out regarding the project deadline...",
        function_name="compose_email",
        function_args={"recipient": "john@example.com"},
        function_result={"draft_id": "draft_123", "status": "saved"},
        rating=5
    )

    # Example 3: Save another exchange
    print("\n3. Saving another exchange...")
    chat.save_exchange(
        user_question="How do I format a meeting request?",
        assistant_answer="A professional meeting request should include:\n1. Clear subject line\n2. Proposed times\n3. Meeting duration\n4. Brief agenda",
        rating=4
    )

    # Example 4: Search past Q&A
    print("\n4. Searching past Q&A pairs...")
    results = chat.qa_client.search_qa_pairs(
        query="email format",
        min_usefulness=3,
        limit=5
    )
    for i, qa in enumerate(results, 1):
        print(f"  {i}. Q: {qa['question'][:60]}...")
        print(f"     Rating: {qa['usefulness_rating']}/5\n")

    # Example 5: Get user statistics
    print("\n5. Getting user statistics...")
    stats = chat.qa_client.get_user_stats(user_email)
    if stats:
        print(f"  Total conversations: {stats['total_conversations']}")
        print(f"  Total messages: {stats['total_messages']}")
        print(f"  Total Q&A pairs: {stats['total_qa_pairs']}")

    # Example 6: Get user context
    print("\n6. Getting user context...")
    context = chat.qa_client.get_user_context(user_email)
    if context:
        print(f"  Preferred model: {context['ai_model_preference']}")
        print(f"  Frequently used: {context['frequently_used_functions']}")

    # End conversation
    chat.end_conversation()

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure Django server is running:")
        print("  cd django_app && python manage.py runserver")
