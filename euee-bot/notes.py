"""
Study notes, flashcards, and audio helpers.

The goal of this module is to keep user-facing content available even when
Firestore chunks are missing or premium AI/TTS providers are unavailable.
It prefers local textbooks and generated assets, then uses cached AI output
where appropriate.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

try:
    import edge_tts
except ImportError:
    edge_tts = None

import ai
if os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes"):
    import db_stub as db
else:
    import db
from config import PREFER_ELEVENLABS_FOR_AUDIO, SUBJECTS

_BOT_ROOT = Path(__file__).resolve().parent
GENERATED_NOTES_DIR = _BOT_ROOT / "euee_notes"
TEXTBOOKS_DIR = _BOT_ROOT / "textbooks"
NOTES_DIR = _BOT_ROOT / "notes"
AUDIO_DIR = _BOT_ROOT / "audio_lessons"
MAX_EXTRACT_PAGES = 20

# Mapping from subject codes to note PDF filenames in notes/ folder
SUBJECT_NOTES_PDF_MAP = {
    "math": "Maths.pdf",
    "physics": "Physics.pdf",
    "chemistry": "Chemistry.pdf",
    "biology": "Biology.pdf",
    "english": "English.pdf",
    "civics": "Civics.pdf",
    "history": "History.pdf",
    "geography": "Geography.pdf",
    "economics": "Economics.pdf",
    "agriculture": "Agriculture.pdf",
    "it": "IT.pdf",
}

SUBJECT_FOLDER_MAP = {
    "math": "math",
    "physics": "physics",
    "chemistry": "chemistry",
    "biology": "biology",
    "english": "english",
    "civics": "civics",
    "history": "history",
    "geography": "geography",
    "economics": "economics",
    "agriculture": "agriculture",
    "it": "it",
}

def _is_placeholder_markdown(text: str) -> bool:
    """True if notes are only the generic starter (no textbook extraction yet)."""
    if not text or len(text.strip()) < 80:
        return True
    markers = (
        "Starter Revision Guide",
        "was not found in the project yet",
        "Place the Grade 12",
        "What to add next",
    )
    return any(marker in text for marker in markers)


SUBJECT_TEXTBOOK_KEYWORDS = {
    "math": ["math", "mathematics"],
    "physics": ["physics"],
    "chemistry": ["chemistry"],
    "biology": ["biology"],
    "english": ["english"],
    "civics": ["civics", "ethics"],
    "history": ["history"],
    "geography": ["geography"],
    "economics": ["economics", "economy"],
    "agriculture": ["agriculture", "agri"],
    "it": ["it", "ict", "information_technology", "information technology", "computer"],
}


def _subject_title(subject: str) -> str:
    return SUBJECTS.get(subject, subject.replace("_", " ").title())


def get_generated_notes_files(subject: str) -> dict:
    """Resolve generated notes paths for a subject."""
    candidates = []
    mapped = SUBJECT_FOLDER_MAP.get(subject, subject)
    candidates.append(GENERATED_NOTES_DIR / mapped)
    candidates.append(GENERATED_NOTES_DIR / subject)

    if GENERATED_NOTES_DIR.exists():
        for entry in GENERATED_NOTES_DIR.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name.lower()
            if subject.lower() in name or mapped.lower() in name:
                candidates.append(entry)

    seen = set()
    for folder in candidates:
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        pdf_path = folder / "notes.pdf"
        md_path = folder / "notes.md"
        flashcards_path = folder / "flashcards.json"
        if pdf_path.exists() or md_path.exists() or flashcards_path.exists():
            return {
                "pdf": pdf_path if pdf_path.exists() else None,
                "md": md_path if md_path.exists() else None,
                "flashcards": flashcards_path if flashcards_path.exists() else None,
                "folder": folder,
            }

    folder = GENERATED_NOTES_DIR / mapped
    return {"pdf": None, "md": None, "flashcards": None, "folder": folder}


def get_local_notes_pdf(subject: str) -> Path | None:
    """Look for a pre-made study notes PDF in the notes/ folder."""
    if not NOTES_DIR.exists():
        return None
    # Check the mapped filename first
    mapped = SUBJECT_NOTES_PDF_MAP.get(subject)
    if mapped:
        candidate = NOTES_DIR / mapped
        if candidate.exists():
            return candidate
    # Fallback: look for any PDF whose name contains the subject
    for pdf in NOTES_DIR.glob("*.pdf"):
        if subject.lower() in pdf.stem.lower():
            return pdf
    return None


def get_local_audio_file(subject: str) -> Path | None:
    path = AUDIO_DIR / f"{subject}_lesson.mp3"
    return path if path.exists() else None


def _extract_pdf_text(pdf_path: Path) -> str:
    import pdfplumber

    def looks_like_noise(page_text: str) -> bool:
        text = page_text.lower()
        noisy_markers = [
            "how to use this textbook",
            "table of contents",
            "acknowledgement",
            "copyright",
            "federal democratic republic",
        ]
        return any(marker in text for marker in noisy_markers)

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return ""

        start_page = min(6, max(total_pages - 1, 0))
        page_limit = total_pages if MAX_EXTRACT_PAGES is None else min(total_pages, MAX_EXTRACT_PAGES)
        if total_pages <= page_limit:
            page_indexes = list(range(start_page, total_pages))
        else:
            span = max(total_pages - start_page, 1)
            stride = max(span // page_limit, 1)
            page_indexes = list(range(start_page, total_pages, stride))[:page_limit]

        pages = []
        for index in page_indexes:
            text = (pdf.pages[index].extract_text() or "").strip()
            if not text or looks_like_noise(text):
                continue
            if len(text) >= 350 or re.search(r"(?im)\b(unit|chapter|example|exercise|theorem|definition)\b", text):
                pages.append(text)
        return "\n\n".join(pages)


def _find_subject_textbooks(subject: str) -> list[Path]:
    if not TEXTBOOKS_DIR.exists():
        return []

    keywords = SUBJECT_TEXTBOOK_KEYWORDS.get(subject, [subject])
    matches = []
    for path in TEXTBOOKS_DIR.rglob("*.pdf"):
        name = path.stem.lower()
        if any(keyword in name for keyword in keywords):
            matches.append(path)
    return sorted(matches)


def _split_into_units(text: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    unit_re = re.compile(r"(?i)^(chapter|unit)\s+(\d+)\s*[:.\-\s]*(.*)$")

    units = []
    current_title = "Core Concepts"
    current_body: list[str] = []

    for line in lines:
        match = unit_re.match(line)
        if match:
            if current_body:
                units.append((current_title, "\n".join(current_body)))
            number = match.group(2).strip()
            suffix = match.group(3).strip()
            current_title = f"{match.group(1).title()} {number}: {suffix}" if suffix else f"{match.group(1).title()} {number}"
            current_body = []
            continue
        current_body.append(line)

    if current_body:
        units.append((current_title, "\n".join(current_body)))

    if not units:
        chunk_size = 12_000
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        units = [(f"Unit {idx + 1}", chunk) for idx, chunk in enumerate(chunks)]

    return units


def _top_bullet_points(unit_text: str, limit: int = 12) -> list[str]:
    raw_sentences = re.split(r"(?<=[.!?])\s+", unit_text.replace("\n", " "))
    cleaned = []
    for sentence in raw_sentences:
        candidate = re.sub(r"\s+", " ", sentence).strip(" -\t")
        if 55 <= len(candidate) <= 260:
            cleaned.append(candidate)

    if not cleaned:
        return ["Read this unit carefully and connect every concept to a likely exam question."]

    scored = []
    for sentence in cleaned:
        words = re.findall(r"[A-Za-z0-9]+", sentence.lower())
        unique_ratio = len(set(words)) / max(len(words), 1)
        formula_bonus = 0.2 if re.search(r"[=+\-/*^]|%|\d", sentence) else 0
        score = unique_ratio + min(len(words), 32) / 32 + formula_bonus
        scored.append((score, sentence))
    scored.sort(key=lambda item: item[0], reverse=True)

    picked = []
    seen = set()
    for _, sentence in scored:
        key = sentence[:70].lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked


def _extract_formula_like_lines(unit_text: str, limit: int = 6) -> list[str]:
    formulas = []
    for line in unit_text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if re.search(r"[=+\-/*^]|ratio|theorem|law|principle|rule", candidate, re.I) and len(candidate) < 160:
            formulas.append(candidate)
        if len(formulas) >= limit:
            break
    return formulas


def _keyword_highlights(text: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    stop_words = {
        "this", "that", "with", "from", "have", "which", "were", "their", "there", "about",
        "chapter", "unit", "into", "than", "also", "such", "these", "those", "your", "what",
    }
    counts = Counter(word for word in words if word not in stop_words)
    return [word for word, _ in counts.most_common(limit)]


def _build_interactive_markdown(subject: str, textbook_text: str) -> str:
    units = _split_into_units(textbook_text)
    hot_topics = set(_keyword_highlights(textbook_text, limit=14))
    title = _subject_title(subject)

    lines = [
        f"# {title} Full EUEE Study Notes",
        "",
        "These notes are built from the local textbook files and arranged for quick revision.",
        "",
        "## How to use these notes",
        "- Read the summary first, then cover the bullets and explain the idea out loud.",
        "- Circle formulas, laws, or rules that appear in more than one chapter.",
        "- End each unit by solving one question without looking back at the notes.",
        "- Revisit weak units every evening instead of rereading your strongest ones.",
        "",
    ]

    for index, (unit_title, body) in enumerate(units, start=1):
        bullets = _top_bullet_points(body, limit=12)
        formulas = _extract_formula_like_lines(body, limit=7)
        clean_title = re.sub(r"\s+", " ", unit_title).strip()[:90]

        lines.append(f"## Unit {index}: {clean_title}")
        lines.append("### Main points")
        for item in bullets:
            hot = " HOT TOPIC" if any(keyword in item.lower() for keyword in hot_topics) else ""
            lines.append(f"- {item}{hot}")

        lines.append("### Key formulas and rules")
        if formulas:
            for formula in formulas:
                lines.append(f"- {formula}")
        else:
            lines.append("- Focus on definitions, worked examples, and cause-and-effect explanations.")

        lines.extend(
            [
                "### Revision check",
                "- Explain the unit to a friend in one minute.",
                "- Predict one exam question from this unit and answer it fully.",
                "- Identify the trap most likely to make you lose marks here.",
                "",
                "### Exam tips",
                "- Start with the easiest question from this unit and lock in safe marks first.",
                "- Underline command words before solving or writing.",
                "- Show clean steps in calculation and reasoning questions.",
                "- Leave a short final check for signs, labels, units, and missing words.",
                "",
            ]
        )

    lines.extend(
        [
            "## Final revision checklist",
            "- [ ] I can explain every unit without reading from the page.",
            "- [ ] I practiced mixed questions from more than one chapter.",
            "- [ ] I reviewed my weakest topics twice this week.",
        ]
    )
    return "\n".join(lines)


def _build_generic_starter_guide(subject: str) -> str:
    title = _subject_title(subject)
    return "\n".join(
        [
            f"# {title} Starter Revision Guide",
            "",
            f"This guide was prepared because a local textbook PDF for {title} was not found in the project yet.",
            "It is still designed to help a student revise with structure instead of guessing what to study.",
            "",
            "## First pass",
            f"- List the major Grade 12 {title} themes you expect to see in the exam.",
            "- Write one sentence for each theme explaining what it is really about.",
            "- Turn definitions into your own words before you try to memorize them.",
            "",
            "## Practice method",
            "- Mix recall, worked examples, and self-testing in the same study block.",
            "- When you miss a question, write why you missed it, not just the answer.",
            "- Revisit that same weakness within twenty-four hours.",
            "",
            "## Exam habits",
            "- Read carefully before you rush into an answer.",
            "- Protect easy marks first, then return to long or tricky items.",
            "- Keep a final minute for checking missing steps, labels, and logic.",
            "",
            "## What to add next",
            f"- Place the Grade 12 {title} PDF inside the textbooks folder.",
            "- Regenerate the notes to build a fuller subject pack with chapter detail.",
        ]
    )


def _save_pdf_from_markdown(markdown_text: str, folder: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    pdf_path = folder / "notes.pdf"
    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=1.7 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], textColor=colors.HexColor("#0B5ED7"))
    h2_style = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#198754"))
    h3_style = ParagraphStyle("h3", parent=styles["Heading3"], textColor=colors.HexColor("#7A4EBF"))
    normal_style = ParagraphStyle("normal", parent=styles["BodyText"], leading=14)
    hot_style = ParagraphStyle("hot", parent=normal_style, textColor=colors.HexColor("#B02A37"))

    story = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 0.14 * cm))
            continue

        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("# "):
            story.append(Paragraph(safe[2:], title_style))
        elif line.startswith("## "):
            story.append(Paragraph(safe[3:], h2_style))
        elif line.startswith("### "):
            story.append(Paragraph(safe[4:], h3_style))
        elif line.startswith("- "):
            style = hot_style if "HOT TOPIC" in line else normal_style
            story.append(Paragraph(f"• {safe[2:]}", style))
        else:
            story.append(Paragraph(safe, normal_style))

    document.build(story)
    return pdf_path


def _build_subject_text(subject: str) -> str:
    textbooks = _find_subject_textbooks(subject)
    extracted = []
    for book in textbooks:
        text = _extract_pdf_text(book)
        if text.strip():
            extracted.append(f"# Source: {book.name}\n\n{text}")
    return "\n\n".join(extracted)


def ensure_subject_notes_generated(subject: str, force_regenerate: bool = False) -> dict:
    """Ensure there is a persistent markdown file and PDF for the subject."""
    existing = get_generated_notes_files(subject)
    
    # Check if we already have non-placeholder notes
    md_path_existing = existing.get("md")
    current_md = ""
    if md_path_existing and md_path_existing.exists():
        current_md = md_path_existing.read_text(encoding="utf-8")
    
    placeholder = _is_placeholder_markdown(current_md)
    complete_files = bool(existing.get("pdf") and existing.get("md"))
    
    # If we have complete notes and they aren't placeholders, and we aren't forced, return immediately.
    # This avoids the extremely slow _build_subject_text step for large PDFs.
    if not force_regenerate and complete_files and not placeholder:
        return existing

    # Only if we need to regenerate do we look for textbooks
    textbook_text = _build_subject_text(subject)
    has_textbook = bool(textbook_text.strip())

    should_regenerate = (
        force_regenerate
        or not complete_files
        or (placeholder and has_textbook)
    )
    if not should_regenerate:
        return existing

    folder = existing.get("folder") or (GENERATED_NOTES_DIR / SUBJECT_FOLDER_MAP.get(subject, subject))
    folder.mkdir(parents=True, exist_ok=True)

    markdown = (
        _build_interactive_markdown(subject, textbook_text)
        if textbook_text
        else _build_generic_starter_guide(subject)
    )

    md_path = folder / "notes.md"
    md_path.write_text(markdown, encoding="utf-8")
    pdf_path = _save_pdf_from_markdown(markdown, folder)
    db.clear_subject_notes_cache(subject)
    return {
        "pdf": pdf_path,
        "md": md_path,
        "flashcards": existing.get("flashcards"),
        "folder": folder,
    }


def study_notes_document_caption(subject: str, lang: str = "en") -> str:
    """Honest caption for Telegram PDF delivery (textbook-backed vs starter roadmap)."""
    title = _subject_title(subject)
    textbooks = _find_subject_textbooks(subject)
    has_textbook = len(textbooks) > 0
    files = get_generated_notes_files(subject)
    md_path = files.get("md")
    sample = ""
    if md_path and md_path.exists():
        sample = md_path.read_text(encoding="utf-8")
    placeholder = _is_placeholder_markdown(sample)

    if lang == "am":
        if has_textbook and not placeholder:
            return f"{title} — ከትምህርት መጽሐፍ (PDF) የተገነቡ ሙሉ ማስታወሻዎች።"
        if has_textbook:
            return f"{title} — ፒዲኤፍ ተገኝቷል፤ ዝርዝር ማስታወሻ ከምንጩ ተዘጋጅቷል።"
        return (
            f"{title} — የመጀመሪያ መንገድ ማስታወሻ። ሙሉ ትምህርት ለማግኘት በሰርቨር textbooks "
            "ከቤት ውስጥ የ12ኛ ክፍል ፒዲኤፍ ያክሉ።"
        )

    if has_textbook and not placeholder:
        return (
            f"{title} — full revision notes extracted from textbook PDFs "
            "bundled with Abebe (EUEE-focused)."
        )
    if has_textbook:
        return (
            f"{title} — notes rebuilt from your textbook PDFs. "
            "Use Study Notes again if you just added new files."
        )
    return (
        f"{title} — starter roadmap until a Grade 12 PDF is added "
        "to the server textbooks folder for deep chapter notes."
    )


def audio_lesson_caption(lang: str = "en") -> str:
    if lang == "am":
        return "የትምህርት ኦዲዮ — ከዚህ ርእስ ምንጭ ከተገነበለ።"
    return "Lesson audio — narration from your subject material (TTS)."


def _load_generated_markdown(subject: str) -> str:
    files = ensure_subject_notes_generated(subject)
    md_path = files.get("md")
    if md_path and md_path.exists():
        return md_path.read_text(encoding="utf-8")
    return ""


def _get_source_material(subject: str, char_limit: int = 10_000) -> str:
    # 1. Check Firestore chunks first (fastest)
    chunks = db.get_chunks_for_subject(subject, limit=8)
    combined = "\n---\n".join(chunk for chunk in chunks if chunk)
    if combined.strip():
        return combined[:char_limit]

    # 2. Check already generated markdown (local, fast)
    # We use get_generated_notes_files instead of ensure_... to avoid the extraction loop
    existing = get_generated_notes_files(subject)
    md_path = existing.get("md")
    if md_path and md_path.exists():
        content = md_path.read_text(encoding="utf-8")
        if not _is_placeholder_markdown(content):
            return content[:char_limit]

    # 3. Last resort: extract from textbooks (SLOW)
    textbook_text = _build_subject_text(subject)
    if textbook_text.strip():
        return textbook_text[:char_limit]

    return _build_generic_starter_guide(subject)[:char_limit]


async def generate_study_notes(subject: str, lang: str = "en") -> str:
    cache_key = f"notes_{subject}_{lang}"
    cached = db.get_cached_content(cache_key)
    if cached and cached.get("content"):
        return cached["content"]

    files = await asyncio.to_thread(ensure_subject_notes_generated, subject)
    if files.get("md"):
        markdown = files["md"].read_text(encoding="utf-8")
        db.set_cached_content(cache_key, {"content": markdown})
        return markdown

    material = _get_source_material(subject)
    result = await ai.generate_notes_gemini(subject=subject, lang=lang, text=material)
    db.set_cached_content(cache_key, {"content": result})
    return result


def create_notes_file(subject: str, content: str) -> str:
    filename = f"{subject}_study_notes.txt"
    with open(filename, "w", encoding="utf-8") as file_handle:
        file_handle.write(f"=== EUEE ABEBE: {_subject_title(subject).upper()} STUDY NOTES ===\n\n")
        file_handle.write(content)
    return filename


def _clean_for_audio(text: str, limit: int = 1000) -> str:
    text = re.sub(r"(?m)^#+\s*", "", text)
    text = text.replace("HOT TOPIC", "")
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _build_audio_script_offline(subject: str, lang: str = "en") -> str:
    units = _split_into_units(_get_source_material(subject, char_limit=12_000))
    top_units = units[:5] if units else [("Core Concepts", _get_source_material(subject))]
    subject_name = _subject_title(subject)

    intro = (
        f"Hello, this is your {subject_name} revision lesson. "
        "We are going to move through the biggest ideas in a calm, exam-focused way. "
    )
    if lang == "am":
        intro = (
            f"ሰላም፣ ይህ የ{subject_name} አጭር የእድሳት ትምህርት ነው። "
            "ዋና ዋና ሀሳቦችን በቀላሉ እና ለፈተና ተገቢ በሆነ መንገድ እንመለከታለን። "
        )

    paragraphs = [intro]
    for title, body in top_units:
        bullets = _top_bullet_points(body, limit=3)
        formulas = _extract_formula_like_lines(body, limit=1)
        section = f"{title}. " + " ".join(bullets[:2])
        if formulas:
            section += f" Remember this rule: {formulas[0]}."
        paragraphs.append(section)

    close = (
        "Before you stop, pause the lesson and explain these ideas back in your own words. "
        "That is where real memory starts."
    )
    if lang == "am":
        close = (
            "ከመጨረሻው በፊት ቆም ብለህ እነዚህን ሀሳቦች በራስህ ቃላት አስረዳ። "
            "እውነተኛ ማስታወስ የሚጀምረው እዚያ ነው።"
        )
    paragraphs.append(close)
    return _clean_for_audio(" ".join(paragraphs), limit=1000)


def generate_audio_script(subject: str, lang: str = "en") -> str:
    cache_key = f"audio_script_{subject}_{lang}"
    cached = db.get_cached_content(cache_key)
    if cached and cached.get("content"):
        cached_text = cached["content"].strip()
        if len(cached_text) >= 120 and "temporarily offline" not in cached_text.lower():
            return cached_text

    material = _get_source_material(subject)
    if material:
        prompt = (
            f"Subject: {subject}\n"
            f"Language: {lang}\n"
            "Write a warm, conversational 2-3 minute audio lesson for a Grade 12 student.\n"
            f"Material:\n{material[:8_000]}"
        )
        result = ai._chat_gemini("Supportive audio lesson writer.", prompt)
        low = result.lower()
        if "temporarily offline" in low or len(result.strip()) < 120:
            result = _build_audio_script_offline(subject, lang)
    else:
        result = _build_audio_script_offline(subject, lang)

    db.set_cached_content(cache_key, {"content": result})
    return result


async def generate_real_audio(text: str, lang: str = "en", subject: str = None) -> str:
    """Uses ElevenLabs (if configured) or Edge-TTS to generate audio."""
    # Priority 0: Check for manually prepared premium audio
    if subject:
        manual_path = AUDIO_DIR / f"{subject}_lesson.mp3"
        if manual_path.exists() and manual_path.stat().st_size > 1000:
            return str(manual_path)

    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    output_file = Path(path)

    async def _edge_tts_save(path: Path) -> bool:
        if edge_tts is None:
            return False
        voice = "en-US-AriaNeural" if lang == "en" else "am-ET-MekdesNeural"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(path))
        return path.exists() and path.stat().st_size > 0

    try:
        if PREFER_ELEVENLABS_FOR_AUDIO:
            if ai.generate_audio_file(text, str(output_file), lang):
                return str(output_file)
            if await _edge_tts_save(output_file):
                return str(output_file)
        else:
            if await _edge_tts_save(output_file):
                return str(output_file)
            if ai.generate_audio_file(text, str(output_file), lang):
                return str(output_file)
    except Exception:
        pass

    output_file.unlink(missing_ok=True)
    raise RuntimeError("No text-to-speech provider produced audio.")


def _offline_flashcards(subject: str, count: int = 5) -> list[dict]:
    units = _split_into_units(_get_source_material(subject, char_limit=12_000))
    cards = []
    for title, body in units:
        bullets = _top_bullet_points(body, limit=3)
        if not bullets:
            continue
        cards.append(
            {
                "question": f"What is the main idea of {title} in {_subject_title(subject)}?",
                "answer": bullets[0],
            }
        )
        formulas = _extract_formula_like_lines(body, limit=1)
        if formulas:
            cards.append(
                {
                    "question": f"Which rule or formula from {title} should you remember first?",
                    "answer": formulas[0],
                }
            )
        if len(cards) >= count:
            break

    while len(cards) < count:
        cards.append(
            {
                "question": f"What should you do first when revising {_subject_title(subject)}?",
                "answer": "Start with the core idea, test yourself quickly, and review the trap that usually causes mistakes.",
            }
        )
    return cards[:count]


def _save_flashcards_file(subject: str, cards: list[dict]) -> None:
    files = get_generated_notes_files(subject)
    folder = files["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    flashcards_path = folder / "flashcards.json"
    flashcards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_flashcards(subject: str, count: int = 5, lang: str = "en") -> list[dict]:
    cache_key = f"flashcards_{subject}_{lang}_{count}"
    cached = db.get_cached_content(cache_key)
    if cached and cached.get("cards"):
        return cached["cards"]

    existing = get_generated_notes_files(subject).get("flashcards")
    if existing and existing.exists():
        cards = json.loads(existing.read_text(encoding="utf-8"))
        if cards:
            return cards[:count]

    material = _get_source_material(subject, char_limit=6_000)
    prompt = (
        "Create flashcards for Grade 12 EUEE revision.\n"
        f"Subject: {subject}\nLanguage: {lang}\nCount: {count}\n"
        "Format exactly as:\nQ1: ...\nA1: ...\nQ2: ...\nA2: ...\n"
        f"Material:\n{material}"
    )
    raw = ai._chat_groq("Flashcard generator.", prompt)
    cards = []
    current_question = ""
    for line in raw.strip().splitlines():
        if line.startswith("Q") and ":" in line:
            current_question = line.split(":", 1)[1].strip()
        elif line.startswith("A") and ":" in line and current_question:
            cards.append({"question": current_question, "answer": line.split(":", 1)[1].strip()})
            current_question = ""
        if len(cards) >= count:
            break

    if not cards:
        cards = _offline_flashcards(subject, count)

    db.set_cached_content(cache_key, {"cards": cards})
    _save_flashcards_file(subject, cards)
    return cards


def generate_mnemonic(topic: str, lang: str = "en") -> str:
    prompt = f"Topic: {topic}\nLanguage: {lang}\nCreate one memorable Ethiopian-style mnemonic."
    result = ai._chat_anthropic("Mnemonic writer.", prompt)
    if "temporarily offline" in result.lower():
        return f"Use the first letters of the key ideas in {topic} and turn them into one funny sentence you can repeat quickly."
    return result


def generate_exam_tips(subject: str, lang: str = "en") -> str:
    """Provides subject-specific exam strategies using the fast Gemini engine."""
    subject_name = SUBJECTS.get(subject, subject.capitalize())
    
    if lang == "am":
        system = "አንተ የኢትዮጵያ ዩኒቨርሲቲ መግቢያ ፈተና (EUEE) ኤክስፐርት ነህ።"
        prompt = (
            f"የትምህርት አይነት: {subject_name}\n"
            "ለዚህ ለ12ኛ ክፍል ትምህርት ጠቃሚ የEUEE ፈተና ምክሮችን፣ ስልቶችን እና የተለመዱ ስህተቶችን በአማርኛ ዘርዝር። "
            "ምክሮቹ ተግባራዊ እና ለኢትዮጵያ ተማሪዎች የሚጠቅሙ መሆን አለባቸው። "
            "ሁልጊዜ 'የፈተና ምክሮች' የሚለውን ቃል ተጠቀም። 'እምት' ወይም 'እምትን' የሚሉ ቃላትን በፍጹም አትጠቀም።"
        )
    else:
        system = "You are an expert EUEE exam coach."
        prompt = f"Subject: {subject_name}\nLanguage: {lang}\nGive practical, high-value EUEE exam tips and common pitfalls for this Grade 12 subject."
    
    return ai._chat_gemini(system, prompt)


def generate_chapter_summary(subject: str, chapter_number: int, lang: str = "en") -> str:
    units = _split_into_units(_get_source_material(subject, char_limit=16_000))
    if not units:
        return "No chapter material is ready yet for this subject."

    index = max(0, min(chapter_number - 1, len(units) - 1))
    title, body = units[index]
    bullets = _top_bullet_points(body, limit=5)
    formulas = _extract_formula_like_lines(body, limit=2)

    lines = [f"{title}", ""]
    lines.extend(f"- {bullet}" for bullet in bullets)
    if formulas:
        lines.append("")
        lines.append("Key rules:")
        lines.extend(f"- {formula}" for formula in formulas)
    return "\n".join(lines)
