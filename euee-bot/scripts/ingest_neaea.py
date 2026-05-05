import os
import sys
import json
import requests
import time
from dotenv import load_dotenv

load_dotenv()

# Ensure parent directory is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_supabase as db
import ai

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

TARGET_PAGES = [
    {"url": "https://www.neaea.com/grade-12-english-unit-1-question-answers/", "subject": "english"},
    {"url": "https://www.neaea.com/grade-12-english-unit-2-health-question-answers/", "subject": "english"},
    {"url": "https://www.neaea.com/grade-12/biology/", "subject": "biology"},
    {"url": "https://www.neaea.com/grade-12/chemistry/", "subject": "chemistry"},
    {"url": "https://www.neaea.com/grade-12/grade-12-physics/", "subject": "physics"},
    {"url": "https://www.neaea.com/grade-12/civics-and-ethics/", "subject": "civics"},
    {"url": "https://www.neaea.com/grade-12/economics/", "subject": "economics"},
    {"url": "https://www.neaea.com/grade-12/grade-12-geography/", "subject": "geography"},
    {"url": "https://www.neaea.com/grade-12/grade-12-ict/", "subject": "it"},
]

def scrape_markdown(url: str):
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"url": url, "formats": ["markdown"]}
    try:
        response = requests.post("https://api.firecrawl.dev/v1/scrape", json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get("data", {}).get("markdown", "")
        print(f"Error scraping {url}: {response.status_code}")
    except Exception as e:
        print(f"Exception scraping {url}: {e}")
    return ""

def parse_questions_with_llm(markdown: str, subject: str):
    prompt = (
        f"Extract all multiple choice questions for the subject '{subject}' from this markdown text.\n"
        "Output ONLY a valid JSON array of objects, where each object has:\n"
        "- question (string)\n"
        "- options (object with keys A, B, C, D)\n"
        "- answer (string, one character A-D)\n"
        "- explanation (string)\n"
        "- topic (string)\n\n"
        f"Markdown:\n{markdown[:15000]}"
    )
    # Use Gemini for better extraction
    response = ai._chat_gemini("You are a data extraction assistant.", prompt)
    
    # Try to find JSON block if LLM added text
    if "```json" in response:
        response = response.split("```json")[1].split("```")[0].strip()
    elif "```" in response:
        response = response.split("```")[1].split("```")[0].strip()
        
    try:
        return json.loads(response)
    except Exception as e:
        print(f"Failed to parse LLM response as JSON: {e}\nResponse: {response[:200]}...")
        return []

def ingest():
    print("Starting ingestion from neaea.com...")
    for page in TARGET_PAGES:
        url = page["url"]
        subject = page["subject"]
        print(f"Processing {subject} from {url}...")
        
        md = scrape_markdown(url)
        if not md:
            continue
            
        questions = parse_questions_with_llm(md, subject)
        print(f"Extracted {len(questions)} questions.")
        
        count = 0
        for q in questions:
            # Basic validation
            if not q.get("question") or not q.get("answer"):
                continue
                
            doc_ref = db.db.collection("real_exam_questions").document()
            doc_ref.set({
                "subject": subject,
                "question": q["question"],
                "options": q.get("options", {}),
                "answer": q["answer"],
                "explanation": q.get("explanation", ""),
                "topic": q.get("topic", "General"),
                "source_url": url,
                "created_at": db._now()
            })
            count += 1
            
        print(f"Saved {count} questions for {subject}.")
        time.sleep(2) # Avoid rate limits

if __name__ == "__main__":
    ingest()
