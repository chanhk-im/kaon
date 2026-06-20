import asyncio
from datetime import datetime, timezone

import discord
import feedparser
from discord.ext import tasks

from db import get_db, run_db
from features.rss.feed import send_new_entries


def create_check_feeds(client: discord.Client, debug: bool):

    @tasks.loop(minutes=10)
    async def check_feeds():
        if debug:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 피드 체크 중...")

        def _get_subs():
            conn = get_db()
            try:
                return [dict(r) for r in conn.execute(
                    """
                    SELECT s.guild_id, s.game_name, s.source_type, s.feed_url,
                           s.last_sent_at, c.channel_id
                    FROM subscriptions s
                    LEFT JOIN channels c
                      ON s.guild_id = c.guild_id AND s.game_name = c.game_name
                    """
                ).fetchall()]
            finally:
                conn.close()

        rows = await run_db(_get_subs)

        for sub in rows:
            if not sub["channel_id"]:
                continue
            last_sent_at = (
                datetime.fromisoformat(sub["last_sent_at"]).replace(tzinfo=timezone.utc)
                if sub["last_sent_at"] else None
            )
            try:
                feed = await asyncio.to_thread(feedparser.parse, sub["feed_url"])
                await send_new_entries(client, sub, feed.entries, last_sent_at, debug)
            except Exception as e:
                print(f"[ERROR] 피드 처리 실패 {sub['game_name']}: {e}")

    return check_feeds
