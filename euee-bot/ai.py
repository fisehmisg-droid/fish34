"""
AI provider hub for Abebe.

This module keeps the bot usable even when optional AI SDKs are missing
locally. Gemini is the preferred provider, Groq is the fast fallback,
Anthropic is used for a few premium content paths, and ElevenLabs is used
for premium audio when available.
"""

from __future__ import annotations

import asyncio
import logging
import os

# FIX: Add tenacity retry with exponential backoff for all external AI API calls.
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_message

_RETRY_DECORATOR = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    # Retry on common API transient issues (Rate limits, Overloaded, Timeouts)
    retry=retry_if_exception_message(match=r".*(rate|limit|overload|timeout|500|503|502|429).*"),
    reraise=True,
)

import db_supabase as db

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

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

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
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    SAMBANOVA_API_KEY,
    SAMBANOVA_MODEL,
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

openrouter_client = (
    OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    if OpenAI and OPENROUTER_API_KEY
    else None
)

sambanova_client = (
    OpenAI(base_url="https://api.sambanova.ai/v1", api_key=SAMBANOVA_API_KEY)
    if OpenAI and SAMBANOVA_API_KEY
    else None
)


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

def _openrouter_available() -> bool:
    return openrouter_client is not None

def _sambanova_available() -> bool:
    return sambanova_client is not None


# FIX: 30-second timeout wrapper for Gemini (which doesn't natively support timeout in the high-level API).
@_RETRY_DECORATOR
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
        # FIX: Wrap in a thread with timeout so a hung Gemini call never blocks the event loop.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(chat.send_message, user_msg[:10_000])
            response = future.result(timeout=30)
        return response.text.strip()
    except Exception as exc:
        logger.warning("Gemini error (%s), falling back to Groq.", exc)
        return _chat_groq(system, user_msg, history, allow_gemini_fallback=False)


@_RETRY_DECORATOR
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
        return _chat_openrouter(system, user_msg, history)

    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_msg[:2_000]})

    try:
        # FIX: 30-second timeout on Groq API call.
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            timeout=30,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Groq error (%s), falling back to Openrouter.", exc)
        if allow_gemini_fallback and _gemini_available():
            return _chat_gemini(system, user_msg, history)
        return _chat_openrouter(system, user_msg, history)


@_RETRY_DECORATOR
def _chat_openrouter(system: str, user_msg: str, history: list[dict] | None = None) -> str:
    """Robust fallback using Openrouter (Gemini 2.0 or Llama 3)."""
    if not _openrouter_available():
        return _chat_sambanova(system, user_msg, history)

    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_msg[:4_000]})

    try:
        # FIX: 30-second timeout on OpenRouter API call.
        response = openrouter_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            timeout=30,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Openrouter error (%s), falling back to SambaNova.", exc)
        return _chat_sambanova(system, user_msg, history)


