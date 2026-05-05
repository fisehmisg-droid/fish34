import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

# Ensure parent directory is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_supabase as db

def ingest_json(file_path: str, subject: str):
    print(f"Ingesting {file_path} for {subject}...")
    if not os.path.exists(file_path):
        print(f"File {file_path} not found.")
        return
        
    with open(file_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
        
    count = 0
    for q in questions:
        doc_ref = db.db.collection("real_exam_questions").document()
        doc_ref.set({
            "subject": subject,
            "question": q["question"],
            "options": q["options"],
            "answer": q["answer"],
            "explanation": q.get("explanation", ""),
            "topic": q.get("topic", "General"),
            "source_url": "https://kehulum.com/entrance-exam/natural-science/2017/physics-400",
            "created_at": db._now()
        })
        count += 1
        
    print(f"Successfully saved {count} questions for {subject} to Firestore.")

if __name__ == "__main__":
    ingest_json("scripts/physics_2017_20.json", "physics")
