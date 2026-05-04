from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


OUTPUT_DIR = Path("docs")
OUTPUT_PDF = OUTPUT_DIR / "Abebe_EUEE_User_Guide.pdf"
OUTPUT_MD = OUTPUT_DIR / "Abebe_EUEE_User_Guide.md"


TITLE = "Abebe EUEE Bot User Guide"
SUBTITLE = "Student-facing guide prepared on May 1, 2026"

SECTIONS = [
    (
        "1. What This Bot Is For",
        [
            "Abebe is built to feel less like a machine and more like a steady study partner for Ethiopian Grade 12 students preparing for the EUEE. The bot is not meant to replace a teacher, a textbook, or real question practice. Its real value is speed, structure, and consistency. A student can open Telegram, choose a subject, and immediately move into questions, revision notes, flashcards, audio lessons, memory tricks, and progress feedback without needing a separate app or website.",
            "The strongest way to use Abebe is not to ask it to do all the thinking. The strongest way is to let it keep the student moving. A student who is tired, distracted, or short on time often loses momentum before the first page is even opened. The bot solves that problem by making the first step small. One tap can start a random challenge. One subject pick can open a note pack. One answer can trigger instant feedback. That matters more than people think because consistency beats intensity in long exam preparation.",
            "This guide is written for normal users, not developers. It explains what the bot can do now, how to use it well, what premium features actually mean in practice, and where the bot should still be used with common sense. The goal is simple: if a student or parent reads this once, they should understand how to get value from the bot without feeling lost or overwhelmed.",
        ],
    ),
    (
        "2. First-Time Use",
        [
            "The first experience should be simple. A student opens the bot, sends start, chooses a language, and lands on the main menu. From there the most useful path is to begin with Practice or Mock Exam after choosing a subject. That single step gives the bot context, which improves almost everything that comes after it. Once a subject is selected, the later tools such as notes, exam tips, battle mode, and progress tracking feel much more coherent.",
            "Students who like to warm up gently should begin with Study Notes or Audio Lesson before doing questions. Students who already know the chapter but need pressure should begin with Random Challenge or Mock Exam. Students who keep forgetting facts should go straight to Flashcards and then follow with a short practice round. There is no one perfect order, but there is a wrong pattern that should be avoided: opening too many features in one sitting without finishing any of them. Abebe works best when each session has one clear purpose.",
            "Parents do not need to learn the whole bot to benefit from it. If the student shares a parent link, the parent dashboard gives a cleaner summary view with the current streak, total questions answered, membership tier, and the latest weekly report. That makes it easier for a parent to support a student with routine and accountability instead of only asking whether studying happened.",
        ],
    ),
    (
        "3. Daily Study Flow",
        [
            "A strong daily routine with Abebe can be surprisingly short. A student can start with one random or subject-specific question, review the explanation, ask one follow-up, then spend ten minutes on notes or audio. After that, a quick flashcard round is enough to lock in what was just covered. This rhythm works because it alternates recall, explanation, and repetition instead of letting the student stay in passive reading for too long.",
            "The progress tools matter most after a few sessions, not after one. Streaks, correct answers, weak-subject radar, and leaderboard placement are motivation tools, not proof of mastery by themselves. A student should read them as signals. If the radar keeps showing the same weak area, that is the place to spend the next two or three sessions. If the streak is strong but the exam score stays flat, the student is probably studying often but not deeply enough. The bot is useful when it nudges better decisions, not when it becomes the decision.",
            "Students should also treat the memory tools with discipline. Memory tricks are helpful only when they point back to understanding. A trick that helps you remember the order of something is useful. A trick that becomes a substitute for understanding is dangerous. The same is true of audio. Audio is excellent for revision, repetition, and low-energy moments, but it should not replace written practice in subjects that require steps, structure, and exact wording.",
        ],
    ),
    (
        "4. Feature Guide",
        [
            "Practice mode is the conversational core of the bot. It lets a student stay in one subject and keep asking until the concept starts to feel stable. Mock Exam is different. It creates a fixed question run, keeps score, and ends with a result summary. Battle Mode adds pressure by turning a question into a head-to-head challenge that can be shared with another student. Boss Fight is the harder premium version of that idea and is best treated as a weekly confidence check rather than a daily learning tool.",
            "Study Notes, Flashcards, and Audio Lesson now work as a real content trio. Notes are the broad map. Flashcards are the short memory loop. Audio is the spoken revision layer for moments when a student is tired of screens or wants to revise while moving around. Exam Tips and Memory Trick features sit on top of that trio. They are not the main meal, but they can make the main material easier to hold.",
            "Score Predictor and Weak Radar should be used honestly. They are best when the student already has enough activity for the bot to notice patterns. They are weak when the student has barely answered anything. Progress and leaderboard features are motivational only. They should push a student toward better habits, not toward chasing vanity numbers or comparing themselves unfairly with others.",
        ],
    ),
    (
        "5. Free, Pro, and Max",
        [
            "The free tier is best seen as a serious trial, not a toy. A student can still feel the core teaching style, answer questions, and understand whether the bot fits their study habits. Pro becomes worthwhile when the student wants regular access to deeper materials such as notes and audio, especially if revision is happening every day. Max is most useful for students who want the full study loop: flashcards, advanced progress views, parent visibility, and competition features.",
            "No student should upgrade just because a feature sounds exciting. The better question is whether the feature changes behavior. If notes and audio will keep a student revising consistently, that is useful. If flashcards will actually be reviewed several times a week, that is useful. If a parent dashboard will create healthy structure at home, that is useful. If the upgrade only adds novelty but does not change routine, the value is lower than it looks.",
            "For parents, the most meaningful premium benefit is not more content. It is clearer visibility. A parent usually does not need every explanation or flashcard. A parent needs to know whether effort is regular, whether weak areas are repeating, and whether the student is drifting or improving. The dashboard and weekly report are designed to support that conversation.",
        ],
    ),
    (
        "6. Honest Limits and Best Practices",
        [
            "Abebe is strong as a study companion, but students should still use judgment. Not every fast explanation is a full lesson. Not every correct multiple-choice answer proves mastery. Subjects like mathematics, physics, chemistry, and essay-based humanities still require written work away from the chat window. The bot is best at keeping momentum, supporting revision, and identifying where a student should focus next. It is not a replacement for solving many real exam questions by hand.",
            "Students should also avoid turning the bot into background noise. It is possible to collect notes, listen to audio, and flip cards without retaining much. The safer habit is to stop after each short block and answer one question from memory. Can you explain the chapter without looking? Can you solve one related question? Can you summarize the trap that usually causes errors? If the answer is no, then more input is not the solution yet. Retrieval is.",
            "One final limit is practical: some features depend on the quality of the available subject material. Where textbook content is complete, the notes and flashcards feel fuller. Where a local textbook is missing, the bot can still provide a starter guide, but the student should understand the difference between a full subject pack and a lighter fallback. The right response is not frustration. The right response is to use what is strong now and improve the missing source material over time.",
        ],
    ),
    (
        "7. What Was Improved and Why",
        [
            "The latest rebuild focused on making the bot feel reliable instead of flashy. The study content layer now falls back to local textbook material when cached database chunks are missing. Missing note packs were created, a civics starter guide was added so the subject no longer dead-ends, flashcard decks were generated for every subject folder, and the missing lesson audio files were built so the audio menu does not feel half-finished. The mock exam flow now behaves like a real exam run instead of stopping after a single answer, and battle mode now has a practical join-and-resolve flow instead of a shell that looks exciting but breaks under real use.",
            "The product choices were also informed by patterns seen in other Telegram learning bots and official Telegram tooling. MemoCard emphasizes the value of sharing decks directly in Telegram and using push reminders for review, while QuizBot-style projects show how much immediate feedback and score summaries matter in quiz sessions. The official python-telegram-bot deep linking example shows a clean way to move users into a specific bot flow from a shared link, and Telegram's poll and quiz support shows why tightly structured answer flows work well inside chat products. Those references pushed this rebuild toward clearer state transitions, better sharing behavior, and stronger revision loops instead of chasing too many novelty features at once.",
            "In plain terms, the bot is now closer to what a student expects when they tap a button. Notes exist where they were missing. Flashcards are not empty. Audio is available for the full subject set. Parent links point to a working dashboard. Optional AI packages no longer crash the whole app if one provider is unavailable. The result is not perfection, but it is much closer to a user-ready study tool than a collection of half-connected ideas.",
        ],
    ),
]


