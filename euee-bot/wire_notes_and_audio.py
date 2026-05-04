# -*- coding: utf-8 -*-
"""
wire_notes_and_audio.py
========================
Does two jobs:
  1. Wires the PDFs inside notes/ into euee_notes/{subject}/notes.pdf
     so the bot serves them immediately as Study Notes.
  2. Generates an ElevenLabs audio lesson for every subject that has a
     notes.md, saving into audio_lessons/{subject}_lesson.mp3.

Run from the euee-bot directory:
    python wire_notes_and_audio.py
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# ---- Paths ------------------------------------------------------------------
BOT_ROOT      = Path(__file__).resolve().parent
NOTES_SRC_DIR = BOT_ROOT / "notes"          # PDFs you provided
EUEE_NOTES    = BOT_ROOT / "euee_notes"     # per-subject folders the bot reads
AUDIO_DIR     = BOT_ROOT / "audio_lessons"  # where *_lesson.mp3 files live
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# ---- Subject aliases (filename stem -> subject key) -------------------------
FILENAME_TO_SUBJECT = {
    "english":               "english",
    "english_notes":         "english",
    "maths":                 "math",
    "math":                  "math",
    "mathematics":           "math",
    "physics":               "physics",
    "physics_notes":         "physics",
    "chemistry":             "chemistry",
    "biology":               "biology",
    "civics":                "civics",
    "history":               "history",
    "geography":             "geography",
    "economics":             "economics",
    "agriculture":           "agriculture",
    "it":                    "it",
    "information_technology":"it",
}

SUBJECT_DISPLAY = {
    "math":        "Mathematics",
    "physics":     "Physics",
    "chemistry":   "Chemistry",
    "biology":     "Biology",
    "english":     "English",
    "civics":      "Civics & Ethics",
    "history":     "History",
    "geography":   "Geography",
    "economics":   "Economics",
    "agriculture": "Agriculture",
    "it":          "Information Technology",
}

# Alice - "Clear, Engaging Educator" -- works on free ElevenLabs tier
ELEVENLABS_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"
ELEVENLABS_MODEL    = "eleven_multilingual_v2"

# ---- Helpers ----------------------------------------------------------------

def _clean_for_audio(text: str, limit: int = 2500) -> str:
    """Strip markdown so ElevenLabs receives clean prose."""
    text = re.sub(r"(?m)^#+\s*", "", text)
    text = re.sub(r"\*+([^*]+)\*+", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"HOT TOPIC", "", text, flags=re.I)
    text = re.sub(r"[-*]\s+", "  ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _build_audio_script(subject: str, md_text: str) -> str:
    """Turn a notes.md into a warm 2-3 minute audio lesson script."""
    title = SUBJECT_DISPLAY.get(subject, subject.title())
    clean = _clean_for_audio(md_text, limit=2200)

    intro = (
        f"Hello everyone! Welcome to your {title} revision lesson by Abebe, "
        "your EUEE study partner. "
        "Grab your pen, sit comfortably, and let's make sure you walk into the "
        "exam hall feeling confident. "
    )
    outro = (
        " That is a wrap for today's revision. "
        f"The more you practise {title}, the easier it gets. "
        "You are capable, you are prepared, and Abebe believes in you. Good luck!"
    )
    return intro + clean + outro


def _generate_eleven_audio(text: str, output_path: Path) -> bool:
    """Call ElevenLabs TTS and save MP3. Returns True on success."""
    if not ELEVENLABS_API_KEY:
        print("  [WARN] ELEVENLABS_API_KEY not set -- skipping TTS.")
        return False

    try:
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        if hasattr(client, "text_to_speech"):
            stream = client.text_to_speech.convert(
                voice_id=ELEVENLABS_VOICE_ID,
                text=text,
                model_id=ELEVENLABS_MODEL,
                output_format="mp3_44100_128",
            )
            with open(output_path, "wb") as fh:
                for chunk in stream:
                    fh.write(chunk)
            return output_path.exists() and output_path.stat().st_size > 0

        # Older SDK fallback
        from elevenlabs import save
        audio = client.generate(
            text=text,
            voice=ELEVENLABS_VOICE_ID,
            model=ELEVENLABS_MODEL,
        )
        save(audio, str(output_path))
        return output_path.exists() and output_path.stat().st_size > 0

    except Exception as exc:
        print(f"  [ERROR] ElevenLabs: {exc}")
        return False


# ---- Step 1: Wire PDFs ------------------------------------------------------

def wire_pdfs() -> dict:
    """Copy PDFs from notes/ -> euee_notes/{subject}/notes.pdf."""
    wired = {}

    if not NOTES_SRC_DIR.exists():
        print(f"  [WARN] notes/ folder not found at {NOTES_SRC_DIR}. Skipping PDF wiring.")
        return wired

    for pdf_file in sorted(NOTES_SRC_DIR.glob("*.pdf")):
        stem    = pdf_file.stem.lower().replace(" ", "_")
        subject = FILENAME_TO_SUBJECT.get(stem)
        if not subject:
            print(f"  [SKIP] Cannot map '{pdf_file.name}' to a subject.")
            continue

        dest_folder = EUEE_NOTES / subject
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_pdf = dest_folder / "notes.pdf"

        shutil.copy2(pdf_file, dest_pdf)
        wired[subject] = dest_pdf
        print(f"  [OK]   {pdf_file.name}  -->  euee_notes/{subject}/notes.pdf")

    return wired


# ---- Step 2: Generate Audio -------------------------------------------------

def generate_all_audio(delay: float = 2.5) -> None:
    """Generate ElevenLabs audio for every subject that has a notes.md."""
    done   = []
    failed = []

    for subject_dir in sorted(EUEE_NOTES.iterdir()):
        if not subject_dir.is_dir():
            continue

        subject  = subject_dir.name
        md_path  = subject_dir / "notes.md"
        out_path = AUDIO_DIR / f"{subject}_lesson.mp3"

        if out_path.exists() and out_path.stat().st_size > 50_000:
            size_kb = out_path.stat().st_size // 1024
            print(f"  [-]    {subject}: already exists ({size_kb} KB) -- skipping.")
            done.append(subject)
            continue

        if not md_path.exists():
            print(f"  [SKIP] {subject}: no notes.md.")
            failed.append(subject)
            continue

        md_text = md_path.read_text(encoding="utf-8")
        script  = _build_audio_script(subject, md_text)
        print(f"  [...] {subject}: generating ({len(script)} chars) ...")

        ok = _generate_eleven_audio(script, out_path)
        if ok:
            size_kb = out_path.stat().st_size // 1024
            print(f"  [OK]  {subject}: {size_kb} KB --> {out_path.name}")
            done.append(subject)
        else:
            print(f"  [FAIL] {subject}: generation failed.")
            failed.append(subject)

        time.sleep(delay)

    print()
    print(f"Audio generation done.")
    print(f"  Success: {done}")
    print(f"  Failed:  {failed}")


# ---- Step 3: Summary --------------------------------------------------------

def show_summary() -> None:
    print()
    print("=" * 60)
    print("CONTENT SUMMARY")
    print("=" * 60)
    for subject_dir in sorted(EUEE_NOTES.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject  = subject_dir.name
        has_pdf  = (subject_dir / "notes.pdf").exists()
        has_md   = (subject_dir / "notes.md").exists()
        has_fc   = (subject_dir / "flashcards.json").exists()
        has_aud  = (AUDIO_DIR / f"{subject}_lesson.mp3").exists()

        flags = (
            "[PDF]" if has_pdf else "     ",
            "[MD] " if has_md  else "     ",
            "[FC] " if has_fc  else "     ",
            "[AUD]" if has_aud else "     ",
        )
        display = SUBJECT_DISPLAY.get(subject, subject.title())
        print(f"  {' '.join(flags)}   {display}")

    print()
    print("Legend: [PDF]=PDF notes  [MD]=Markdown  [FC]=Flashcards  [AUD]=Audio")
    print()


# ---- Main -------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  EUEE ABEBE -- Wire Notes & Generate Audio")
    print("=" * 60)
    print()

    print("STEP 1: Wiring PDFs from notes/ folder...")
    wired = wire_pdfs()
    if wired:
        print(f"  Wired {len(wired)} PDF(s): {list(wired.keys())}")
    else:
        print("  No new PDFs wired.")

    print()
    print("STEP 2: Generating ElevenLabs audio for all subjects...")
    generate_all_audio(delay=2.5)

    show_summary()
    print("All done! Restart the bot to pick up the new files.")
