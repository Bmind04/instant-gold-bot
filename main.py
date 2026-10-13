"""
BrightLiveBot / InstantGoldBot — Position Positive Possibilities Match Intelligence Bot
Features:
- Multi-Image Vision Analysis (1 to 4 screenshots per match: Form, H2H, Standings, Injuries, Referee)
- Position Positive Possibilities 3-Pillar Analytical Framework (Position, Positive, Possibilities)
- Early Payout (1UP / 2UP), Double Chance, Draw No Bet & Safety Combo Modeling
- Zero Virtual / Instant Football Simulations
"""

import os
import io
import time
import base64
import asyncio
import http.server
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import httpx
from PIL import Image
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

from google import genai
from google.genai import types
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from prompt import POSITION_POSITIVE_SYSTEM_PROMPT
from compliance import (
    RESPONSIBLE_GAMING_POLICY,
    PRIVACY_POLICY,
    TERMS_OF_SERVICE,
)
from tracker import init_db, log_user_activity, get_analytics_summary, get_all_user_ids
from fixtures import resolve_match_details

ADMIN_USERNAMES = {"lost_in_space000"}
ADMIN_USER_IDS = set()

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or GEMINI_API_KEY in environment variables!")


def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            print(f"Healthcheck server running on port {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"Healthcheck server warning: {e}")


threading.Thread(target=run_dummy_server, daemon=True).start()


async def render_keep_alive_task():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(240)
            try:
                await client.get(render_url, timeout=8.0)
            except Exception:
                pass


GENAI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
]

AI_MODELS = [
    ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", google_api_key=GEMINI_API_KEY, timeout=60.0, max_retries=0),
    ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", google_api_key=GEMINI_API_KEY, timeout=60.0, max_retries=0),
    ChatGoogleGenerativeAI(model="gemini-3.8-flash", google_api_key=GEMINI_API_KEY, timeout=60.0, max_retries=0),
    ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key=GEMINI_API_KEY, timeout=60.0, max_retries=0),
]


def optimize_image_bytes(image_bytes: bytes, max_dim: int = 1280, quality: int = 85) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_dim:
                if w > h:
                    new_w = max_dim
                    new_h = int(h * (max_dim / w))
                else:
                    new_h = max_dim
                    new_w = int(w * (max_dim / h))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=quality, optimize=True)
            return out_buf.getvalue()
    except Exception:
        return bytes(image_bytes)


user_request_timestamps: Dict[int, List[float]] = {}
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60

user_last_context: Dict[int, str] = {}


def check_rate_limit(user_id: int) -> tuple[bool, int]:
    now = time.time()
    timestamps = [t for t in user_request_timestamps.get(user_id, []) if now - t < RATE_LIMIT_WINDOW]
    user_request_timestamps[user_id] = timestamps
    if len(timestamps) >= RATE_LIMIT_MAX:
        wait_seconds = int(RATE_LIMIT_WINDOW - (now - timestamps[0])) + 1
        return False, max(1, wait_seconds)
    timestamps.append(now)
    user_request_timestamps[user_id] = timestamps
    return True, 0


async def keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    start_time = asyncio.get_event_loop().time()
    while not stop_event.is_set():
        if asyncio.get_event_loop().time() - start_time > 70.0:
            break
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        await asyncio.sleep(4)


def _call_genai_sync(contents: list) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=POSITION_POSITIVE_SYSTEM_PROMPT,
        temperature=0.25,
    )
    last_err = None
    for model_name in GENAI_MODELS:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All Gemini models failed: {last_err}")


