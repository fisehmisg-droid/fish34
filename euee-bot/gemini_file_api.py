"""
gemini_file_api.py — Gemini File API Pipeline for Large Textbook PDFs
======================================================================
Handles:
  1. PDF upload via Gemini File API (upload_file) — avoids inline TPM exhaustion.
  2. Async processing queue — one PDF processed at a time to stay within rate limits.
  3. Chunking strategy — splits text by unit/chapter when a file exceeds 200 000 tokens.
     A 65-second cooldown is inserted between chunk requests to reset the free-tier TPM.
  4. Exponential backoff — retries on HTTP 429 (ResourceExhausted) with jitter.
  5. Full-context instruction — the AI is explicitly told to scan EVERY section uploaded.
"""

import asyncio
import io
import logging
import math
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Approximate tokens per word for Ethiopian-curriculum PDFs (English + Amharic mix).
# 200 000 is the Gemini 1.5 Flash/Pro free-tier TPM window we must respect per call.
TOKENS_PER_WORD_EST   = 1.4
CHUNK_TOKEN_LIMIT     = 180_000          # stay safely below the 200 000 TPM ceiling
CHUNK_WORD_LIMIT      = int(CHUNK_TOKEN_LIMIT / TOKENS_PER_WORD_EST)  # ≈ 128 571 words

# How long to sleep between chunk requests to let the TPM window reset (free tier = 60 s).
CHUNK_COOLDOWN_SECS   = 65

# Exponential backoff settings for 429 / ResourceExhausted errors.
BACKOFF_BASE_SECS     = 5
BACKOFF_MAX_SECS      = 120
BACKOFF_MAX_RETRIES   = 6

# Gemini file-state poll interval while waiting for a newly uploaded file to be ACTIVE.
FILE_POLL_INTERVAL    = 4   # seconds
FILE_POLL_TIMEOUT     = 120 # seconds

# ---------------------------------------------------------------------------
# Gemini client initialisation
# ---------------------------------------------------------------------------

genai.configure(api_key=GEMINI_API_KEY)

_model: Optional[genai.GenerativeModel] = None

def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        _model = genai.GenerativeModel(model_name=GEMINI_MODEL)
    return _model


# ---------------------------------------------------------------------------
# Async processing queue (singleton)
# ---------------------------------------------------------------------------

_queue: asyncio.Queue = asyncio.Queue()
_worker_started: bool = False


async def _queue_worker():
    """
    Single-worker coroutine — processes one PDF upload job at a time.
    This prevents multiple concurrent File API uploads from hammering the free tier.
    """
    logger.info("[GeminiFileAPI] Queue worker started.")
    while True:
        coro, future = await _queue.get()
        try:
            result = await coro
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            _queue.task_done()


async def _ensure_worker():
    """Start the background queue worker if it hasn't been started yet."""
    global _worker_started
    if not _worker_started:
        asyncio.create_task(_queue_worker())
        _worker_started = True


async def enqueue(coro) -> any:
    """Push a coroutine onto the processing queue and await its result."""
    await _ensure_worker()
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    await _queue.put((coro, future))
    return await future


# ---------------------------------------------------------------------------
# Exponential backoff helper
# ---------------------------------------------------------------------------

async def _call_with_backoff(fn, *args, **kwargs):
    """
    Call *fn* (sync or async), retrying on ResourceExhausted (HTTP 429)
    with exponential backoff + full jitter.
    """
    import random

    for attempt in range(1, BACKOFF_MAX_RETRIES + 1):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)

        except ResourceExhausted as exc:
            if attempt == BACKOFF_MAX_RETRIES:
                logger.error(
                    "[GeminiFileAPI] 429 rate limit — all %d retries exhausted.",
                    BACKOFF_MAX_RETRIES,
                )
                raise

            # Calculate sleep with full jitter to avoid thundering-herd.
            cap   = min(BACKOFF_BASE_SECS * (2 ** (attempt - 1)), BACKOFF_MAX_SECS)
            sleep = random.uniform(0, cap)
            logger.warning(
                "[GeminiFileAPI] 429 ResourceExhausted on attempt %d/%d — "
                "sleeping %.1f s before retry. (%s)",
                attempt, BACKOFF_MAX_RETRIES, sleep, exc
            )
            await asyncio.sleep(sleep)

        except Exception:
            raise


# ---------------------------------------------------------------------------
# File API helpers
# ---------------------------------------------------------------------------

def _upload_pdf_bytes(pdf_bytes: bytes, display_name: str) -> genai.types.File:
    """
    Upload raw PDF bytes to the Gemini File API.
    Returns the File object (state may still be PROCESSING on return).
    """
    file_obj = io.BytesIO(pdf_bytes)
    uploaded = genai.upload_file(
        path=file_obj,
        display_name=display_name,
        mime_type="application/pdf",
    )
    logger.info("[GeminiFileAPI] Uploaded '%s' → uri=%s", display_name, uploaded.uri)
    return uploaded


