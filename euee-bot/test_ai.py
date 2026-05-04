import ai
import asyncio

async def test():
    print("Testing Groq...")
    q = ai.generate_exam_question("math")
    print(f"Groq Result: {q.get('question')[:50]}...")
    
    print("\nTesting Anthropic...")
    note = ai.generate_confession_lesson("algebra", "en")
    print(f"Anthropic Result: {note[:50]}...")
    
    print("\nTesting Gemini...")
    summary = ai.eli10_explain("Complex integration is a method of evaluating integrals of functions of a complex variable.", "en")
    print(f"Gemini Result: {summary[:50]}...")

if __name__ == "__main__":
    asyncio.run(test())