async def analyze_position_positive(
    images: Optional[List[bytes]] = None,
    text_input: str = "",
    market_focus: str = "",
) -> str:
    live_context = ""
    if text_input and not images:
        try:
            fixture_info = await resolve_match_details(text_input)
            if fixture_info and fixture_info.get("verified"):
                live_context = (
                    f"\nVERIFIED SCHEDULE METRICS:\n"
                    f"• Match: {fixture_info['home']} vs {fixture_info['away']}\n"
                    f"• Competition: {fixture_info['league']}\n"
                    f"• Kickoff: {fixture_info['kickoff']}\n"
                    f"• Market Odds: {fixture_info['odds']}\n"
                )
        except Exception:
            pass

    focus_instruction = f"\nSPECIFIC MARKET ANGLE REQUESTED: {market_focus}\n" if market_focus else ""

    if images:
        optimized_imgs = [optimize_image_bytes(img) for img in images[:4]]
        prompt_text = (
            f"Analyze the attached {len(optimized_imgs)} match stat screenshot(s) using the "
            f"Position Positive Possibilities framework (1. Position, 2. Positive, 3. Possibilities).\n"
            f"Extract the exact teams, league/round, standings, form streaks, H2H record, injuries/missing players, "
            f"key player stats, and referee from all provided images.\n"
            f"{focus_instruction}"
            f"User Note: {text_input if text_input else 'Provide the full Position Positive Possibilities breakdown and best picks (including 1UP/2UP Early Payout and safety combos).'}"
        )
        try:
            contents = [
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                for img_bytes in optimized_imgs
            ]
            contents.append(prompt_text)
            return await asyncio.wait_for(asyncio.to_thread(_call_genai_sync, contents), timeout=65.0)
        except Exception:
            content_blocks = [{"type": "text", "text": prompt_text}]
            for img_bytes in optimized_imgs:
                b64_img = base64.b64encode(img_bytes).decode("utf-8")
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                })
            messages = [
                SystemMessage(content=POSITION_POSITIVE_SYSTEM_PROMPT),
                HumanMessage(content=content_blocks),
            ]
            for model in AI_MODELS:
                try:
                    resp = await asyncio.wait_for(asyncio.to_thread(model.invoke, messages), timeout=60.0)
                    return str(resp.content).strip()
                except Exception:
                    continue
            raise
    else:
        prompt_text = (
            f"Execute a full Position Positive Possibilities analysis (1. Position, 2. Positive, 3. Possibilities) "
            f"for:\n{text_input}\n{live_context}{focus_instruction}"
            f"Prioritize high-probability outcomes, Early Payout (1UP/2UP) protection, Double Chance, Draw No Bet, and Goal Bounds."
        )
        try:
            return await asyncio.wait_for(asyncio.to_thread(_call_genai_sync, [prompt_text]), timeout=65.0)
        except Exception:
            messages = [
                SystemMessage(content=POSITION_POSITIVE_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ]
            for model in AI_MODELS:
                try:
                    resp = await asyncio.wait_for(asyncio.to_thread(model.invoke, messages), timeout=60.0)
                    return str(resp.content).strip()
                except Exception:
                    continue
            raise


@dataclass
class _PendingBatch:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    user_id: int
    chat_id: int
    caption: str = ""
    images: List[bytes] = field(default_factory=list)
    task: Optional[asyncio.Task] = None


class PhotoBatchAccumulator:
    """Collects 1 to 4 screenshots uploaded together (album or rapid sequence) into a single analysis call."""

    def __init__(self, debounce_seconds: float = 1.6, max_images: int = 4):
        self.debounce_seconds = debounce_seconds
        self.max_images = max_images
        self._batches: Dict[str, _PendingBatch] = {}
        self._lock = asyncio.Lock()

    def _key(self, chat_id: int, user_id: int, media_group_id: Optional[str]) -> str:
        if media_group_id:
            return f"mg:{chat_id}:{media_group_id}"
        return f"user:{chat_id}:{user_id}"

    async def add_photo(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        image_bytes: bytes,
        caption: str,
        media_group_id: Optional[str],
    ):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        key = self._key(chat_id, user_id, media_group_id)

        async with self._lock:
            batch = self._batches.get(key)
            if batch is None:
                batch = _PendingBatch(
                    update=update,
                    context=context,
                    user_id=user_id,
                    chat_id=chat_id,
                    caption=caption,
                    images=[image_bytes],
                )
                self._batches[key] = batch
            else:
                if len(batch.images) < self.max_images:
                    batch.images.append(image_bytes)
                if caption and not batch.caption:
                    batch.caption = caption
                if batch.task and not batch.task.done():
                    batch.task.cancel()

            batch.task = asyncio.create_task(self._flush_after_delay(key))

    async def _flush_after_delay(self, key: str):
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return

        async with self._lock:
            batch = self._batches.pop(key, None)

        if not batch:
            return

        await _process_photo_batch(batch)


photo_accumulator = PhotoBatchAccumulator(debounce_seconds=1.6, max_images=4)


async def send_clean_message(update: Update, text: str):
    if len(text) > 4000:
        text = text[:4000]
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text, parse_mode=None)


