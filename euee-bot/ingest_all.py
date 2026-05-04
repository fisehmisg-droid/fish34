"""
ingest_all.py — Batch ingest ALL Grade 12 textbooks from the textbooks/ folder
================================================================================
Run this ONCE:  python ingest_all.py
It finds all PDFs, maps them to subjects, and loads them into Firestore.
"""
import os
import sys

# Fix Windows console emoji/Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Map PDF filenames to subject codes
PDF_SUBJECT_MAP = {
    "Mathematics": "math",
    "Physics": "physics",
    "Chemistry": "chemistry",
    "Biology": "biology",
    "English": "english",
    "History": "history",
    "Geography": "geography",
    "Economics": "economics",
    "Agriculture": "agriculture",
    "IT": "it",
}

TEXTBOOK_DIR = os.path.join(os.path.dirname(__file__), "textbooks")


def detect_subject(filename: str) -> str | None:
    """Detect subject code from PDF filename."""
    fname_upper = filename.upper()
    for keyword, code in PDF_SUBJECT_MAP.items():
        if keyword.upper() in fname_upper:
            return code
    return None


def main():
    if not os.path.isdir(TEXTBOOK_DIR):
        print(f"❌ Textbooks folder not found: {TEXTBOOK_DIR}")
        sys.exit(1)

    pdfs = [f for f in os.listdir(TEXTBOOK_DIR) if f.lower().endswith(".pdf")]
    if not pdfs:
        print("❌ No PDF files found in textbooks/ folder.")
        sys.exit(1)

    print(f"\n📚 Found {len(pdfs)} PDFs in textbooks/\n")
    print("=" * 60)

    tasks = []
    for pdf in sorted(pdfs):
        subject = detect_subject(pdf)
        if subject:
            tasks.append((pdf, subject))
            print(f"  ✅ {pdf}  →  {subject}")
        else:
            print(f"  ⚠️  {pdf}  →  SKIPPED (unknown subject)")

    print("=" * 60)
    print(f"\n🚀 Will ingest {len(tasks)} textbooks.\n")

    for i, (pdf, subject) in enumerate(tasks, 1):
        pdf_path = os.path.join(TEXTBOOK_DIR, pdf)
        print(f"\n{'='*60}")
        print(f"📖 [{i}/{len(tasks)}] Ingesting: {pdf} → {subject}")
        print(f"{'='*60}")

        # Call ingest.py logic directly
        from ingest import extract_text_from_pdf, chunk_text, sanitize_chunk, store_chunks
        from config import SUBJECTS

        subject_name = SUBJECTS.get(subject, subject.title())
        raw_text = extract_text_from_pdf(pdf_path)
        print(f"   📊 Characters extracted: {len(raw_text):,}")

        chunks = chunk_text(raw_text)
        chunks = [sanitize_chunk(c) for c in chunks]
        chunks = [c for c in chunks if len(c) > 50]
        print(f"   📊 Chunks after processing: {len(chunks)}")

        store_chunks(chunks, subject, subject_name, pdf)

    print(f"\n{'='*60}")
    print(f"🎉 ALL DONE! {len(tasks)} textbooks ingested successfully!")
    print(f"{'='*60}")
    print("Abebe now has all the knowledge he needs. Run: python main.py\n")


if __name__ == "__main__":
    main()
