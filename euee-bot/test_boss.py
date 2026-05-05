import asyncio
import ai
import db_supabase as db

async def test_generation():
    print("Testing generate_boss_fight_question...")
    try:
        question = ai.generate_boss_fight_question("Mathematics")
        print(f"Question generated: {question}")
    except Exception as e:
        print(f"Error generating question: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
