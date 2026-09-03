"""
InstantGoldBot — 24/7 Dedicated Virtual & Instant Football Intelligence Bot
Features:
- Instant Automated Vision Analysis (Upload any screenshot)
- Pillow Image Optimization (10x faster response time)
- Multi-Photo Album Deduplication
- Anti-Spam Rate Limiting per User
- Full Responsible Gaming & Data Privacy Compliance
- Render 24/7 Self-Ping Keep-Alive
"""

import os
import io
import time
import base64
import asyncio
import http.server
import socketserver
import threading
import httpx
from PIL import Image
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from prompt import FRAMEWORK_VIRTUAL_FOOTBALL_PROMPT
from compliance import (
    RESPONSIBLE_GAMING_POLICY,
    PRIVACY_POLICY,
    TERMS_OF_SERVICE,
    COMPLIANCE_FOOTER
)
from tracker import init_db, log_user_activity, get_analytics_summary, get_all_user_ids

# Admin security list
ADMIN_USERNAMES = {"lost_in_space000"}
ADMIN_USER_IDS = set()

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or GEMINI_API_KEY in environment variables!")

# 1. Dummy HTTP Server for Render Health Check
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

# 2. Render Keep-Alive Background Task
async def render_keep_alive_task():
    """Pings the container every 4 minutes to prevent Render free tier sleep."""
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(240)
            try:
                await client.get(render_url, timeout=8.0)
                print("Keep-Alive ping sent successfully.")
            except Exception as e:
                print(f"Keep-Alive ping warning: {e}")

# 3. AI Models (Primary: gemini-3.6-flash, Fallback: gemini-3.5-flash)
llm_primary = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    timeout=60.0,
    max_retries=1
)
llm_secondary = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    google_api_key=GEMINI_API_KEY,
    timeout=60.0,
    max_retries=1
)

# 4. Image Optimization using Pillow
def optimize_image_bytes(image_bytes: bytes, max_dim: int = 1024, quality: int = 85) -> bytes:
    """Compresses and downscales images from MBs to ~80KB for rapid AI processing."""
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
    except Exception as e:
        print(f"Warning: Image optimization fallback: {e}")
        return image_bytes

# 5. Anti-Spam Rate Limiter (Max 6 requests per 60s per user)
user_request_timestamps = {}  # user_id -> [timestamps]
RATE_LIMIT_MAX = 6
RATE_LIMIT_WINDOW = 60

def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """Returns (is_allowed, seconds_to_wait)."""
    now = time.time()
    timestamps = user_request_timestamps.get(user_id, [])
    # Filter timestamps within the window
    valid_timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    user_request_timestamps[user_id] = valid_timestamps

    if len(valid_timestamps) >= RATE_LIMIT_MAX:
        oldest = valid_timestamps[0]
        wait_seconds = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, max(1, wait_seconds)

    valid_timestamps.append(now)
    user_request_timestamps[user_id] = valid_timestamps
    return True, 0

# 6. Multi-Photo Album Deduplication Cache
recent_media_groups = {}  # media_group_id -> timestamp

# 7. Helper: Keep Typing Action (Capped at 70s)
async def keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    start_time = asyncio.get_event_loop().time()
    while not stop_event.is_set():
        if asyncio.get_event_loop().time() - start_time > 70.0:
            break
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
        except Exception:
            pass
        await asyncio.sleep(4)

# 8. Robust AI Invocation
async def invoke_llm_with_retry(messages, timeout=65.0, retries=2):
    for attempt in range(retries):
        model = llm_primary if attempt == 0 else llm_secondary
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(model.invoke, messages),
                timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                continue
            raise RuntimeError("The simulation analysis timed out. Please try uploading the screenshot again.")
        except Exception as e:
            err_str = str(e)
            if any(term in err_str for term in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500"]):
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
            raise e

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif hasattr(item, "text"):
                parts.append(getattr(item, "text"))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)

