"""
InstantGoldBot — PAUSED (Standby Mode).
All production and Gemini API quota is dedicated to the primary bot (sports-ai-agent / @BrightLiveBot).
"""

import os
import time
import http.server
import socketserver


def main():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    print(f"⏸️ InstantGoldBot is PAUSED. Healthcheck server standing by on port {port} (zero Telegram polling / zero token usage).")
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"Standby loop notice: {e}")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