def _upload_pdf_path(pdf_path: str | Path) -> genai.types.File:
    """Upload a PDF from the local filesystem."""
    pdf_path = Path(pdf_path)
    uploaded = genai.upload_file(
        path=str(pdf_path),
        display_name=pdf_path.name,
        mime_type="application/pdf",
    )
    logger.info("[GeminiFileAPI] Uploaded '%s' → uri=%s", pdf_path.name, uploaded.uri)
    return uploaded


async def _wait_for_file_active(file_obj: genai.types.File) -> genai.types.File:
    """
    Poll until the uploaded file transitions from PROCESSING → ACTIVE.
    Raises TimeoutError if it takes longer than FILE_POLL_TIMEOUT seconds.
    """
    deadline = time.time() + FILE_POLL_TIMEOUT
    while True:
        # FIX: Run sync genai.get_file in a thread so the event loop never blocks.
        current = await asyncio.to_thread(genai.get_file, file_obj.name)
        state   = current.state.name if hasattr(current.state, "name") else str(current.state)

        if state == "ACTIVE":
            logger.info("[GeminiFileAPI] File '%s' is ACTIVE.", file_obj.name)
            return current

        if state == "FAILED":
            raise RuntimeError(
                f"Gemini File API processing failed for '{file_obj.name}'."
            )

        if time.time() > deadline:
            raise TimeoutError(
                f"File '{file_obj.name}' did not become ACTIVE within "
                f"{FILE_POLL_TIMEOUT} seconds."
            )

        logger.debug(
            "[GeminiFileAPI] File '%s' state=%s — polling again in %ds.",
            file_obj.name, state, FILE_POLL_INTERVAL
        )
        await asyncio.sleep(FILE_POLL_INTERVAL)


def _delete_file_safe(file_obj: genai.types.File):
    """Delete an uploaded file, ignoring errors (best-effort cleanup)."""
    try:
        genai.delete_file(file_obj.name)
        logger.info("[GeminiFileAPI] Deleted remote file '%s'.", file_obj.name)
    except Exception as exc:
        logger.warning(
            "[GeminiFileAPI] Could not delete remote file '%s': %s",
            file_obj.name, exc
        )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_FULL_FILE_PROMPT = """You are Dr. Abebe, a Senior Curriculum Expert and EUEE Specialist.
You have been given the COMPLETE textbook as an uploaded file above.

CRITICAL INSTRUCTION: Scan the ENTIRE uploaded document — every unit, every chapter,
every sub-section, every example, every exercise. Do NOT skip or summarise skipped content.

Generate comprehensive, exam-ready study notes following this exact structure:

## [Unit/Chapter Number]: [Full Title]

### Summary
[2–3 sentences capturing the core idea]

### Exam Logic
[Why this concept is tested in EUEE; what examiners are looking for]

### Key Concepts & Definitions
[Bullet list — precise definitions with examples]

### Formulas / Laws / Rules
[Table: Name | Expression | When to Apply]

### Common Pitfalls
[The Trap | The Correction — top 3 student errors]

### The Link
[How this unit connects to the previous one and the next]

### Practice Questions (EUEE-Standard)
[3 tiered MCQ questions with answers and explanations]

---
Repeat the structure above for EVERY unit found in the uploaded document.

Subject: {subject}
Language: {lang}
"""

_CHUNK_PROMPT = """You are Dr. Abebe, a Senior Curriculum Expert and EUEE Specialist.
The text below is SECTION {chunk_idx} of {total_chunks} from the Grade 12 {subject} textbook.

CRITICAL INSTRUCTION: Process this section completely. Cover every concept, every definition,
every formula, and every worked example present in this section.

Generate exam-ready study notes for ALL content in this section:

## [Unit/Chapter Number]: [Full Title]

### Summary
### Exam Logic
### Key Concepts & Definitions
### Formulas / Laws / Rules
### Common Pitfalls
### The Link
### Practice Questions (EUEE-Standard)

---

TEXTBOOK SECTION {chunk_idx}/{total_chunks}:
{chunk_text}

Subject: {subject}
Language: {lang}
"""


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

async def _generate_from_file(
    pdf_path: str | Path,
    subject: str,
    lang: str = "en",
) -> str:
    """
    Upload the whole PDF once and generate notes in a single Gemini call.
    Best path — use when the textbook is under ~200 000 tokens.
    """
    # FIX: Wrap sync File API calls in threads so the event loop never blocks.
    uploaded = await asyncio.to_thread(_upload_pdf_path, pdf_path)
    active   = await _wait_for_file_active(uploaded)

    prompt = _FULL_FILE_PROMPT.format(subject=subject, lang=lang)

    try:
        model    = _get_model()
        response = await _call_with_backoff(
            model.generate_content,
            [active, prompt],
        )
        return response.text.strip()
    finally:
        await asyncio.to_thread(_delete_file_safe, active)


