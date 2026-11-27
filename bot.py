import truststore

truststore.inject_into_ssl()

import asyncio
import os
import mimetypes
import re
import uuid

import aiohttp
import fluxer

import json
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.environ["FLUXER_BOT_TOKEN"]
GUILD_ID = os.environ["GUILD_ID"]
OWNER_ID = os.environ["OWNER_ID"]
RESULTS_CHANNEL_ID = os.environ["RESULTS_CHANNEL_ID"]
# Optional: create Pending in Fluxer and put its ID in .env to enable auto-role.
PENDING_ROLE_ID = os.getenv("PENDING_ROLE_ID", "").strip()
VERIFIED_ROLE_ID = os.getenv("VERIFIED_ROLE_ID", "").strip()
MODERATOR_ROLE_IDS = {
    role.strip() for role in os.getenv("MODERATOR_ROLE_IDS", "").split(",")
    if role.strip()
}
if any(not role.isdigit() for role in MODERATOR_ROLE_IDS):
    raise ValueError("MODERATOR_ROLE_IDS must contain comma-separated numeric role IDs")
if PENDING_ROLE_ID:
    if not PENDING_ROLE_ID.isdigit() or not VERIFIED_ROLE_ID.isdigit():
        raise ValueError("PENDING_ROLE_ID and VERIFIED_ROLE_ID must be numeric role IDs")
    if PENDING_ROLE_ID == VERIFIED_ROLE_ID or PENDING_ROLE_ID == GUILD_ID:
        raise ValueError("Pending must be a separate role, not Verified or @everyone")

API_URL = os.getenv("FLUXER_API_URL", "https://fluxer.com/api/v1").rstrip("/")

bot = fluxer.Bot(
    command_prefix="!",
    intents=fluxer.Intents.all(),
    api_url=API_URL,
)

creation_lock = asyncio.Lock()

# Permission bits: view channel, send messages, read history.
VIEW = 1 << 10
SEND = 1 << 11
HISTORY = 1 << 16
TEST_ACCESS = VIEW | SEND | HISTORY