async def _process_photo_batch(batch: _PendingBatch):
    user = batch.update.effective_user
    allowed, wait_sec = check_rate_limit(batch.user_id)
    if not allowed:
        await batch.update.message.reply_text(
            f"⏳ Please wait {wait_sec}s before sending another batch."
        )
        return

    log_user_activity(batch.user_id, user.username or "", user.first_name or "", query_type="photo")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(batch.context, batch.chat_id, stop_typing))
    try:
        report = await analyze_position_positive(images=batch.images, text_input=batch.caption)
        user_last_context[batch.user_id] = report
        await send_clean_message(batch.update, report)
    except Exception as e:
        await send_clean_message(
            batch.update,
            f"⚠️ Could not process screenshot(s). Please ensure the match stats are clearly visible and try again. ({str(e)[:80]})",
        )
    finally:
        stop_typing.set()
        typing_task.cancel()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user.id)
    log_user_activity(user.id, user.username or "", user.first_name or "", query_type="interaction")

    msg = """⚡ **POSITION POSITIVE POSSIBILITIES — MATCH AI** ⚽️👑
*Multimodal Tactical & Statistical Football Intelligence*

---

📸 **UPLOAD 1 TO 4 MATCH STAT SCREENSHOTS:**
Send 1–4 screenshots for any match (Standings, Recent Form, H2H, Injuries/Missing Players, Referee).
The AI reads every image together and runs the **Position Positive Possibilities** framework:

1️⃣ **Position (Tactical Reality):** League table motivation, home/away splits, and injury-list mismatches.
2️⃣ **Positive (Statistical Indicators):** Over 2.5 / BTTS rates, H2H dominance, key forwards, and referee card/penalty tendencies.
3️⃣ **Possibilities (High-Value Outcomes):** Primary Verdict, **1UP / 2UP Early Payout** protection, Double Chance & Over 1.5 safety combos, Player Props, and Wildcards.

---

📋 **COMMANDS:**
• 📸 **Send 1–4 Screenshots:** Automatic Position Positive Possibilities analysis
• `/analyse <Home vs Away>` — Full tactical & statistical breakdown for any match
• `/over [Match]` — Goals & Over/Under angle for a match (or your last uploaded screenshots)
• `/draw [Match]` — Double Chance / Draw No Bet / 1UP safety angle
• `/corner [Match]` — Corner & referee/card angle
• `/help` — Full guide"""
    await send_clean_message(update, msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, RESPONSIBLE_GAMING_POLICY)


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, PRIVACY_POLICY)


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, TERMS_OF_SERVICE)


async def _run_market_command(update: Update, context: ContextTypes.DEFAULT_TYPE, market_focus: str):
    user = update.effective_user
    user_id = user.id
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user_id)

    match_input = " ".join(context.args).strip() if context.args else ""
    if not match_input:
        last_ctx = user_last_context.get(user_id, "")
        if last_ctx:
            match_input = f"Using the match from this previous analysis:\n{last_ctx}"
        else:
            await send_clean_message(
                update,
                "📸 Upload 1–4 match stat screenshots first, or type the match name after the command (e.g. `/analyse Nottingham Forest vs Newcastle`).",
            )
            return

    allowed, wait_sec = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"⏳ Please wait {wait_sec}s before requesting another analysis.")
        return

    log_user_activity(user_id, user.username or "", user.first_name or "", query_type="analyse")
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(context, chat_id, stop_typing))
    try:
        report = await analyze_position_positive(text_input=match_input, market_focus=market_focus)
        user_last_context[user_id] = report
        await send_clean_message(update, report)
    except Exception as e:
        await send_clean_message(update, f"⚠️ Could not complete analysis: {str(e)[:100]}")
    finally:
        stop_typing.set()
        typing_task.cancel()


