import asyncio
import sys
import ai
import db_supabase as db
from config import SUBJECTS

# Fix Windows console emoji/Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def populate_subject(subject: str, count: int = 10):
    print(f"🚀 Populating {subject} ({count} questions)...")
    success_count = 0
    for i in range(count):
        try:
            # Generate a new question using AI (Groq is fast)
            q = ai.generate_exam_question(subject, difficulty="medium", lang="en")
            # Check if it's the fallback question by matching the specific fallback explanation
            is_fallback = q.get("explanation") == "This is a safe fallback question used when live quiz generation is unavailable."
            
            if q and q.get("question") and not is_fallback:
                if db.add_real_question(subject, q):
                    success_count += 1
                    print(f"  [{i+1}/{count}] ✅ Added: {q['question'][:50]}...")
                else:
                    print(f"  [{i+1}/{count}] ❌ Database save failed.")
            else:
                print(f"  [{i+1}/{count}] ⚠️ AI rate limit hit or fallback triggered. Waiting a bit longer...")
                await asyncio.sleep(5) # Extra penalty delay if rate limited
        except Exception as e:
            print(f"  [{i+1}/{count}] ❌ Error: {e}")
        
        # Delay to stay under Groq 12k TPM (Tokens Per Minute) limit. 
        # Each request is ~600 tokens, so max 13 req/min = 1 req every 4.5 seconds
        await asyncio.sleep(4.5)
    
    print(f"🎉 Done with {subject}. Added {success_count} questions.\n")

async def main():
    print("🎓 EUEE Abebe — Model Exam Population Script")
    print("============================================")
    
    # Changed to 100 per subject as per production requirements.
    for subject in SUBJECTS.keys():
        await populate_subject(subject, count=100)

    print("✅ All subjects processed!")

if __name__ == "__main__":
    asyncio.run(main())