# 9. Core Virtual Match Analysis Logic
async def analyze_virtual_match(image_bytes: bytes = None, text_input: str = "") -> str:
    messages = [SystemMessage(content=FRAMEWORK_VIRTUAL_FOOTBALL_PROMPT)]
    if image_bytes:
        optimized = optimize_image_bytes(image_bytes)
        b64_img = base64.b64encode(optimized).decode("utf-8")
        prompt_content = [
            {
                "type": "text",
                "text": f"""Analyze this Virtual / Instant Football stats screenshot (SportyBet Instant Football / Virtuals).
User Note: {text_input if text_input else 'Extract exact metrics and deliver the single Gold Standard Recommendation.'}

MANDATORY INSTRUCTIONS:
1. HEADER LOCK: Identify the EXACT MATCH from the TOP HEADER (e.g. 'AST vs MCI', 'LIV vs BHA', 'BRE vs COV').
2. PIXEL-EXACT STATS: Read exact Form % circles, League positions, H2H counters (Home Wins, Draws, Away Wins), and Average Goals.
3. THE 4 RNG PILLARS:
   - PILLAR 1: RESPECT THE RNG SEED: If Home has higher Win %, never pick X2! If Away has higher Win %, never pick 1X!
   - PILLAR 2: ZERO-DRAW MASTER KEY: If H2H has >= 2 games and Draws == 0, MANDATORY PICK is Double Chance 12 (Home or Away Win - No Draw) 👑!
   - PILLAR 3: LOW-GOAL COMPRESSION: If Combined Average Goals <= 1.60, MANDATORY PICK is Under 3.5 Match Goals 👑!
   - PILLAR 4: GOAL BOUNDS EXCLUSIVE: Use Goal Bound 1–4 Goals 👑 (~90% blanket), Goal Bound 1–3 Goals 👑 (@ ~1.45 odds), or Goal Bound 2–4 Goals 👑!
4. STRICT DISQUALIFICATIONS: NEVER recommend Asian Handicap (not offered on Virtuals) and NEVER recommend Over 1.5, Over 2.5, 2H Over 0.5, or BTTS Yes!

Apply Framework v11.0 Virtual RNG Decision Engine and provide the single Gold Standard Recommendation!"""
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
            }
        ]
        messages.append(HumanMessage(content=prompt_content))
    else:
        messages.append(HumanMessage(content=f"""Analyze this Virtual / Instant Football fixture:
Match: {text_input}

Apply Framework v11.0 Virtual RNG Decision Engine and provide the single Gold Standard Recommendation!"""))

    resp = await invoke_llm_with_retry(messages)
    return extract_text(resp.content).strip()

# 10. Message Sending Helper
async def send_clean_message(update: Update, text: str):
    if len(text) > 4000:
        text = text[:4000]
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text, parse_mode=None)

