"""
Pre-build local assets so Study Notes / Audio Lesson paths hit disk cache immediately.

Usage (from euee-bot folder):
  python bootstrap_assets.py              # notes PDF+MD for every subject + lesson MP3s
  python bootstrap_assets.py --notes-only # PDF+MD only (faster)
  python bootstrap_assets.py --audio-only # MP3s only (uses Edge TTS / ElevenLabs)

Requires the same .env / Firebase as the bot for Firestore audio_script cache invalidation paths.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys


def _utf8_stdio() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def build_assets(*, notes: bool, audio: bool) -> None:
    import notes as notes_mod
    from config import SUBJECTS

    subjects = list(SUBJECTS.keys())
    notes_mod.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    if notes:
        print("━━ Building notes (MD + PDF) from textbooks / starter guides ━━")
        for subject in subjects:
            print(f"  • {subject}...", flush=True)
            notes_mod.ensure_subject_notes_generated(subject)

    if audio:
        print("━━ Building lesson MP3s (saved next to bot for instant delivery) ━━")
        for subject in subjects:
            dest = notes_mod.AUDIO_DIR / f"{subject}_lesson.mp3"
            if dest.exists() and dest.stat().st_size > 50_000:
                print(f"  ⏭ {subject}: existing file ({dest.stat().st_size // 1024} KB)")
                continue
            print(f"  🔊 {subject}...", flush=True)
            try:
                script = notes_mod.generate_audio_script(subject, lang="en")
                tmp_path = await notes_mod.generate_real_audio(script, lang="en")
                shutil.move(tmp_path, dest)
                print(f"     → {dest.name}")
            except Exception as exc:
                print(f"     ✗ failed: {exc}")

    print("\nDone.")


def main() -> None:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="Pre-build Abebe notes + audio assets.")
    parser.add_argument("--notes-only", action="store_true", help="Only regenerate MD/PDF packs.")
    parser.add_argument("--audio-only", action="store_true", help="Only generate MP3 lesson files.")
    args = parser.parse_args()

    do_notes = not args.audio_only
    do_audio = not args.notes_only
    if args.notes_only and args.audio_only:
        parser.error("Pick at most one of --notes-only / --audio-only, or neither for full build.")

    asyncio.run(build_assets(notes=do_notes, audio=do_audio))


if __name__ == "__main__":
    main()
