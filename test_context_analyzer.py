"""
Context Analyzer Demo
Shows how the context analyzer handles relative references
"""

from services.context_analyzer import ContextAnalyzer


def demo_basic_references():
    """Demo 1: Basic reference detection and authentication"""
    print("\n" + "="*60)
    print("DEMO 1: Basic Reference Detection")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # Add conversation history
    analyzer.add_message("user", "I want to learn Python programming")
    analyzer.add_message("assistant", "Python is a great language for beginners. It has simple syntax...")
    analyzer.add_message("user", "What about async programming?")
    analyzer.add_message("assistant", "Async programming allows concurrent execution...")
    
    # Test reference authentication
    text = "In the above case, how do I implement this?"
    result = analyzer.authenticate_reference(text)
    
    print(f"\nText: {text}")
    print(f"References Found: {result['found_references']}")
    print(f"Valid: {result['is_valid']}")
    print(f"Issues: {result['issues']}")
    
    if result['context']:
        print(f"\nContext for 'above_case':")
        print(result['context'].get('above_case', 'None'))


def demo_from_now():
    """Demo 2: 'From now on' context establishment"""
    print("\n" + "="*60)
    print("DEMO 2: 'From Now On' Instructions")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # User establishes new behavior
    analyzer.add_message("user", "From now on, always format code with comments")
    analyzer.add_message("assistant", "✅ Understood. I'll add detailed comments to all code.")
    
    # Test detection
    text = "From now on, I prefer short concise answers"
    result = analyzer.authenticate_reference(text)
    
    print(f"\nText: {text}")
    print(f"References Found: {result['found_references']}")
    print(f"Valid: {result['is_valid']}")


def demo_previously():
    """Demo 3: 'Previously mentioned' context"""
    print("\n" + "="*60)
    print("DEMO 3: References to Previous Content")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # Build conversation
    analyzer.add_message("user", "I use Flask for web development")
    analyzer.add_message("assistant", "Flask is a lightweight web framework. You can...")
    analyzer.add_message("user", "What about database integration?")
    analyzer.add_message("assistant", "You can use SQLAlchemy with Flask...")
    analyzer.add_message("user", "Previously you mentioned ORM. Can you explain more?")
    
    # Get stats
    stats = analyzer.get_stats()
    
    print(f"\nConversation Statistics:")
    print(f"  Total Messages: {stats['total_messages']}")
    print(f"  Messages with References: {stats['messages_with_references']}")
    print(f"  Reference Types Used: {stats['reference_types_found']}")


def demo_context_resolution():
    """Demo 4: Context resolution in messages"""
    print("\n" + "="*60)
    print("DEMO 4: Context Resolution")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # Build context
    analyzer.add_message("user", "I'm building an e-commerce site")
    analyzer.add_message("assistant", "For e-commerce, consider these aspects...")
    
    # Message with reference
    original = "In the above case, how should I handle payments?"
    enhanced = analyzer.resolve_references_in_message(original)
    
    print(f"\nOriginal: {original}")
    print(f"\nEnhanced (with context):")
    print(enhanced)


def demo_full_context():
    """Demo 5: Full conversation context"""
    print("\n" + "="*60)
    print("DEMO 5: Full Conversation Context")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # Build a conversation
    messages = [
        ("user", "I want to learn machine learning"),
        ("assistant", "ML involves training models on data..."),
        ("user", "How does deep learning differ?"),
        ("assistant", "Deep learning uses neural networks..."),
        ("user", "From now on, explain with code examples"),
        ("assistant", "✅ I'll include code examples in all explanations"),
    ]
    
    for role, content in messages:
        analyzer.add_message(role, content)
    
    # Get full context
    context = analyzer.get_full_context()
    print("\nConversation Context:")
    print(context)


def demo_invalid_reference():
    """Demo 6: Handling invalid references"""
    print("\n" + "="*60)
    print("DEMO 6: Invalid Reference Handling")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    
    # Try to reference something that doesn't exist
    text = "Previously I mentioned X, but now I want Y"
    result = analyzer.authenticate_reference(text)
    
    print(f"\nText: {text}")
    print(f"References Found: {result['found_references']}")
    print(f"Valid: {result['is_valid']}")
    print(f"Issues: {result['issues']}")


def demo_system_prompt():
    """Demo 7: Context-aware system prompt"""
    print("\n" + "="*60)
    print("DEMO 7: System Prompt for Context Awareness")
    print("="*60)
    
    analyzer = ContextAnalyzer()
    system_prompt = analyzer.get_context_aware_system_prompt()
    
    print("\nSystem Prompt:")
    print(system_prompt)


def run_all_demos():
    """Run all demonstrations"""
    print("\n" + "="*80)
    print(" "*20 + "CONTEXT ANALYZER DEMONSTRATIONS")
    print("="*80)
    
    try:
        demo_basic_references()
        demo_from_now()
        demo_previously()
        demo_context_resolution()
        demo_full_context()
        demo_invalid_reference()
        demo_system_prompt()
        
        print("\n" + "="*80)
        print(" "*25 + "ALL DEMOS COMPLETED")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error running demos: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_demos()