@_RETRY_DECORATOR
def _chat_sambanova(system: str, user_msg: str, history: list[dict] | None = None) -> str:
    """Last resort ultra-fast fallback via SambaNova."""
    if not _sambanova_available():
        return _provider_unavailable_message()

    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_msg[:4_000]})

    try:
        # FIX: 30-second timeout on SambaNova API call.
        response = sambanova_client.chat.completions.create(
            model=SAMBANOVA_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            timeout=30,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("All AI providers exhausted or failed: %s", exc)
        return _provider_unavailable_message()


@_RETRY_DECORATOR
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
        # FIX: 30-second timeout on Anthropic API call.
        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            system=system,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=messages,
            timeout=30,
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

    # Check if AI providers are available
    if not groq_client and not genai:
        logger.warning("AI providers not available, using fallback question")
        return _generate_fallback_question(subject, lang)
    
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
    
    try:
        raw = _chat_groq(system, prompt)
        parsed = _parse_mcq(raw)
        if parsed["question"] and parsed["answer"]:
            return parsed
    except Exception as e:
        logger.warning(f"AI question generation failed: {e}")
    
    # Fallback to default question
    return _generate_fallback_question(subject, lang)


def _generate_fallback_question(subject: str, lang: str) -> dict:
    """Generate a simple fallback question when AI is not available"""
    questions = {
        "math": {
            "question": "What is the derivative of x²?",
            "options": {"A": "2x", "B": "x²", "C": "2x²", "D": "x"},
            "answer": "A",
            "explanation": "The derivative of x² is 2x using the power rule.",
            "topic": "Calculus"
        },
        "physics": {
            "question": "What is Newton's Second Law of Motion?",
            "options": {"A": "F = ma", "B": "E = mc²", "C": "PV = nRT", "D": "F = Gm₁m₂/r²"},
            "answer": "A",
            "explanation": "Newton's Second Law states that force equals mass times acceleration.",
            "topic": "Mechanics"
        },
        "chemistry": {
            "question": "What is the chemical formula for water?",
            "options": {"A": "H₂O", "B": "CO₂", "C": "O₂", "D": "N₂"},
            "answer": "A",
            "explanation": "Water is composed of two hydrogen atoms and one oxygen atom.",
            "topic": "Chemical Compounds"
        },
        "biology": {
            "question": "What is the function of mitochondria in cells?",
            "options": {"A": "Energy production", "B": "Protein synthesis", "C": "DNA storage", "D": "Cell division"},
            "answer": "A",
            "explanation": "Mitochondria are the powerhouses of the cell, producing ATP through cellular respiration.",
            "topic": "Cell Biology"
        }
    }
    
    # Return subject-specific question or default math question
    return questions.get(subject, questions["math"])


def _parse_mcq(raw: str) -> dict:
    import re
    result = {"question": "", "options": {}, "answer": "", "explanation": "", "topic": "General"}
    
    # Try to extract topic
    topic_match = re.search(r"(?i)TOPIC:\s*(.*)", raw)
    if topic_match:
        result["topic"] = topic_match.group(1).strip()
        
    # Try to extract question
    q_match = re.search(r"(?i)QUESTION:\s*(.*?)(?=\n[A-D]\)|$)", raw, re.DOTALL)
    if q_match:
        result["question"] = q_match.group(1).strip()
        
    # Extract options
    for letter in ["A", "B", "C", "D"]:
        opt_match = re.search(rf"(?i){letter}\)\s*(.*?)(?=\n[A-D]\)|$|\nANSWER:)", raw, re.DOTALL)
        if opt_match:
            result["options"][letter] = opt_match.group(1).strip()
            
    # Extract answer
    ans_match = re.search(r"(?i)ANSWER:\s*([A-D])", raw)
    if ans_match:
        result["answer"] = ans_match.group(1).upper()
        
    # Extract explanation
    exp_match = re.search(r"(?i)EXPLANATION:\s*(.*)", raw, re.DOTALL)
    if exp_match:
        result["explanation"] = exp_match.group(1).strip()
        
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


def generate_score_prediction(user: dict, weak_subjects: dict, lang: str) -> str:
    """Generate personalized EUEE score prediction based on user performance."""
    total_correct = user.get("correct_total", 0)
    total_questions = user.get("questions_total", 0)
    streak = user.get("streak", 0)
    exams_taken = user.get("exams_taken", 0)
    
    if total_questions == 0:
        accuracy = 0
    else:
        accuracy = round((total_correct / total_questions) * 100, 1)
    
    prompt = (
        f"You are an EUEE score prediction expert. Analyze this student data:\n"
        f"Total Questions: {total_questions}\n"
        f"Correct Answers: {total_correct}\n"
        f"Accuracy: {accuracy}%\n"
        f"Study Streak: {streak} days\n"
        f"Mock Exams Taken: {exams_taken}\n"
        f"Weak Subjects: {weak_subjects}\n\n"
        f"Generate a personalized EUEE score prediction and improvement plan. "
        f"Include:\n"
        f"1. Predicted EUEE score range (out of 700)\n"
        f"2. Key strengths to maintain\n"
        f"3. Critical areas to improve\n"
        f"4. Specific study recommendations\n"
        f"5. Confidence level and achievable target\n\n"
        f"Respond in {lang} with an encouraging but realistic tone. "
        f"Use emojis to make it engaging."
    )
    
    return _chat_gemini("EUEE Score Prediction Expert", prompt)
