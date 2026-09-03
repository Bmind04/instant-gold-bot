"""
Persistent SQLite User Analytics and Activity Tracker for InstantGoldBot.
Tracks unique users, engagement metrics, query volume, and active user trends.
"""

import sqlite3
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "user_tracker.db")

def init_db():
    """Initializes SQLite database tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        query_count INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS query_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query_type TEXT,
        timestamp TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def log_user_activity(user_id: int, username: str = "", first_name: str = "", query_type: str = "interaction"):
    """Logs user presence, updates last_seen, and increments query counts."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_username = f"@{username.strip()}" if username else "Anonymous"
    clean_first_name = (first_name or "").strip()[:50]

    is_prediction = query_type in ("photo", "predict", "text")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT user_id, query_count FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row:
            new_count = row[1] + (1 if is_prediction else 0)
            cursor.execute("""
            UPDATE users 
            SET username = ?, first_name = ?, last_seen = ?, query_count = ?
            WHERE user_id = ?
            """, (clean_username, clean_first_name, now, new_count, user_id))
        else:
            init_count = 1 if is_prediction else 0
            cursor.execute("""
            INSERT INTO users (user_id, username, first_name, first_seen, last_seen, query_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, clean_username, clean_first_name, now, now, init_count))

        if is_prediction:
            cursor.execute("""
            INSERT INTO query_logs (user_id, query_type, timestamp)
            VALUES (?, ?, ?)
            """, (user_id, query_type, now))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging user activity: {e}")

def get_analytics_summary() -> dict:
    """Extracts summary metrics for the Admin Dashboard."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Total Users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        now = datetime.datetime.now(datetime.timezone.utc)
        iso_24h_ago = (now - datetime.timedelta(hours=24)).isoformat()
        iso_7d_ago = (now - datetime.timedelta(days=7)).isoformat()

        # Active 24h
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (iso_24h_ago,))
        active_24h = cursor.fetchone()[0]

        # Active 7d
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (iso_7d_ago,))
        active_7d = cursor.fetchone()[0]

        # Total Queries
        cursor.execute("SELECT COUNT(*) FROM query_logs")
        total_queries = cursor.fetchone()[0]

        # Photo Queries
        cursor.execute("SELECT COUNT(*) FROM query_logs WHERE query_type = 'photo'")
        photo_queries = cursor.fetchone()[0]

        # Text Queries
        cursor.execute("SELECT COUNT(*) FROM query_logs WHERE query_type IN ('predict', 'text')")
        text_queries = cursor.fetchone()[0]

        # Recent 10 Users
        cursor.execute("""
        SELECT username, first_name, query_count, last_seen 
        FROM users 
        ORDER BY last_seen DESC 
        LIMIT 10
        """)
        recent_users = cursor.fetchall()

        conn.close()

        return {
            "total_users": total_users,
            "active_24h": active_24h,
            "active_7d": active_7d,
            "total_queries": total_queries,
            "photo_queries": photo_queries,
            "text_queries": text_queries,
            "recent_users": recent_users
        }
    except Exception as e:
        print(f"Error fetching analytics: {e}")
        return {
            "total_users": 0,
            "active_24h": 0,
            "active_7d": 0,
            "total_queries": 0,
            "photo_queries": 0,
            "text_queries": 0,
            "recent_users": []
        }

def get_all_user_ids() -> list[int]:
    """Retrieves all unique user IDs for broadcast announcements."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        user_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return user_ids
    except Exception as e:
        print(f"Error fetching user IDs for broadcast: {e}")
        return []
