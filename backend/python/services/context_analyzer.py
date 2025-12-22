"""
Context Analyzer - Handles contextual references and authentication of relative references
Parses references like "from now...", "in above case...", "previously...", etc.
"""

import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime


class ContextAnalyzer:
    """Analyzes conversation context and authenticates relative references"""
    
    # Patterns for contextual references
    REFERENCE_PATTERNS = {
        'from_now': r'\b(?:from\s+now|henceforth|going\s+forward|from\s+this\s+point)\b',
        'above_case': r'\b(?:in\s+(?:the\s+)?(?:above|previous|aforesaid|aforementioned)\s+case|in\s+that\s+case|in\s+the\s+above\s+mentioned|above\s+(?:situation|scenario|context))\b',
        'previously': r'\b(?:previously|before|as\s+mentioned|as\s+discussed|earlier|as\s+stated)\b',
        'henceforth': r'\b(?:henceforth|hereby|with\s+this|as\s+of\s+now)\b',
        'following': r'\b(?:in\s+the\s+following|below|next|as\s+follows|hereunder)\b',
        'context_ref': r'\b(?:in\s+(?:this|that|the)\s+(?:context|situation|case|scenario)|given\s+(?:the\s+)?(?:above|this))\b',
        'temporal_ref': r'\b(?:from\s+now\s+on|henceforth|going\s+forward|from\s+here\s+on|subsequently)\b',
    }
    
    def __init__(self, max_history: int = 50):
        """Initialize context analyzer
        
        Args:
            max_history: Maximum number of messages to keep in context
        """
        self.max_history = max_history
        self.conversation_history: List[Dict] = []
        self.context_markers: List[Dict] = []
        self.reference_map: Dict[str, any] = {}
    
    def add_message(self, role: str, content: str, metadata: Dict = None) -> None:
        """Add a message to conversation history with metadata
        
        Args:
            role: 'user' or 'assistant'
            content: Message content
            metadata: Additional metadata (timestamp, etc.)
        """
        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {},
            'references': self.extract_references(content),
            'reference_indices': self.find_referenced_messages(content)
        }
        self.conversation_history.append(message)
        
        # Keep history within bounds
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)
    
    def extract_references(self, text: str) -> List[str]:
        """Extract all contextual references from text
        
        Args:
            text: Text to analyze
            
        Returns:
            List of found reference types
        """
        references = []
        text_lower = text.lower()
        
        for ref_type, pattern in self.REFERENCE_PATTERNS.items():
            if re.search(pattern, text_lower, re.IGNORECASE):
                references.append(ref_type)
        
        return references
    
    def find_referenced_messages(self, text: str) -> Dict[str, List[int]]:
        """Find which messages are being referenced
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary mapping reference types to message indices
        """
        referenced_indices = {}
        
        references = self.extract_references(text)
        for ref_type in references:
            if ref_type == 'above_case':
                # Find the most recent complete message/case
                indices = self._get_above_case_indices()
                referenced_indices['above_case'] = indices
            
            elif ref_type == 'previously':
                # Find all previous messages
                indices = self._get_previous_indices()
                referenced_indices['previously'] = indices
            
            elif ref_type == 'following':
                # This refers to content that follows
                referenced_indices['following'] = ['pending']
            
            elif ref_type in ['from_now', 'henceforth', 'temporal_ref']:
                # These establish new context from this point forward
                referenced_indices[ref_type] = [len(self.conversation_history) - 1]
        
        return referenced_indices
    
    def _get_above_case_indices(self) -> List[int]:
        """Get indices of messages that constitute the 'above case'
        
        Usually the most recent exchange or context block
        """
        if len(self.conversation_history) < 2:
            return []
        
        # Find the most recent complete message/exchange
        # Look back through history for a coherent context
        indices = []
        
        # Get the last user message and preceding assistant message
        for i in range(len(self.conversation_history) - 1, -1, -1):
            msg = self.conversation_history[i]
            indices.insert(0, i)
            
            # Stop at 2 messages (one user, one assistant pair)
            if len(indices) >= 2:
                break
        
        return indices
    
    def _get_previous_indices(self) -> List[int]:
        """Get indices of all previous messages"""
        if len(self.conversation_history) == 0:
            return []
        return list(range(len(self.conversation_history) - 1))
    
    def get_context_for_reference(self, reference_type: str) -> str:
        """Get the actual context/content being referenced
        
        Args:
            reference_type: Type of reference ('above_case', 'previously', etc.)
            
        Returns:
            The referenced context as a string
        """
        context_parts = []
        
        if reference_type == 'above_case':
            indices = self._get_above_case_indices()
            for idx in indices:
                if 0 <= idx < len(self.conversation_history):
                    msg = self.conversation_history[idx]
                    context_parts.append(f"{msg['role'].title()}: {msg['content']}")
        
        elif reference_type == 'previously':
            for msg in self.conversation_history[:-1]:  # All except last
                context_parts.append(f"{msg['role'].title()}: {msg['content']}")
        
        elif reference_type in ['from_now', 'henceforth']:
            # Return current context as starting point
            if self.conversation_history:
                msg = self.conversation_history[-1]
                context_parts.append(f"From now on (starting with): {msg['content']}")
        
        return "\n\n".join(context_parts)
    
    def authenticate_reference(self, text: str) -> Dict:
        """Authenticate references in text - verify they point to valid context
        
        Args:
            text: Text containing potential references
            
        Returns:
            Dictionary with authentication results
        """
        references = self.extract_references(text)
        referenced_messages = self.find_referenced_messages(text)
        
        authentication = {
            'text': text,
            'found_references': references,
            'is_valid': True,
            'referenced_messages': referenced_messages,
            'context': {},
            'issues': []
        }
        
        # Check validity of each reference
        for ref_type, indices in referenced_messages.items():
            if indices == ['pending']:
                # Reference to future content
                authentication['context'][ref_type] = "Pending (refers to content that follows)"
            else:
                # Verify indices exist in history
                valid_indices = [i for i in indices if 0 <= i < len(self.conversation_history)]
                
                if not valid_indices and ref_type not in ['following']:
                    authentication['is_valid'] = False
                    authentication['issues'].append(
                        f"Reference '{ref_type}' points to no valid messages in history"
                    )
                else:
                    # Get the context
                    context_content = self.get_context_for_reference(ref_type)
                    authentication['context'][ref_type] = context_content
        
        return authentication
    
    def resolve_references_in_message(self, text: str) -> str:
        """Resolve references by including relevant context in the message
        
        Args:
            text: Original message with references
            
        Returns:
            Enhanced message with context included
        """
        auth = self.authenticate_reference(text)
        
        if not auth['found_references']:
            return text  # No references to resolve
        
        # Build an enhanced message with context
        enhanced_parts = [text]
        
        for ref_type, context in auth['context'].items():
            if context and context != "Pending (refers to content that follows)":
                enhanced_parts.append(f"\n[Context: {ref_type}]\n{context}")
        
        return "\n".join(enhanced_parts)
    
    def get_full_context(self) -> str:
        """Get full conversation context for system prompt
        
        Returns:
            Formatted conversation history
        """
        if not self.conversation_history:
            return "No conversation history yet."
        
        context_lines = ["Conversation History:"]
        for i, msg in enumerate(self.conversation_history[-10:], 1):  # Last 10 messages
            context_lines.append(f"\n{i}. {msg['role'].title()}: {msg['content']}")
            if msg['references']:
                context_lines.append(f"   [References: {', '.join(msg['references'])}]")
        
        return "\n".join(context_lines)
    
    def get_context_aware_system_prompt(self) -> str:
        """Get a context-aware system prompt that explains how to handle references
        
        Returns:
            Enhanced system prompt
        """
        return """You are a context-aware AI assistant that understands relative references.

When you see references like:
- "from now..." - Establishes new context from this point forward
- "in above case..." - Refers to the most recent context/case mentioned
- "previously..." - Refers to earlier parts of the conversation
- "as discussed..." - References previous discussion
- "going forward..." - Sets context for future instructions

You should:
1. Acknowledge which context is being referenced
2. Apply that context to your response
3. If a reference is unclear, ask for clarification
4. Remember established contexts and apply them to subsequent responses

Be precise about what context you're applying and why."""
    
    def create_context_aware_history(self) -> List[Dict]:
        """Create history with enhanced context information for OpenAI
        
        Returns:
            List of messages with context metadata
        """
        enhanced_history = []
        
        for msg in self.conversation_history:
            enhanced_msg = {
                'role': msg['role'],
                'content': msg['content']
            }
            
            # Add context information if there are references
            if msg['references']:
                # Append reference info to content for clarity
                ref_info = f"\n[Contains references to: {', '.join(msg['references'])}]"
                enhanced_msg['content'] = msg['content'] + ref_info
            
            enhanced_history.append(enhanced_msg)
        
        return enhanced_history
    
    def clear_history(self) -> None:
        """Clear conversation history"""
        self.conversation_history = []
        self.context_markers = []
        self.reference_map = {}
    
    def get_stats(self) -> Dict:
        """Get statistics about conversation and references
        
        Returns:
            Dictionary with conversation stats
        """
        total_messages = len(self.conversation_history)
        messages_with_refs = sum(1 for msg in self.conversation_history if msg['references'])
        
        ref_counts = {}
        for msg in self.conversation_history:
            for ref_type in msg['references']:
                ref_counts[ref_type] = ref_counts.get(ref_type, 0) + 1
        
        return {
            'total_messages': total_messages,
            'messages_with_references': messages_with_refs,
            'reference_types_found': ref_counts,
            'conversation_length': len("\n".join(msg['content'] for msg in self.conversation_history))
        }
