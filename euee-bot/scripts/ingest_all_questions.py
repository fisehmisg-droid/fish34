import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

# Ensure parent directory is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_supabase as db
from config import SUBJECTS

def ingest_json_file(file_path: str, subject: str):
    """Ingest questions from a JSON file for a specific subject"""
    print(f"Ingesting {file_path} for {subject}...")
    if not os.path.exists(file_path):
        print(f"File {file_path} not found.")
        return 0
        
    with open(file_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
        
    count = 0
    for q in questions:
        try:
            if db.add_real_question(subject, q):
                count += 1
                print(f"  ✅ Added question {count}: {q['question'][:50]}...")
            else:
                print(f"  ❌ Failed to save question")
        except Exception as e:
            print(f"  ❌ Error saving question: {e}")
        
    print(f"Successfully saved {count} questions for {subject}.")
    return count

def create_sample_questions_for_subject(subject: str, count: int = 10):
    """Create sample questions for subjects that don't have JSON files"""
    print(f"Creating {count} sample questions for {subject}...")
    
    # Sample question templates for different subjects
    sample_questions = {
        "math": [
            {
                "question": "What is the derivative of f(x) = 3x² + 2x - 5?",
                "options": {"A": "6x + 2", "B": "6x - 2", "C": "3x + 2", "D": "6x² + 2"},
                "answer": "A",
                "explanation": "Using the power rule: d/dx(3x²) = 6x, d/dx(2x) = 2, d/dx(-5) = 0. So f'(x) = 6x + 2.",
                "topic": "Calculus"
            },
            {
                "question": "Solve for x: 2x + 7 = 15",
                "options": {"A": "x = 4", "B": "x = 8", "C": "x = 11", "D": "x = 3"},
                "answer": "A",
                "explanation": "Subtract 7 from both sides: 2x = 8. Divide by 2: x = 4.",
                "topic": "Algebra"
            },
            {
                "question": "What is the area of a circle with radius 5 units?",
                "options": {"A": "25π", "B": "10π", "C": "5π", "D": "50π"},
                "answer": "A",
                "explanation": "Area = πr² = π(5)² = 25π square units.",
                "topic": "Geometry"
            }
        ],
        "physics": [
            {
                "question": "What is the SI unit of force?",
                "options": {"A": "Joule", "B": "Newton", "C": "Watt", "D": "Pascal"},
                "answer": "B",
                "explanation": "The SI unit of force is the Newton (N), named after Sir Isaac Newton.",
                "topic": "Units and Measurements"
            },
            {
                "question": "An object moves with constant velocity. Which statement is true?",
                "options": {"A": "Net force is zero", "B": "Net force is non-zero", "C": "Acceleration is non-zero", "D": "Object is at rest"},
                "answer": "A",
                "explanation": "According to Newton's first law, an object moving with constant velocity has zero net force acting on it.",
                "topic": "Mechanics"
            }
        ],
        "chemistry": [
            {
                "question": "What is the chemical formula for water?",
                "options": {"A": "H2O", "B": "CO2", "C": "O2", "D": "H2O2"},
                "answer": "A",
                "explanation": "Water consists of two hydrogen atoms and one oxygen atom, giving the formula H2O.",
                "topic": "Chemical Formulas"
            },
            {
                "question": "Which element has the atomic number 6?",
                "options": {"A": "Oxygen", "B": "Nitrogen", "C": "Carbon", "D": "Hydrogen"},
                "answer": "C",
                "explanation": "Carbon has atomic number 6, meaning it has 6 protons in its nucleus.",
                "topic": "Periodic Table"
            }
        ],
        "biology": [
            {
                "question": "What is the powerhouse of the cell?",
                "options": {"A": "Nucleus", "B": "Mitochondria", "C": "Ribosome", "D": "Cell membrane"},
                "answer": "B",
                "explanation": "Mitochondria are known as the powerhouse of the cell because they produce ATP through cellular respiration.",
                "topic": "Cell Biology"
            },
            {
                "question": "Which process converts light energy into chemical energy?",
                "options": {"A": "Respiration", "B": "Photosynthesis", "C": "Transpiration", "D": "Fermentation"},
                "answer": "B",
                "explanation": "Photosynthesis is the process by which plants convert light energy into chemical energy stored in glucose.",
                "topic": "Plant Physiology"
            }
        ]
    }
    
    # Get sample questions for this subject or use generic ones
    subject_samples = sample_questions.get(subject, [
        {
            "question": f"What is the basic principle of {subject.title()}?",
            "options": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
            "answer": "A",
            "explanation": f"This is a sample question for {subject}.",
            "topic": "General"
        }
    ])
    
    # Create and ingest questions
    added_count = 0
    for i in range(min(count, len(subject_samples))):
        q = subject_samples[i % len(subject_samples)]
        try:
            if db.add_real_question(subject, q):
                added_count += 1
                print(f"  ✅ Added sample question {added_count}")
            else:
                print(f"  ❌ Failed to save sample question")
        except Exception as e:
            print(f"  ❌ Error saving sample question: {e}")
    
    print(f"Successfully created {added_count} sample questions for {subject}.")
    return added_count

def main():
    print("🎓 EUEE Abebe — Comprehensive Question Ingestion Script")
    print("=====================================================")
    
    total_questions = 0
    
    # Check for existing JSON files and ingest them
    json_files = {
        "physics": "scripts/physics_2017_20.json"
    }
    
    for subject, file_path in json_files.items():
        if os.path.exists(file_path):
            count = ingest_json_file(file_path, subject)
            total_questions += count
        else:
            print(f"⚠️ No JSON file found for {subject}")
    
    # Create sample questions for all subjects that don't have JSON files
    for subject in SUBJECTS.keys():
        if subject not in json_files or not os.path.exists(json_files[subject]):
            count = create_sample_questions_for_subject(subject, count=5)
            total_questions += count
    
    print(f"\n🎉 Total questions ingested: {total_questions}")
    print("✅ All subjects processed!")

if __name__ == "__main__":
    main()
