"""
AI provider hub for Abebe.

This module keeps the bot usable even when optional AI SDKs are missing
locally. Gemini is the preferred provider, Groq is the fast fallback,
Anthropic is used for a few premium content paths, and ElevenLabs is used
for premium audio when available.
"""

from __future__ import annotations

import logging

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from elevenlabs import save
    from elevenlabs.client import ElevenLabs
except ImportError:
    save = None
    ElevenLabs = None

try:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        import google.generativeai as genai
except ImportError:
    genai = None

try:
    from groq import Groq
except ImportError:
    Groq = None

from config import (
    ABEBE_SYSTEM_AM,
    ABEBE_SYSTEM_EN,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    ELI10_PROMPT_AM,
    ELI10_PROMPT_EN,
    ELEVENLABS_API_KEY,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    MAX_TOKENS,
    PREDICTOR_PROMPT_EN,
    TEMPERATURE,
    TOPPER_TIP_PROMPT,
)

logger = logging.getLogger(__name__)

anthropic_client = (
    anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    if anthropic and ANTHROPIC_API_KEY
    else None
)
groq_client = Groq(api_key=GROQ_API_KEY) if Groq and GROQ_API_KEY else None
eleven_client = (
    ElevenLabs(api_key=ELEVENLABS_API_KEY)
    if ElevenLabs and ELEVENLABS_API_KEY
    else None
)

if genai and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def _provider_unavailable_message() -> str:
    return "Abebe is temporarily offline for this feature. Please try again in a moment."


def _is_suspicious(text: str) -> bool:
    """
    Check for common prompt injection / jailbreak patterns (Pass 4.3 Hardening).
    This helps prevent 'vibe-coded' applications from leaking internal prompts
    or being manipulated into malicious personas.
    """
    text = text.lower()
    patterns = [
        "ignore all previous",
        "system prompt",
        "you are now a",
        "dan mode",
        "developer mode",
        "jailbreak",
        "mythous",
        "bypass",
        "reveal your instructions",
        "disregard",
        "new rules",
        "command override",
        "hypothetical scenario where",
        "assistant is offline",
        "override safety",
    ]
    return any(p in text for p in patterns)


def _gemini_available() -> bool:
    return genai is not None and bool(GEMINI_API_KEY)


def _groq_available() -> bool:
    return groq_client is not None


def _anthropic_available() -> bool:
    return anthropic_client is not None and "your-key-here" not in ANTHROPIC_API_KEY


def _chat_gemini(system: str, user_msg: str, history: list[dict] | None = None) -> str:
    """Primary reasoning engine for short-context Q&A."""
    if _is_suspicious(user_msg):
        return "I am Abebe, your study partner. I only help with EUEE preparation. Let's get back to studying!"

    if not _gemini_available():
        return _chat_groq(system, user_msg, history, allow_gemini_fallback=False)

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=system,
        )
        chat = model.start_chat(history=[])
        response = chat.send_message(user_msg[:10_000])
        return response.text.strip()
    except Exception as exc:
        logger.warning("Gemini error, falling back to Groq: %s", exc)
        return _chat_groq(system, user_msg, history, allow_gemini_fallback=False)


def _chat_groq(
    system: str,
    user_msg: str,
    history: list[dict] | None = None,
    allow_gemini_fallback: bool = True,
) -> str:
    """Fast fallback engine for quizzes and lightweight prompts."""
    if _is_suspicious(user_msg):
        return "I am Abebe, your study partner. I only help with EUEE preparation. Let's get back to studying!"

    if not _groq_available():
        if allow_gemini_fallback and _gemini_available():
            return _chat_gemini(system, user_msg, history)
        return _provider_unavailable_message()

    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_msg[:2_000]})

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Groq error: %s", exc)
        if allow_gemini_fallback and _gemini_available():
            return _chat_gemini(system, user_msg, history)
        return _provider_unavailable_message()


def _chat_anthropic(system: str, user_msg: str, history: list[dict] | None = None) -> str:
    """Premium fallback for a few longer-form helper outputs."""
    if _is_suspicious(user_msg):
        return "I am Abebe, your study partner. I only help with EUEE preparation. Let's get back to studying!"

    if not _anthropic_available():
        return _chat_gemini(system, user_msg, history)

    messages = []
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_msg[:4_000]})

    try:
        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            system=system,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.warning("Anthropic error, falling back to Gemini: %s", exc)
        return _chat_gemini(system, user_msg, history)


