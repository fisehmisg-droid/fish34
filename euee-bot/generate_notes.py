import os
import sys
import glob
import time
import asyncio
from pathlib import Path

# Paths anchored to this package so scripts work from any cwd
_ROOT = Path(__file__).resolve().parent
TEXTBOOKS_DIR = _ROOT / "textbooks"
OUTPUT_DIR = _ROOT / "euee_notes"

from config import SUBJECTS
from gemini_file_api import generate_notes_for_pdf
from notes import _save_pdf_from_markdown

# Map PDF filenames to subject codes
PDF_SUBJECT_MAP = {
    "math": "math",
    "physics": "physics",
    "chemistry": "chemistry",
    "biology": "biology",
    "english": "english",
    "history": "history",
    "geography": "geography",
    "economics": "economics",
    "agriculture": "agriculture",
    "it": "it",
}

def detect_subject(filename: str) -> str | None:
    fname_lower = filename.lower()
    for keyword, code in PDF_SUBJECT_MAP.items():
        if keyword in fname_lower:
            return code
    return None

async def process_subject(pdf_path: Path):
    subject = detect_subject(pdf_path.name)
    if not subject:
        print(f"⚠️ Could not detect subject for {pdf_path.name}, skipping.")
        return

    subject_name = SUBJECTS.get(subject, subject.title())
    subject_dir = OUTPUT_DIR / subject
    subject_dir.mkdir(parents=True, exist_ok=True)
    
    md_path = subject_dir / "notes.md"
    if md_path.exists():
        print(f"⏭️ Notes already exist for {subject_name}, skipping.")
        return

    print(f"\n[>] 📖 Processing: {pdf_path.name} ({subject_name})")
    
    try:
        # Use the new Gemini File API pipeline
        notes_content = await generate_notes_for_pdf(str(pdf_path), subject, lang="en")
        
        md_body = f"# {subject_name.upper()} STUDY NOTES\n\n{notes_content}"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_body)

        pdf_path = _save_pdf_from_markdown(md_body, subject_dir)
        print(f"✅ Successfully generated notes + PDF for {subject_name}! ({pdf_path.name})")
        
    except Exception as e:
        print(f"❌ Failed to generate notes for {subject_name}: {e}")

async def main():
    print("🚀 Starting Offline EUEE Notes Generation via Gemini File API")
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    pdfs = list(TEXTBOOKS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"📚 No PDFs found in {TEXTBOOKS_DIR}/ folder.")
        return
        
    print(f"📚 Found {len(pdfs)} textbooks to process.\n")
    
    for pdf_path in pdfs:
        await process_subject(pdf_path)

    print("\n🎉 ALL DONE! Check the euee_notes/ directory.")

if __name__ == "__main__":
    # Fix Windows console emoji/Unicode output
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    
    asyncio.run(main())