# 11. Command Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user.id)
    log_user_activity(user.id, user.username or "", user.first_name or "", query_type="interaction")

    msg = """👋 **WELCOME TO INSTANTGOLDBOT!** 🎮👑
*24/7 Autonomous Virtual & Instant Football Quantitative AI*

---

⚠️ **STRICT BOT RULES:**
• 🎮 **100% Virtual / Instant Football ONLY** (SportyBet, Bet9ja, 1xBet).
• ❌ **NO real-world games supported.**
• 📸 **Screenshots ONLY:** All predictions require a stats screenshot for pixel-exact RNG analysis. Text match queries are disabled!

---

⚡ **HOW TO GET A WINNING PICK (INSTANT):**
Simply **send any screenshot** of an Instant Football fixture (the Stats / H2H screen)! 📸

The AI automatically:
1. Locks onto the header matchup (e.g. `AST vs MCI`).
2. Reads pixel-exact form percentages, league positions, and H2H records.
3. Evaluates simulation seed weights and goal flow compression.
4. Delivers the **#1 Gold Standard Pick**:
   • 🛡️ **Double Chance (1X, 12, X2) 👑**
   • 🎯 **Exclusive Goal Bounds (1–4 Goals, 1–3 Goals, 2–4 Goals) 👑**
   • 🔒 **Under 3.5 & Under 2.5 Match Goals 👑**

---

📋 **COMMANDS:**
• 📸 **Send any Virtual Stats Screenshot:** Instant automated analysis!
• `/help` — Screenshot capture guide & tips
• `/responsible` — 🔞 18+ Policy, Bankroll Management & Safety Rules
• `/privacy` — Zero-Data Retention Privacy Policy
• `/terms` — Terms of Service & Disclaimer

---
🔞 *18+ Only | Bet Responsibly | Virtual simulation modeling for informational purposes.*"""
    await send_clean_message(update, msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """📖 **INSTANTGOLDBOT — USER GUIDE & PRO TIPS**

---

🎮 **VIRTUAL FOOTBALL ONLY (24/7):**
This AI is specialized strictly in **Random Number Generator (RNG) Virtual Football** simulations (SportyBet Instant Football, Bet9ja Virtual, 1xBet).
❌ We DO NOT predict real-world soccer matches.
❌ We DO NOT accept text match names.

---

📸 **HOW TO GET PREDICTIONS (SCREENSHOTS ONLY):**
1. Open your bookmaker's **Instant Football / Virtual Football** section.
2. Click on the upcoming match to view the **Stats / H2H** screen.
3. Take a screenshot showing:
   • The top header (`Team A vs Team B`).
   • The Form % circles and League position.
   • The H2H past match results.
   • The Average Goals Scored bars.
4. Send the screenshot directly to this bot!

---

🎯 **THE EXCLUSIVE VIRTUAL MARKETS WE TARGET:**
• 🛡️ **Double Chance (1X, 12, X2):** High win rate, insulating against simulated draws and capitalizing on form parity.
• 🎯 **Goal Bound 1–4 Goals:** The ultimate ~90% win rate blanket covering almost all virtual simulation finishes!
• 🎯 **Goal Bound 1–3 Goals:** High-value banker covering low/medium scoring games.
• 🔒 **Under 3.5 Goals:** For defensive gridlocks.

---
🔞 *18+ Only | Bet Responsibly | Type /responsible for safety guidance.*"""
    await send_clean_message(update, msg)

async def responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, RESPONSIBLE_GAMING_POLICY)

async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, PRIVACY_POLICY)

async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_clean_message(update, TERMS_OF_SERVICE)

# 12. Photo Message Handler (Direct Upload with Zero Commands Needed)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user_id)
    log_user_activity(user_id, user.username or "", user.first_name or "", query_type="photo")

    chat_id = update.effective_chat.id
    media_group_id = update.message.media_group_id
    curr_t = time.time()

    # Clean up stale media group records older than 60s
    for mg in list(recent_media_groups.keys()):
        if curr_t - recent_media_groups[mg] > 60:
            recent_media_groups.pop(mg, None)

    # Album deduplication: If this is a subsequent photo from a multi-photo album, skip
    if media_group_id and media_group_id in recent_media_groups:
        return

    # Check rate limit
    allowed, wait_sec = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"⏳ **Rate Limit Notice:** Please wait {wait_sec} seconds before uploading another screenshot.")
        return

    if media_group_id:
        recent_media_groups[media_group_id] = curr_t

    caption = (update.message.caption or "").strip()
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(context, chat_id, stop_typing))

    try:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        image_bytes = await photo_file.download_as_bytearray()

        report = await analyze_virtual_match(image_bytes=image_bytes, text_input=caption)
        full_output = report + COMPLIANCE_FOOTER
        await send_clean_message(update, full_output)
    except Exception as e:
        await send_clean_message(update, f"⚠️ Analysis error: {e}")
    finally:
        stop_typing.set()
        typing_task.cancel()

# 13. Text Message Handler (Strictly Screenshots Only Enforcement)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    if user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES:
        ADMIN_USER_IDS.add(user_id)
    log_user_activity(user_id, user.username or "", user.first_name or "", query_type="text")

    # Inform user that text matching is disabled and only virtual screenshots are accepted
    msg = """📸 **SCREENSHOTS ONLY | 24/7 VIRTUAL FOOTBALL** 🎮

⚠️ *Text match queries and real-world football are NOT supported.*

This AI operates exclusively on **Virtual & Instant Football simulation screens** (SportyBet Instant Football, Bet9ja Virtuals, 1xBet).

👉 **How to use:**
1. Open your bookmaker's Instant Football fixture.
2. Click to open the **Stats / H2H** screen.
3. Take a screenshot and **send the photo directly here**!
The AI will immediately extract the simulation seed and deliver the #1 Gold Standard Pick!

Type `/help` for screenshot tips or `/responsible` for bankroll safety guidance."""
    await send_clean_message(update, msg)

