import asyncio
import logging
from datetime import datetime, timezone

import discord
import feedparser
from discord.ext import tasks

from db import get_db, run_db
from features.rss.feed import send_new_entries

log = logging.getLogger(__name__)


def create_check_feeds(client: discord.Client, debug: bool):

    @tasks.loop(minutes=10)
    async def check_feeds():
        if debug:
            log.debug("피드 체크 중...")

        def _get_subs():
            conn = get_db()
            try:
                return [dict(r) for r in conn.execute(
                    """
                    SELECT s.guild_id, s.catalog_id, s.last_sent_at,
                           gc.game_name, gc.server_name, gc.source_type, gc.feed_url,
                           ch.channel_id
                    FROM subscriptions s
                    JOIN game_catalog gc ON s.catalog_id = gc.id
                    LEFT JOIN channels ch
                      ON s.guild_id = ch.guild_id
                     AND gc.game_name = ch.game_name
                     AND gc.server_name = ch.server_name
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
                log.error("피드 처리 실패 %s(%s): %s", sub["game_name"], sub["server_name"], e)

    return check_feeds
