import asyncio
import sqlite3
from datetime import datetime, timezone
import os

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "."), "kaon.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


async def run_db(fn):
    """동기 DB 작업을 스레드풀에서 실행해 이벤트 루프 블로킹을 방지한다."""
    return await asyncio.to_thread(fn)


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id     TEXT NOT NULL,
            game_name    TEXT NOT NULL,
            source_type  TEXT NOT NULL,
            feed_url     TEXT NOT NULL,
            last_sent_at TEXT,
            UNIQUE(guild_id, feed_url)
        );
        CREATE TABLE IF NOT EXISTS channels (
            guild_id    TEXT NOT NULL,
            game_name   TEXT NOT NULL,
            channel_id  TEXT NOT NULL,
            PRIMARY KEY(guild_id, game_name)
        );
        CREATE TABLE IF NOT EXISTS command_channels (
            guild_id    TEXT NOT NULL,
            channel_id  TEXT NOT NULL,
            PRIMARY KEY(guild_id, channel_id)
        );
    """)
    conn.close()


def get_last_sent_at(guild_id: str, feed_url: str) -> datetime | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT last_sent_at FROM subscriptions WHERE guild_id=? AND feed_url=?",
            (guild_id, feed_url),
        ).fetchone()
        if row and row["last_sent_at"]:
            return datetime.fromisoformat(row["last_sent_at"]).replace(tzinfo=timezone.utc)
        return None
    finally:
        conn.close()


def update_last_sent_at(guild_id: str, feed_url: str, dt: datetime):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE subscriptions SET last_sent_at=? WHERE guild_id=? AND feed_url=?",
            (dt.replace(tzinfo=None).isoformat(), guild_id, feed_url),
        )
        conn.commit()
    finally:
        conn.close()