async def generate_notes_gemini(
    subject: str,
    lang: str = "en",
    pdf_path: str | None = None,
    text: str | None = None,
) -> str:
    """
    Generate full notes through the Gemini File API when available.

    If Gemini is unavailable, fall back to a shorter text-only generation so the
    user still gets usable content instead of a hard failure.
    """
    if _gemini_available():
        from gemini_file_api import generate_notes_for_pdf, generate_notes_for_text

        if pdf_path:
            logger.info("[ai] Routing %s through Gemini File API.", pdf_path)
            return await generate_notes_for_pdf(pdf_path, subject, lang)
        if text:
            logger.info("[ai] Routing extracted text through Gemini chunk pipeline.")
            return await generate_notes_for_text(text, subject, lang)
    else:
        logger.warning("Gemini unavailable. Falling back to standard chat generation.")

    base_text = (text or "")[:8_000]
    prompt = (
        f"Create readable Grade 12 EUEE study notes for {subject}.\n"
        f"Language: {lang}\n"
        "Structure the response with topic headings, key ideas, exam traps, and revision tips.\n"
        f"Source material:\n{base_text}"
    )
    return _chat_gemini("Senior EUEE curriculum coach.", prompt)


def ask_abebe(
    question: str,
    subject: str,
    lang: str,
    context_chunks: list[str] | None = None,
    history: list[dict] | None = None,
) -> str:
    system = ABEBE_SYSTEM_EN if lang == "en" else ABEBE_SYSTEM_AM
    context = ""
    if context_chunks:
        context = "\n\n[Textbook Material]\n" + "\n---\n".join(context_chunks[:10])
    prompt = f"Subject: {subject}\n{context}\n\nStudent: {question}\n\nGuide me."
    return _chat_gemini(system, prompt, history)


def _default_mcq(subject: str) -> dict:
    return {
        "question": f"Which answer best matches a core Grade 12 {subject} concept?",
        "options": {
            "A": "A definition connected to the topic",
            "B": "A partly related but inaccurate idea",
            "C": "A statement from a different subject",
            "D": "A random everyday statement",
        },
        "answer": "A",
        "explanation": "This is a safe fallback question used when live quiz generation is unavailable.",
    }


def generate_exam_question(
    subject: str,
    difficulty: str = "medium",
    lang: str = "en",
    model_index: str = None,
) -> dict:
    # Attempt to fetch a real question from the database first
    real_q = db.get_random_real_question(subject)
    if real_q:
        return real_q

    system = ABEBE_SYSTEM_EN if lang == "en" else ABEBE_SYSTEM_AM
    lang_note = "Respond in Amharic." if lang == "am" else "Respond in English."
    model_note = f" This is for Model Exam #{model_index}." if model_index else ""
    prompt = (
        f"Generate one {difficulty}-difficulty EUEE exam question for Grade 12 {subject}.{model_note}\n"
        f"{lang_note}\n"
        "Format exactly as:\n"
        "TOPIC: [Specific Chapter/Unit Name]\n"
        "QUESTION: [text]\n"
        "A) [option]\n"
        "B) [option]\n"
        "C) [option]\n"
        "D) [option]\n"
        "ANSWER: [A/B/C/D]\n"
        "EXPLANATION: [text]"
    )
    raw = _chat_groq(system, prompt)
    parsed = _parse_mcq(raw)
    return parsed if parsed["question"] and parsed["answer"] else _default_mcq(subject)


def _parse_mcq(raw: str) -> dict:
    lines = raw.strip().splitlines()
    result = {"question": "", "options": {}, "answer": "", "explanation": "", "topic": "General"}
    for line in lines:
        if line.startswith("TOPIC:"):
            result["topic"] = line.split(":", 1)[1].strip()
        elif line.startswith("QUESTION:"):
            result["question"] = line.split(":", 1)[1].strip()
        elif line.startswith("A)"):
            result["options"]["A"] = line[2:].strip()
        elif line.startswith("B)"):
            result["options"]["B"] = line[2:].strip()
        elif line.startswith("C)"):
            result["options"]["C"] = line[2:].strip()
        elif line.startswith("D)"):
            result["options"]["D"] = line[2:].strip()
        elif line.startswith("ANSWER:"):
            result["answer"] = line.split(":", 1)[1].strip().upper()[:1]
        elif line.startswith("EXPLANATION:"):
            result["explanation"] = line.split(":", 1)[1].strip()
    return result


