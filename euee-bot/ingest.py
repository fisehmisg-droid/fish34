"""
ingest.py — Ethiopian Grade 12 Textbook PDF Ingestion
=====================================================
Run this script ONCE to load your textbooks into Firestore.
Usage:
    python ingest.py --pdf textbooks/grade12_math.pdf --subject math
    python ingest.py --pdf textbooks/grade12_physics.pdf --subject physics

Subjects: math, physics, chemistry, biology, english, civics, history, geography, economics
"""

import os
import sys
import argparse
import pdfplumber
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Fix Windows console emoji/Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

load_dotenv()

# ---------------------------------------------------------------------------
# Firebase init
# ---------------------------------------------------------------------------
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHUNK_SIZE = 800          # characters per chunk — good balance for Groq context
CHUNK_OVERLAP = 100       # characters of overlap between consecutive chunks

VALID_SUBJECTS = {
    "math": "Mathematics",
    "physics": "Physics",
    "chemistry": "Chemistry",
    "biology": "Biology",
    "english": "English",
    "civics": "Civics & Ethics",
    "history": "History",
    "geography": "Geography",
    "economics": "Economics",
    "agriculture": "Agriculture",
    "it": "Information Technology",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF using pdfplumber."""
    print(f"📖 Reading PDF: {pdf_path}")
    all_text = []
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                all_text.append(text.strip())
            # Progress indicator
            if (i + 1) % 10 == 0 or (i + 1) == total_pages:
                print(f"  ✅ Processed page {i + 1}/{total_pages}", end="\r")
    print()  # newline after progress
    return "\n\n".join(all_text)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        # Try to break at a paragraph or sentence boundary
        if end < text_len:
            # Look back up to 100 chars for a newline or period
            break_at = text.rfind("\n", start, end)
            if break_at == -1:
                break_at = text.rfind(". ", start, end)
            if break_at != -1 and break_at > start:
                end = break_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap  # slide window with overlap
    return chunks


def sanitize_chunk(chunk: str) -> str:
    """Remove excessively short or useless chunks."""
    # Remove chunks that are purely page numbers or whitespace
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    meaningful = [l for l in lines if len(l) > 5]
    return " ".join(meaningful)


def store_chunks(chunks: list[str], subject: str, subject_name: str, pdf_filename: str):
    """Store text chunks into Firestore in batches."""
    print(f"\n📦 Storing {len(chunks)} chunks for subject: {subject_name}")

    # Firestore batch writes (max 500 per batch)
    BATCH_LIMIT = 400
    total_stored = 0

    for batch_start in range(0, len(chunks), BATCH_LIMIT):
        batch = db.batch()
        batch_chunks = chunks[batch_start: batch_start + BATCH_LIMIT]

        for i, chunk in enumerate(batch_chunks):
            global_index = batch_start + i
            doc_ref = db.collection("textbook_chunks").document(
                f"{subject}_{global_index:05d}"
            )
            batch.set(doc_ref, {
                "subject": subject,
                "subject_name": subject_name,
                "source_file": pdf_filename,
                "chunk_index": global_index,
                "text": chunk,
                "char_count": len(chunk),
            })

        batch.commit()
        total_stored += len(batch_chunks)
        print(f"  ✅ Stored batch: {total_stored}/{len(chunks)} chunks", end="\r")

    print(f"\n🎉 Done! {total_stored} chunks stored for {subject_name}.")

    # Also update a metadata document for this subject
    db.collection("textbook_meta").document(subject).set({
        "subject": subject,
        "subject_name": subject_name,
        "source_file": pdf_filename,
        "total_chunks": total_stored,
        "ingested_at": firestore.SERVER_TIMESTAMP,
    })
    print(f"📝 Metadata saved for {subject}.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest Ethiopian Grade 12 textbook PDFs into Firestore"
    )
    parser.add_argument(
        "--pdf", required=True, help="Path to the PDF file (e.g. textbooks/math.pdf)"
    )
    parser.add_argument(
        "--subject",
        required=True,
        choices=list(VALID_SUBJECTS.keys()),
        help=f"Subject code. Options: {', '.join(VALID_SUBJECTS.keys())}",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Characters per chunk (default: {CHUNK_SIZE})",
    )
    args = parser.parse_args()

    pdf_path = args.pdf
    subject = args.subject
    subject_name = VALID_SUBJECTS[subject]

    # Validate file exists
    if not os.path.isfile(pdf_path):
        print(f"❌ File not found: {pdf_path}")
        sys.exit(1)

    print(f"\n🚀 EUEE Textbook Ingestion")
    print(f"   Subject  : {subject_name}")
    print(f"   PDF File : {pdf_path}")
    print(f"   Chunk size: {args.chunk_size} chars\n")

    # Check if subject already ingested
    meta = db.collection("textbook_meta").document(subject).get()
    if meta.exists:
        existing = meta.to_dict()
        confirm = input(
            f"⚠️  '{subject_name}' already has {existing.get('total_chunks', '?')} chunks. "
            f"Re-ingest and overwrite? (yes/no): "
        ).strip().lower()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

    # Run the pipeline
    raw_text = extract_text_from_pdf(pdf_path)
    print(f"\n📊 Total characters extracted: {len(raw_text):,}")

    chunks = chunk_text(raw_text, chunk_size=args.chunk_size)
    chunks = [sanitize_chunk(c) for c in chunks]
    chunks = [c for c in chunks if len(c) > 50]  # drop tiny chunks
    print(f"📊 Total chunks after processing: {len(chunks)}")

    store_chunks(chunks, subject, subject_name, os.path.basename(pdf_path))

    print(f"\n✅ Ingestion complete! {subject_name} is now available to Abebe the tutor.")
    print("Run 'python ingest.py --help' to ingest another subject.\n")


if __name__ == "__main__":
    main()