async def _generate_from_chunks(
    text_chunks: list[str],
    subject: str,
    lang: str = "en",
) -> str:
    """
    Process text chunks sequentially with a 65-second cooldown between requests.
    Used when the PDF exceeds the token limit and we fall back to text extraction.
    """
    model = _get_model()
    total = len(text_chunks)
    all_notes: list[str] = []

    for idx, chunk in enumerate(text_chunks, start=1):
        prompt = _CHUNK_PROMPT.format(
            chunk_idx=idx,
            total_chunks=total,
            subject=subject,
            lang=lang,
            chunk_text=chunk,
        )

        logger.info(
            "[GeminiFileAPI] Processing chunk %d/%d for '%s'…",
            idx, total, subject
        )

        response = await _call_with_backoff(
            model.generate_content,
            prompt,
        )
        all_notes.append(response.text.strip())

        if idx < total:
            logger.info(
                "[GeminiFileAPI] Chunk %d/%d done — sleeping %ds (TPM reset).",
                idx, total, CHUNK_COOLDOWN_SECS
            )
            await asyncio.sleep(CHUNK_COOLDOWN_SECS)

    return "\n\n---\n\n".join(all_notes)


def _estimate_word_count(pdf_path: str | Path) -> int:
    """Quickly estimate word count from a PDF using PyMuPDF (fitz) or pdfplumber."""
    try:
        import fitz  # PyMuPDF — fastest
        doc = fitz.open(str(pdf_path))
        total = sum(len(page.get_text().split()) for page in doc)
        doc.close()
        return total
    except ImportError:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return sum(
                len((p.extract_text() or "").split())
                for p in pdf.pages
            )
    except Exception:
        return 0


def _extract_full_text_in_chunks(pdf_path: str | Path) -> list[str]:
    """
    Extract the full text from a PDF and split it into word-limited chunks,
    breaking at chapter/unit boundaries where possible.
    """
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        pages = [page.get_text() for page in doc]
        doc.close()
    except ImportError:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]

    # Reconstruct full text preserving page breaks as paragraph separators.
    full_text = "\n\n".join(p.strip() for p in pages if p.strip())

    # Split on chapter/unit headings first; fall back to word-count windows.
    heading_re = re.compile(
        r"(?im)^(chapter|unit)\s+\d+[\s:\-]", re.MULTILINE
    )
    splits = heading_re.split(full_text)

    # Naive reassembly: join heading back with its body.
    sections: list[str] = []
    i = 0
    while i < len(splits):
        part = splits[i].strip()
        if not part:
            i += 1
            continue
        # If next two pieces look like "chapter" + number + body, merge them.
        if i + 2 < len(splits) and re.match(r"(?i)(chapter|unit)", splits[i]):
            merged = splits[i] + splits[i + 1] + splits[i + 2]
            sections.append(merged.strip())
            i += 3
        else:
            sections.append(part)
            i += 1

    # Group sections into word-limited chunks.
    chunks: list[str] = []
    current_words = 0
    current_parts: list[str] = []

    for section in sections:
        wc = len(section.split())
        if current_words + wc > CHUNK_WORD_LIMIT and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_words = 0
        current_parts.append(section)
        current_words += wc

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_notes_for_pdf(
    pdf_path: str | Path,
    subject: str,
    lang: str = "en",
) -> str:
    """
    Generate comprehensive EUEE study notes for a textbook PDF.

    Strategy selection:
      - If estimated token count <= CHUNK_TOKEN_LIMIT  →  single File API upload.
      - Otherwise                                      →  chunked text extraction
                                                          with 65 s cooldown between
                                                          chunk requests.

    This call is wrapped in the async queue so only one PDF is processed at a time.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    word_count     = _estimate_word_count(pdf_path)
    est_tokens     = int(word_count * TOKENS_PER_WORD_EST)
    file_size_mb   = pdf_path.stat().st_size / (1024 * 1024)

    logger.info(
        "[GeminiFileAPI] '%s' — %.1f MB, ~%d words, ~%d est. tokens.",
        pdf_path.name, file_size_mb, word_count, est_tokens,
    )

    # Gemini File API supports PDFs up to 2 GB / 1000 pages; keep well under TPM.
    if est_tokens <= CHUNK_TOKEN_LIMIT:
        logger.info(
            "[GeminiFileAPI] Token count within limit — using single File API upload."
        )
        coro = _generate_from_file(pdf_path, subject, lang)
    else:
        logger.info(
            "[GeminiFileAPI] Token count %d exceeds %d limit — using chunked extraction.",
            est_tokens, CHUNK_TOKEN_LIMIT,
        )
        chunks = _extract_full_text_in_chunks(pdf_path)
        logger.info(
            "[GeminiFileAPI] Split into %d chunks for '%s'.", len(chunks), subject
        )
        coro = _generate_from_chunks(chunks, subject, lang)

    # Route through the serialising queue.
    return await enqueue(coro)


async def generate_notes_for_text(
    text: str,
    subject: str,
    lang: str = "en",
) -> str:
    """
    Generate study notes directly from pre-extracted text (e.g., from Firestore chunks).
    Applies the same chunking + backoff logic; does NOT use the File API.
    """
    words  = text.split()
    chunks = [
        " ".join(words[i : i + CHUNK_WORD_LIMIT])
        for i in range(0, len(words), CHUNK_WORD_LIMIT)
    ]
    coro = _generate_from_chunks(chunks, subject, lang)
    return await enqueue(coro)