def write_markdown_source() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# {TITLE}", "", SUBTITLE, ""]
    for heading, paragraphs in SECTIONS:
        lines.append(f"## {heading}")
        lines.append("")
        lines.extend(paragraphs)
        lines.append("")
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def add_page_number(canvas, doc):
    page_number = canvas.getPageNumber()
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawRightString(19 * cm, 1.2 * cm, f"Page {page_number}")


def build_pdf() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2.2 * cm,
        bottomMargin=1.8 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#1f3d37"),
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "subtitle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=12,
        leading=18,
        textColor=colors.HexColor("#5d655f"),
        alignment=TA_CENTER,
    )
    heading_style = ParagraphStyle(
        "heading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#1f3d37"),
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=17,
        textColor=colors.HexColor("#1f1f1f"),
        spaceAfter=10,
    )

    story = [
        Spacer(1, 5 * cm),
        Paragraph(TITLE, title_style),
        Spacer(1, 0.6 * cm),
        Paragraph(SUBTITLE, subtitle_style),
        Spacer(1, 0.8 * cm),
        Paragraph("A readable guide for students, parents, and anyone handing off the bot in a real study setting.", subtitle_style),
        Spacer(1, 1.2 * cm),
    ]

    for index, (heading, paragraphs) in enumerate(SECTIONS):
        story.append(Paragraph(heading, heading_style))
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph, body_style))
        if index < len(SECTIONS) - 1:
            story.append(PageBreak())

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)


if __name__ == "__main__":
    write_markdown_source()
    build_pdf()
    print(f"Created {OUTPUT_PDF}")
