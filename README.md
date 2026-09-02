# 🎮 InstantGoldBot — 24/7 Virtual Football Quantitative AI

An autonomous, production-ready Telegram bot dedicated exclusively to **Virtual and Instant Football** prediction modeling (SportyBet Instant Football, Bet9ja Virtuals, 1xBet).

## 🚀 Key Features
- **Frictionless Screenshot Analysis:** Users just drop a screenshot of the Stats/H2H screen — no commands needed!
- **Pillow Image Compression:** Automatically compresses and downscales high-res screenshots to ~80 KB for sub-5 second responses.
- **RNG Simulation Modeling:** Features the 4 Pillars of Virtual RNG Mechanics, Zero-Draw Master Key, and Zero Overs Law.
- **Exclusive Goal Bounds:** Recommends high-win Goal Bounds (1–4 Goals, 1–3 Goals, 2–4 Goals).
- **Anti-Spam Rate Limiter:** Per-user rate limiting prevents API abuse.
- **Multi-Photo Deduplication:** Smart album caching prevents duplicate replies.
- **Full Responsible Gaming & Compliance:** Comprehensive 18+ policy (`/responsible`), Privacy Policy (`/privacy`), Terms (`/terms`), and footers.

## 🛠️ Setup & Deployment
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure `.env`:
   ```env
   TELEGRAM_TOKEN="your_bot_token"
   GEMINI_API_KEY="your_gemini_api_key"
   PORT=8080
   ```
3. Run locally:
   ```bash
   python main.py
   ```
