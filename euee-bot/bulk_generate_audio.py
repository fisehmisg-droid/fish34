"""
Bulk-generate lesson MP3s under audio_lessons/ (same layout the bot expects).

Prefer: python bootstrap_assets.py --audio-only
"""
from __future__ import annotations

import asyncio
import sys

from bootstrap_assets import build_assets

if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(build_assets(notes=False, audio=True))