async def analyse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_market_command(update, context, market_focus="Full Position Positive Possibilities Breakdown (1UP/2UP Early Payout, Double Chance, Goals & Props)")


async def over_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_market_command(update, context, market_focus="Over/Under Goals, Team Goals, Goal Bounds & BTTS Possibilities")


async def draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_market_command(update, context, market_focus="1UP/2UP Early Payout, Double Chance (1X/X2) & Draw No Bet Safety Possibilities")


async def corner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_market_command(update, context, market_focus="Corners, Referee Card/Penalty Tendencies & Tactical Wing Matchups")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user.id)

    caption = (update.message.caption or "").strip()
    media_group_id = update.message.media_group_id

    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await photo_file.download_as_bytearray())

    await photo_accumulator.add_photo(
        update=update,
        context=context,
        image_bytes=image_bytes,
        caption=caption,
        media_group_id=media_group_id,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user_id)
    log_user_activity(user_id, user.username or "", user.first_name or "", query_type="text")

    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(context, chat_id, stop_typing))
    try:
        res = await analyze_position_positive(text_input=user_text)
        user_last_context[user_id] = res
        await send_clean_message(update, res)
    except Exception as e:
        await send_clean_message(update, f"⚠️ Could not analyze match text: {str(e)[:100]}")
    finally:
        stop_typing.set()
        typing_task.cancel()


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES) or (user.id in ADMIN_USER_IDS)
    if not is_admin:
        await update.message.reply_text("🔒 Access Denied: Admin only.")
        return

    ADMIN_USER_IDS.add(user.id)
    stats = get_analytics_summary()
    recent_lines = []
    for idx, (uname, fname, qcount, last_seen) in enumerate(stats["recent_users"], 1):
        dt_str = last_seen.split("T")[0] if "T" in str(last_seen) else str(last_seen)[:10]
        recent_lines.append(f"{idx}. **{uname}** ({fname}) — `{qcount} queries` [_{dt_str}_]")
    recent_text = "\n".join(recent_lines) if recent_lines else "_No users recorded yet._"

    msg = f"""📊 **ADMIN ANALYTICS DASHBOARD**
• **Total Users:** `{stats['total_users']}`
• **Active (24h):** `{stats['active_24h']}`
• **Total Analyses:** `{stats['total_queries']}` (📸 `{stats['photo_queries']}` | 💬 `{stats['text_queries']}`)

📋 **RECENT USERS:**
{recent_text}"""
    await send_clean_message(update, msg)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES) or (user.id in ADMIN_USER_IDS)
    if not is_admin:
        await update.message.reply_text("🔒 Access Denied: Admin only.")
        return

    broadcast_msg = " ".join(context.args).strip() if context.args else ""
    if not broadcast_msg:
        await update.message.reply_text("Usage: `/broadcast <message>`")
        return

    user_ids = get_all_user_ids()
    sent_count, fail_count = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_msg, parse_mode="Markdown")
            sent_count += 1
        except Exception:
            fail_count += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(f"✅ Broadcast Complete! Delivered: `{sent_count}` | Failed: `{fail_count}`")


def main():
    print("🚀 Initializing Position Positive Possibilities Bot...")
    init_db()

    request_kwargs = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, write_timeout=60.0)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request_kwargs).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("responsible", responsible_command))
    app.add_handler(CommandHandler("disclaimer", responsible_command))
    app.add_handler(CommandHandler("privacy", privacy_command))
    app.add_handler(CommandHandler("terms", terms_command))

    app.add_handler(CommandHandler("analyse", analyse_command))
    app.add_handler(CommandHandler("analyze", analyse_command))
    app.add_handler(CommandHandler("all", analyse_command))
    app.add_handler(CommandHandler("over", over_command))
    app.add_handler(CommandHandler("draw", draw_command))
    app.add_handler(CommandHandler("corner", corner_command))

    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("admin", users_command))
    app.add_handler(CommandHandler("stats", users_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    asyncio.get_event_loop().create_task(render_keep_alive_task())

    print("✅ Position Positive Possibilities Bot running on Telegram!")
    app.run_polling(poll_interval=2, timeout=30, bootstrap_retries=10)


if __name__ == "__main__":
    main()