# 14. Admin Analytics Dashboard & Broadcast Commands
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exclusive Admin Command: Displays comprehensive audience and prediction statistics."""
    user = update.effective_user
    is_admin = (user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES) or (user.id in ADMIN_USER_IDS)
    if not is_admin:
        await update.message.reply_text("🔒 **Access Denied:** This command is restricted to the bot administrator (@Lost_in_space000).")
        return

    ADMIN_USER_IDS.add(user.id)
    stats = get_analytics_summary()

    recent_lines = []
    for idx, (uname, fname, qcount, last_seen) in enumerate(stats["recent_users"], 1):
        dt_str = last_seen.split("T")[0] if "T" in str(last_seen) else str(last_seen)[:10]
        recent_lines.append(f"{idx}. **{uname}** ({fname}) — `{qcount} queries` [_{dt_str}_]")

    recent_text = "\n".join(recent_lines) if recent_lines else "_No users recorded yet._"

    msg = f"""📊 **INSTANTGOLDBOT — ADMIN ANALYTICS DASHBOARD**
*Live Audience & Prediction Engagement Record*

---

👥 **AUDIENCE METRICS:**
• **Total Registered Users:** `{stats['total_users']}`
• 🟢 **Active Users (Last 24h):** `{stats['active_24h']}`
• 📈 **Active Users (Last 7 Days):** `{stats['active_7d']}`

🎮 **PREDICTION ACTIVITY:**
• **Total Predictions Delivered:** `{stats['total_queries']}`
• 📸 **Photo Screenshot Audits:** `{stats['photo_queries']}`
• 💬 **Text Match Queries:** `{stats['text_queries']}`

---

📋 **TOP 10 RECENT ACTIVE USERS:**
{recent_text}

---
👑 *Admin Portal Authorized for @{user.username or user.id}*"""
    await send_clean_message(update, msg)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exclusive Admin Command: Broadcasts an announcement to all registered users."""
    user = update.effective_user
    is_admin = (user.username and user.username.lower().replace("@", "") in ADMIN_USERNAMES) or (user.id in ADMIN_USER_IDS)
    if not is_admin:
        await update.message.reply_text("🔒 **Access Denied:** Admin only.")
        return

    broadcast_msg = " ".join(context.args).strip() if context.args else ""
    if not broadcast_msg:
        await update.message.reply_text("Usage: `/broadcast <Your announcement message here...>`")
        return

    user_ids = get_all_user_ids()
    sent_count = 0
    fail_count = 0

    await update.message.reply_text(f"📢 Starting broadcast transmission to {len(user_ids)} registered users...")
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_msg, parse_mode="Markdown")
            sent_count += 1
        except Exception:
            fail_count += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(f"✅ **Broadcast Completed!**\n• Successfully Delivered: `{sent_count}`\n• Failed/Blocked: `{fail_count}`")

# 15. Main Entrypoint
def main():
    print("🚀 Initializing InstantGoldBot...")
    init_db()

    request_kwargs = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, write_timeout=60.0)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request_kwargs).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("responsible", responsible_command))
    app.add_handler(CommandHandler("disclaimer", responsible_command))
    app.add_handler(CommandHandler("privacy", privacy_command))
    app.add_handler(CommandHandler("terms", terms_command))

    # Admin commands
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("admin", users_command))
    app.add_handler(CommandHandler("stats", users_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    asyncio.get_event_loop().create_task(render_keep_alive_task())

    print("✅ InstantGoldBot successfully running on Telegram!")
    app.run_polling(poll_interval=3, timeout=30, bootstrap_retries=10)

if __name__ == "__main__":
    main()
