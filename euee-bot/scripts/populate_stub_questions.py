import os
import sys
import json
import random

# Ensure parent directory is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_stub as db
from config import SUBJECTS

def ingest_json_to_stub(file_path: str, subject: str):
    """Ingest questions from a JSON file into the stub database"""
    print(f"Ingesting {file_path} for {subject} into stub database...")
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

def create_sample_questions_for_stub(subject: str, count: int = 10):
    """Create sample questions for subjects that don't have JSON files in stub database"""
    print(f"Creating {count} sample questions for {subject} in stub database...")
    
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
            },
            {
                "question": "What is the value of sin(30°)?",
                "options": {"A": "1/2", "B": "√3/2", "C": "√2/2", "D": "1"},
                "answer": "A",
                "explanation": "sin(30°) = 1/2. This is a standard trigonometric value.",
                "topic": "Trigonometry"
            },
            {
                "question": "What is the sum of angles in a triangle?",
                "options": {"A": "90°", "B": "180°", "C": "270°", "D": "360°"},
                "answer": "B",
                "explanation": "The sum of interior angles in any triangle is always 180°.",
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
            },
            {
                "question": "What is the speed of light in vacuum?",
                "options": {"A": "3×10⁸ m/s", "B": "3×10⁶ m/s", "C": "3×10¹⁰ m/s", "D": "3×10⁴ m/s"},
                "answer": "A",
                "explanation": "The speed of light in vacuum is approximately 3×10⁸ meters per second.",
                "topic": "Optics"
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
            },
            {
                "question": "What is the pH of pure water?",
                "options": {"A": "7", "B": "0", "C": "14", "D": "1"},
                "answer": "A",
                "explanation": "Pure water has a neutral pH of 7 at 25°C.",
                "topic": "Acids and Bases"
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
            },
            {
                "question": "What is the basic unit of life?",
                "options": {"A": "Tissue", "B": "Organ", "C": "Cell", "D": "Organism"},
                "answer": "C",
                "explanation": "The cell is the basic structural and functional unit of all living organisms.",
                "topic": "Cell Biology"
            }
        ],
        "english": [
            {
                "question": "Which is the correct spelling?",
                "options": {"A": "Necesary", "B": "Necessary", "C": "Neccessary", "D": "Nesessary"},
                "answer": "B",
                "explanation": "The correct spelling is 'necessary' with one 'c' and two 's's.",
                "topic": "Spelling"
            },
            {
                "question": "What is the past tense of 'go'?",
                "options": {"A": "Goed", "B": "Went", "C": "Gone", "D": "Going"},
                "answer": "B",
                "explanation": "The past tense of 'go' is 'went'. This is an irregular verb.",
                "topic": "Grammar"
            }
        ],
        "civics": [
            {
                "question": "What is democracy?",
                "options": {"A": "Rule by a king", "B": "Rule by the people", "C": "Rule by the military", "D": "Rule by the wealthy"},
                "answer": "B",
                "explanation": "Democracy is a system of government where power is vested in the people, who rule either directly or through elected representatives.",
                "topic": "Government Systems"
            }
        ],
        "history": [
            {
                "question": "When did World War II end?",
                "options": {"A": "1943", "B": "1944", "C": "1945", "D": "1946"},
                "answer": "C",
                "explanation": "World War II ended in 1945 with the surrender of Japan in September.",
                "topic": "World History"
            }
        ],
        "geography": [
            {
                "question": "What is the capital of Ethiopia?",
                "options": {"A": "Addis Ababa", "B": "Nairobi", "C": "Cairo", "D": "Johannesburg"},
                "answer": "A",
                "explanation": "Addis Ababa is the capital city of Ethiopia.",
                "topic": "Capital Cities"
            }
        ],
        "economics": [
            {
                "question": "What is inflation?",
                "options": {"A": "Decrease in prices", "B": "Increase in prices", "C": "Stable prices", "D": "Economic growth"},
                "answer": "B",
                "explanation": "Inflation is the rate at which the general level of prices for goods and services is rising, and subsequently, purchasing power is falling.",
                "topic": "Basic Concepts"
            }
        ],
        "agriculture": [
            {
                "question": "What is photosynthesis in plants?",
                "options": {"A": "Making food using sunlight", "B": "Taking in water", "C": "Growing roots", "D": "Producing flowers"},
                "answer": "A",
                "explanation": "Photosynthesis is the process by which plants use sunlight, water, and carbon dioxide to create their food.",
                "topic": "Plant Science"
            }
        ],
        "it": [
            {
                "question": "What does CPU stand for?",
                "options": {"A": "Central Processing Unit", "B": "Computer Personal Unit", "C": "Central Program Unit", "D": "Computer Processing Unit"},
                "answer": "A",
                "explanation": "CPU stands for Central Processing Unit, which is the main component of a computer that performs most of the processing.",
                "topic": "Computer Hardware"
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
    print("🎓 EUEE Abebe — Populate Stub Database with Questions")
    print("===================================================")
    
    total_questions = 0
    
    # Check for existing JSON files and ingest them
    json_files = {
        "physics": "scripts/physics_2017_20.json"
    }
    
    for subject, file_path in json_files.items():
        if os.path.exists(file_path):
            count = ingest_json_to_stub(file_path, subject)
            total_questions += count
        else:
            print(f"⚠️ No JSON file found for {subject}")
    
    # Create sample questions for all subjects that don't have JSON files
    for subject in SUBJECTS.keys():
        if subject not in json_files or not os.path.exists(json_files[subject]):
            count = create_sample_questions_for_stub(subject, count=5)
            total_questions += count
    
    print(f"\n🎉 Total questions added to stub database: {total_questions}")
    print("✅ All subjects processed!")
    
    # Test the question retrieval
    print("\n🧪 Testing question retrieval...")
    for subject in ["math", "physics", "chemistry"]:
        question = db.get_random_real_question(subject)
        if question:
            print(f"✅ Retrieved {subject} question: {question['question'][:50]}...")
        else:
            print(f"❌ No {subject} question found")

if __name__ == "__main__":
    main()