def generate_audio_file(text: str, output_path: str, lang: str = "en") -> bool:
    if eleven_client is None:
        return False

    try:
        voice_id = "Xb7hH8MSUJpSbSDYk0k2"  # Alice - Clear, Engaging Educator (free premade)
        if hasattr(eleven_client, "generate") and save is not None:
            audio = eleven_client.generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2",
            )
            save(audio, output_path)
            return True

        if hasattr(eleven_client, "text_to_speech"):
            stream = eleven_client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            with open(output_path, "wb") as file_handle:
                for chunk in stream:
                    file_handle.write(chunk)
            return True

        return False
    except Exception as exc:
        logger.error(f"ElevenLabs audio generation failed: {exc}")
        if hasattr(exc, "body"):
            logger.error(f"ElevenLabs Error Body: {exc.body}")
        return False


def eli10_explain(last_explanation: str, lang: str) -> str:
    system = ELI10_PROMPT_EN if lang == "en" else ELI10_PROMPT_AM
    return _chat_gemini(system, f"Simplify for a 10-year-old: {last_explanation}")


def predict_euee_score(user_data: dict, lang: str) -> str:
    system = ABEBE_SYSTEM_EN if lang == "en" else ABEBE_SYSTEM_AM
    stats_summary = {
        "streak": user_data.get("streak", 0),
        "correct_total": user_data.get("correct_total", 0),
        "wrong_total": user_data.get("wrong_total", 0),
        "subject_correct": user_data.get("subject_correct", {}),
        "subject_attempts": user_data.get("subject_attempts", {}),
        "study_minutes": user_data.get("study_minutes_total", 0),
        "topic_performance": user_data.get("topic_performance", {})
    }
    prompt = PREDICTOR_PROMPT_EN.format(stats=json.dumps(stats_summary, indent=2))
    return _chat_gemini(system, prompt)


def generate_confession_lesson(topic: str, lang: str) -> str:
    prompt = f"Topic: {topic}\nLanguage: {lang}\nExplain gently, simply, and with study steps."
    return _chat_gemini("Warm Ethiopian tutor for confused students.", prompt)


def generate_topper_tip(lang: str) -> str:
    prompt = TOPPER_TIP_PROMPT.format(lang="Amharic" if lang == "am" else "English")
    return _chat_gemini("Top student study advice.", prompt)


def generate_weak_radar_analysis(weak_subjects: dict, lang: str) -> str:
    prompt = (
        f"Based on this REAL student performance data: {weak_subjects}\n"
        "Identify the top 3 critical weaknesses and give highly specific, actionable study advice. "
        f"Respond in {lang}. Use a direct, coaching tone."
    )
    return _chat_gemini("Expert EUEE Performance Analyst.", prompt)


def generate_parent_shock_report(stats: dict, child_name: str) -> str:
    prompt = (
        f"Child: {child_name}\n"
        f"Stats: {stats}\n"
        "Write a factual, caring weekly parent report with strengths, concerns, and next steps."
    )
    return _chat_gemini("Parent-facing education report writer.", prompt)


def generate_survival_kit(lang: str) -> list[str]:
    questions = []
    for subject in ["math", "physics", "chemistry", "biology", "english"]:
        question = _chat_groq("Fast question generator.", f"Most likely EUEE {subject} question.")
        questions.append(f"{subject.title()}: {question}")
    return questions


def generate_boss_fight_question(subject: str) -> str:
    prompt = f"Create one ultra-hard EUEE boss fight question for {subject}. Question only."
    return _chat_gemini("Boss fight question master.", prompt)


def generate_feature_proposal(idea: str) -> str:
    prompt = (
        f"The user has suggested a new feature idea: '{idea}'.\n"
        "Analyze this feature and output exactly in this format:\n\n"
        "Feature idea: [Name of feature]\n"
        "Usefulness: [High/Medium/Low]\n"
        "Risk level: [High/Medium/Low]\n"
        "Difficulty: [High/Medium/Low]\n\n"
        "[Brief description of the implementation considerations]"
    )
    return _chat_gemini("Feature analyzer and software architect.", prompt)