async def api(method, path, payload=None, image=None):
    headers = {"Authorization": f"Bot {TOKEN}"}
    image_path = BASE_DIR / image if image else None
    image_bytes = image_path.read_bytes() if image_path else None

    async with aiohttp.ClientSession(headers=headers) as session:
        for _ in range(5):
            # Rebuild multipart data on every retry; consumed forms cannot be reused.
            if image_path:
                body = dict(payload or {})
                body["attachments"] = [{"id": 0, "filename": image_path.name}]
                form = aiohttp.FormData()
                form.add_field("payload_json", json.dumps(body))
                form.add_field(
                    "files[0]", image_bytes, filename=image_path.name,
                    content_type=mimetypes.guess_type(image_path.name)[0]
                    or "application/octet-stream",
                )
                request_body = {"data": form}
            else:
                request_body = {"json": payload}
            async with session.request(
                method, API_URL + path, **request_body,
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(float(data.get("retry_after", 2)))
                    continue

                if response.status >= 400:
                    # Do not print request headers or the bot token.
                    raise RuntimeError(
                        f"Fluxer API returned HTTP {response.status} "
                        f"for {method} {path}"
                    )

                if response.status == 204:
                    return None

                return await response.json()

    raise RuntimeError("Rate limit persisted; try again shortly.")


async def send(channel_id, text, image=None):
    return await api(
        "POST",
        f"/channels/{channel_id}/messages",
        {
            "content": text,
            "allowed_mentions": {"parse": []},
            "nonce": uuid.uuid4().hex,
        },
        image=image,
    )


async def create_test_channel(user_id):
    user_id = str(user_id)
    name = f"test-{user_id}"

    async with creation_lock:
        # Reuse an existing channel, including after a bot restart.
        channels = await api("GET", f"/guilds/{GUILD_ID}/channels")
        existing = next(
            (channel for channel in channels if channel["name"] == name),
            None,
        )

        if existing:
            return existing["id"]

        # The guild ID is also the @everyone role ID.
        overwrites = [
            {
                "id": GUILD_ID,
                "type": 0,
                "allow": "0",
                "deny": str(VIEW),
            }
        ]

        # Member-specific access for the candidate, owner, and bot.
        member_ids = {user_id, OWNER_ID, str(bot.user.id)}

        for member_id in member_ids:
            overwrites.append(
                {
                    "id": member_id,
                    "type": 1,
                    "allow": str(TEST_ACCESS),
                    "deny": "0",
                }
            )

        channel = await api(
            "POST",
            f"/guilds/{GUILD_ID}/channels",
            {
                "name": name,
                "type": 0,
                "permission_overwrites": overwrites,
            },
        )

        await send(
            channel["id"],
            "Welcome! This is your private entry-test channel.\n"
            "Type !start when ready. The time limit will be shown when you start. "
            "Multiple-choice questions take a letter; open-ended questions "
            "take one text response. Type !question to show the current question.",
        )

        return channel["id"]


@bot.event
async def on_ready():
    global timer_task

    print(f"Connected as {bot.user.username}")
    print("Pending auto-role: enabled" if PENDING_ROLE_ID else
          "Pending auto-role: disabled (set PENDING_ROLE_ID in .env to enable)")

    if timer_task is None or timer_task.done():
        timer_task = asyncio.create_task(watch_deadlines())


@bot.command()
async def ping(ctx):
    await ctx.reply("Pong! Doge Examiner is online.")


@bot.command()
async def setup_test(ctx):
    # Only you can run this setup command, from the results channel.
    if str(ctx.author.id) != OWNER_ID:
        return

    if str(ctx.channel.id) != RESULTS_CHANNEL_ID:
        return

    try:
        channel_id = await create_test_channel(OWNER_ID)
        await ctx.reply(f"Test channel ready: <#{channel_id}>")
    except Exception as error:
        print(f"Channel setup failed: {error}")
        await ctx.reply(
            "Channel creation failed. Check the VS Code terminal."
        )


@bot.command()
async def approve(ctx, *, target: str = ""):
    # Never accept approvals in candidate channels or another community.
    if (str(ctx.channel_id) != RESULTS_CHANNEL_ID or not ctx.channel
            or str(ctx.channel.guild_id) != GUILD_ID or ctx.author.bot):
        return
    try:
        authorized = str(ctx.author.id) == OWNER_ID
        if not authorized and MODERATOR_ROLE_IDS:
            moderator = await api("GET", f"/guilds/{GUILD_ID}/members/{ctx.author.id}")
            authorized = bool(
                MODERATOR_ROLE_IDS.intersection(str(role) for role in moderator.get("roles", []))
            )
        if not authorized:
            await send(RESULTS_CHANNEL_ID, "You are not authorized to approve candidates.")
            return
        match = re.fullmatch(r"(?:<@!?)?([0-9]+)>?", target.strip())
        if not match:
            await send(RESULTS_CHANNEL_ID, "Usage: !approve USER_ID (or !approve @member)")
            return
        user_id = match.group(1)
        if not VERIFIED_ROLE_ID.isdigit():
            await send(RESULTS_CHANNEL_ID, "Set VERIFIED_ROLE_ID in .env before approving.")
            return
        # Require a submitted/expired test before allowing an approval command.
        attempt = db.execute(
            "SELECT status FROM exams WHERE user_id = ? AND status IN ('completed', 'expired')",
            (user_id,),
        ).fetchone()
        if not attempt:
            await send(RESULTS_CHANNEL_ID, "This member has no completed or expired test to review.")
            return
        member = await api("GET", f"/guilds/{GUILD_ID}/members/{user_id}")
        if member.get("user", {}).get("bot"):
            await send(RESULTS_CHANNEL_ID, "Bot accounts cannot be approved as candidates.")
            return
        await api("PUT", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{VERIFIED_ROLE_ID}")
    except Exception as error:
        print(f"Approval failed: {error}")
        await send(RESULTS_CHANNEL_ID, "Approval failed. Check the member ID, bot permissions, and role order.")
        return

    # Verified was granted successfully even if cleanup fails afterwards.
    cleanup_failed = False
    if PENDING_ROLE_ID:
        try:
            await api("DELETE", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{PENDING_ROLE_ID}")
        except Exception as error:
            cleanup_failed = True
            print(f"Verified granted but Pending cleanup failed: {error}")
    await send(
        RESULTS_CHANNEL_ID,
        f"Approved member {user_id}: Verified assigned by moderator {ctx.author.id}."
        + (" Pending could not be removed; remove it manually." if cleanup_failed else ""),
    )


async def report_role_error(action, user_id, error):
    print(f"{action} for member {user_id} failed: {error}")
    try:
        await send(
            RESULTS_CHANNEL_ID,
            f"Role setup needs attention for member {user_id}: {action} failed. "
            "Check role IDs, Manage Roles, and the bot's role position.",
        )
    except Exception:
        pass


@bot.event
async def on_member_join(member):
    if str(member.get("guild_id")) != GUILD_ID:
        return
    user = member.get("user", {})
    if user.get("bot") or not user.get("id"):
        return
    user_id = str(user["id"])
    # Fetch current roles rather than relying on a possibly stale join event.
    if PENDING_ROLE_ID:
        try:
            current = await api("GET", f"/guilds/{GUILD_ID}/members/{user_id}")
            roles = {str(role) for role in current.get("roles", [])}
            if VERIFIED_ROLE_ID in roles:
                if PENDING_ROLE_ID in roles:
                    await api("DELETE", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{PENDING_ROLE_ID}")
                return
            await api("PUT", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{PENDING_ROLE_ID}")
        except Exception as error:
            await report_role_error("Assign Pending", user_id, error)
            # Still create their private channel so a role error doesn't block setup.
    try:
        await create_test_channel(user_id)
    except Exception as error:
        print(f"New-member channel creation failed: {error}")


@bot.event
async def on_guild_member_update(member):
    # fluxer.py dispatches GUILD_MEMBER_UPDATE under this generic event name.
    if not PENDING_ROLE_ID or str(member.get("guild_id")) != GUILD_ID:
        return
    user_id = member.get("user", {}).get("id")
    roles = {str(role) for role in member.get("roles", [])}
    if not user_id or VERIFIED_ROLE_ID not in roles or PENDING_ROLE_ID not in roles:
        return
    try:
        # Recheck current state so an older update cannot undo a newer decision.
        current = await api("GET", f"/guilds/{GUILD_ID}/members/{user_id}")
        current_roles = {str(role) for role in current.get("roles", [])}
        if VERIFIED_ROLE_ID in current_roles and PENDING_ROLE_ID in current_roles:
            await api("DELETE", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{PENDING_ROLE_ID}")
    except Exception as error:
        await report_role_error("Remove Pending after approval", user_id, error)


# Loaded fresh for every new attempt; existing attempts use their database snapshot.
QUESTIONS_FILE = BASE_DIR / "questions.json"

CONFIG_FILE = BASE_DIR / "config.json"

db = sqlite3.connect(Path(__file__).with_name("exam.db"))
db.row_factory = sqlite3.Row

db.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        channel_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        deadline REAL NOT NULL,
        questions TEXT NOT NULL,
        answers TEXT NOT NULL,
        status TEXT NOT NULL
    )
""")
db.commit()

exam_lock = asyncio.Lock()
timer_task = None


def question_text(question):
    return question["text"] if isinstance(question, dict) else question


def question_choices(question):
    if not isinstance(question, dict):
        return {}
    if question.get("type") == "open_ended":
        return {}
    if question.get("options"):
        return question["options"]
    # Older saved attempts contain options inside the question text.
    return dict(re.findall(r"(?m)^([A-Z])\)\s*(.*)$", question["text"]))


def is_graded(question):
    return (
        isinstance(question, dict)
        and question.get("type") != "open_ended"
        and question.get("correct") is not None
    )


def load_config():
    """Load settings for a new attempt; saved deadlines remain unchanged."""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"config.json: invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    minutes = config.get("test_duration_minutes")
    if type(minutes) is not int or minutes < 1:
        raise ValueError("test_duration_minutes must be a positive whole number")
    unknown = set(config) - {"test_duration_minutes"}
    if unknown:
        raise ValueError("Unknown config.json setting: " + ", ".join(sorted(unknown)))
    return config


def load_questions():
    """Read and validate the editable test file without changing active attempts."""
    try:
        questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"questions.json: invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions.json must contain a non-empty list of questions")
    for index, question in enumerate(questions, 1):
        label = f"Question {index}"
        if not isinstance(question, dict):
            raise ValueError(f"{label}: must be a JSON object")
        if not isinstance(question.get("text"), str) or not question["text"].strip():
            raise ValueError(f"{label}: text must be a non-empty string")
        if question.get("type") not in ("multiple_choice", "open_ended"):
            raise ValueError(f"{label}: type must be multiple_choice or open_ended")
        if question["type"] == "multiple_choice":
            options = question.get("options")
            if not isinstance(options, dict) or len(options) < 2:
                raise ValueError(f"{label}: provide at least two options")
            if any(
                not re.fullmatch(r"[A-Z]", key)
                or not isinstance(value, str) or not value.strip()
                for key, value in options.items()
            ):
                raise ValueError(f"{label}: options need uppercase letters and non-empty text")
            correct = question.get("correct")
            if not isinstance(correct, str) or correct not in options:
                raise ValueError(f"{label}: correct must match one of the option letters")
        elif "correct" in question or "options" in question:
            raise ValueError(f"{label}: open-ended questions must omit correct and options")
        if "image" in question:
            image = question["image"]
            if not isinstance(image, str) or not image.strip():
                raise ValueError(f"{label}: image must be a relative filename")
            image_path = (BASE_DIR / image).resolve()
            if not image_path.is_relative_to(BASE_DIR) or not image_path.is_file():
                raise ValueError(f"{label}: image must exist inside the bot folder: {image}")
        rendered = question["text"] + "".join(
            f"\n{key}) {value}" for key, value in question.get("options", {}).items()
        )
        if len(rendered) > 1500:
            raise ValueError(f"{label}: shorten the question/options to 1500 characters")
    return questions


async def present_question(channel_id, questions, index):
    question = questions[index]
    text = f"Question {index + 1}/{len(questions)}:\n{question_text(question)}"
    choices = question_choices(question)
    if isinstance(question, dict) and question.get("options"):
        text += "\n" + "\n".join(f"{letter}) {label}" for letter, label in choices.items())
    text += (
        "\n\nReply with one letter: " + ", ".join(choices)
        if choices else
        "\n\nType your response in ONE message. A moderator will review it."
    )
    image = question.get("image") if isinstance(question, dict) else None
    await send(channel_id, text, image=image)


async def finish_exam(channel_id, status):
    row = db.execute(
        "SELECT * FROM exams WHERE channel_id = ?",
        (str(channel_id),),
    ).fetchone()

    if not row or row["status"] != "active":
        return

    db.execute(
        "UPDATE exams SET status = ? WHERE channel_id = ?",
        (status, str(channel_id)),
    )
    db.commit()

    questions = json.loads(row["questions"])
    answers = json.loads(row["answers"])

    score = 0
    graded_count = 0
    reports = []
    manual_submitted = 0
    manual_total = 0

    for index, question in enumerate(questions):
        answer = (
            answers[index]["text"]
            if index < len(answers)
            else None
        )

        if isinstance(question, dict):
            question_text = question["text"]
            correct = question.get("correct") if is_graded(question) else None
        else:
            # Preserve compatibility with existing older tests.
            question_text = question
            correct = None

        if correct is not None:
            graded_count += 1
            is_correct = (
                answer is not None
                and answer.strip().upper() == correct.upper()
            )
            score += int(is_correct)

            verdict = (
                "Correct"
                if is_correct
                else "Unanswered" if answer is None else "Incorrect"
            )
            grading = (
                f"\nResult: {verdict}"
                f"\nCorrect answer: {correct}"
            )
        else:
            manual_total += 1
            manual_submitted += int(answer is not None)
            grading = "\nResult: Awaiting moderator review" if answer is not None else "\nResult: Unanswered (manual-review question)"

        choices = question_choices(question)
        if isinstance(question, dict) and question.get("options"):
            question_text += "\n" + "\n".join(f"{key}) {value}" for key, value in choices.items())
        reports.append((
            f"Question {index + 1}: {question_text}\n"
            f"Answer: {answer if answer is not None else '(No answer)'}"
            f"{grading}",
            question.get("image") if isinstance(question, dict) else None,
        ))

    score_text = (
        f"You answered {score} out of {graded_count} "
        "graded questions correctly."
        if graded_count
        else "No automatically graded questions."
    )
    score_text += (
        f"\nOpen-ended responses awaiting moderator review: "
        f"{manual_submitted}/{manual_total}."
    )

    notice = (
        "Test completed."
        if status == "completed"
        else "Time is up."
    )

    try:
        await send(
            channel_id,
            f"{notice}\n{score_text}\n"
            "A moderator will review your application.",
        )
    except Exception as error:
        print(f"Could not send completion notice: {error}")

    try:
        await send(
            RESULTS_CHANNEL_ID,
            f"Entry test: {status}\n"
            f"Member ID: {row['user_id']}\n"
            f"Channel: <#{channel_id}>\n"
            f"Answered: {len(answers)}/{len(questions)}\n"
            f"Score: {score}/{graded_count}\n"
            f"Open-ended responses for review: {manual_submitted}/{manual_total}"
            if graded_count
            else (
                f"Entry test: {status}\n"
                f"Member ID: {row['user_id']}\n"
                f"Channel: <#{channel_id}>\n"
                "Grading: Manual review"
            ),
        )

        for report, image in reports:
            for offset in range(0, len(report), 1800):
                await send(
                    RESULTS_CHANNEL_ID,
                    report[offset:offset + 1800],
                    image=image if offset == 0 else None,
                )

    except Exception as error:
        print(
            "Results delivery failed; answers remain in exam.db. "
            f"Details: {error}"
        )


async def watch_deadlines():
    while True:
        try:
            async with exam_lock:
                expired = db.execute(
                    """
                    SELECT channel_id FROM exams
                    WHERE status = 'active' AND deadline <= ?
                    """,
                    (time.time(),),
                ).fetchall()

                for row in expired:
                    await finish_exam(row["channel_id"], "expired")

        except Exception as error:
            print(f"Deadline check failed: {error}")

        await asyncio.sleep(2)


@bot.event
async def on_message(message):
    global timer_task

    if message.author.bot:
        return

    channel_id = str(message.channel_id)
    user_id = str(message.author.id)
    text = message.content.strip()

    # Only the candidate assigned to this channel can submit answers.
    if not message.channel:
        return

    if str(message.channel.guild_id) != GUILD_ID:
        return

    if message.channel.name != f"test-{user_id}":
        return

    # Also start the deadline watcher if it isn't already running.
    if timer_task is None or timer_task.done():
        timer_task = asyncio.create_task(watch_deadlines())

    async with exam_lock:
        row = db.execute(
            "SELECT * FROM exams WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()

        if text.lower() == "!start":
            if row:
                await send(
                    channel_id,
                    "You already started this test. "
                    "Its timer cannot be reset.",
                )
                return

            try:
                config = load_config()
                questions = load_questions()
                duration_minutes = config["test_duration_minutes"]
            except (OSError, ValueError) as error:
                print(f"Cannot start test: {error}")
                await send(
                    channel_id,
                    "The test configuration needs attention. Please contact a moderator. "
                    "Your test has not started.",
                )
                return

            db.execute(
                "INSERT INTO exams VALUES (?, ?, ?, ?, ?, ?)",
                (
                    channel_id,
                    user_id,
                    time.time() + duration_minutes * 60,
                    json.dumps(questions),
                    "[]",
                    "active",
                ),
            )
            db.commit()

            await send(
                channel_id,
                f"Your {duration_minutes}-minute test has started. Reply with a letter for "
                "multiple choice, or ONE text message for open-ended questions. "
                "Accepted answers are final; edits do not change them. "
                "Type !question to display your current question again.",
            )
            await present_question(channel_id, questions, 0)
            return

        if not row:
            if not text.startswith("!"):
                await send(channel_id, "Type !start when ready.")
            return

        if row["status"] != "active":
            return

        if time.time() >= row["deadline"]:
            await finish_exam(channel_id, "expired")
            return

        if text.lower() == "!question":
            saved_questions = json.loads(row["questions"])
            saved_answers = json.loads(row["answers"])
            if len(saved_answers) < len(saved_questions):
                await present_question(channel_id, saved_questions, len(saved_answers))
            return

        if text.startswith("!") or not text:
            return

        questions = json.loads(row["questions"])
        answers = json.loads(row["answers"])

        question = questions[len(answers)]
        choices = question_choices(question)
        if choices:
            choice = text.upper()
            if choice not in choices:
                await send(channel_id, "Please reply with one letter: " + ", ".join(choices))
                return
            text = choice

        answers.append({
            "text": text,
            "submitted_at": time.time(),
            "message_id": str(message.id),
        })

        db.execute(
            "UPDATE exams SET answers = ? WHERE channel_id = ?",
            (json.dumps(answers), channel_id),
        )
        db.commit()

        if len(answers) == len(questions):
            await finish_exam(channel_id, "completed")
        else:
            await present_question(channel_id, questions, len(answers))

load_config()
load_questions()  # Fail clearly at startup if a configuration file is invalid.

bot.run(TOKEN)