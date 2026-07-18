import asyncio
import logging
import re
import time
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
import feedparser

from db import get_db, run_db, update_last_sent_at

log = logging.getLogger(__name__)


async def _resolve_youtube_handle(handle: str) -> str | None:
    url = f"https://www.youtube.com/@{handle}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KaonBot/1.0)"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        m = re.search(r'"channelId":"(UC[\w-]+)"', html)
        return m.group(1) if m else None
    except Exception:
        return None


async def url_to_feed(url: str) -> tuple[str, str]:
    """URL을 (feed_url, source_type) 로 변환한다. 실패 시 ValueError."""
    url = url.strip().rstrip("/")

    if re.search(r"youtube\.com/feeds/videos\.xml", url):
        return url, "YouTube"

    m = re.search(r"youtube\.com/channel/(UC[\w-]+)", url)
    if m:
        cid = m.group(1)
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", "YouTube"

    m = re.search(r"youtube\.com/@([\w.-]+)", url)
    if m:
        handle = m.group(1)
        cid = await _resolve_youtube_handle(handle)
        if not cid:
            raise ValueError(
                f"YouTube @{handle} 채널 ID를 자동으로 찾지 못했습니다.\n"
                f"직접 채널 URL을 입력해주세요: `https://www.youtube.com/channel/UC...`"
            )
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", "YouTube"

    m = re.search(r"reddit\.com/r/([\w]+)", url)
    if m:
        sr = m.group(1)
        return f"https://www.reddit.com/r/{sr}/new.rss?sort=new", "Reddit"

    if re.search(r"\.(rss|xml|atom)(\?|$)", url, re.I) or "/rss" in url or "/feed" in url:
        return url, "RSS"

    raise ValueError(
        "지원하지 않는 URL 형식입니다.\n"
        "지원 형식: YouTube 채널/핸들 URL, Reddit 서브레딧 URL, RSS·Atom 피드 URL"
    )


def entry_published(entry) -> datetime | None:
    """feedparser entry의 발행 시각을 UTC datetime으로 반환. 없으면 None."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def _extract_entry_fields(entry, source_type: str) -> dict | None:
    """전송할 필드를 추출한다. 전송 불필요하면 None."""
    title = entry.get("title", "제목 없음")[:256]
    link = entry.get("link", "")

    if source_type == "YouTube":
        media = entry.get("media_thumbnail") or []
        thumbnail_url = media[0].get("url") if isinstance(media, list) and media else ""
        return {
            "source_type": "YouTube",
            "title": title,
            "link": link,
            "summary": "",
            "thumbnail_url": thumbnail_url,
            "published": entry_published(entry),
        }

    if source_type == "Reddit":
        tags = [t.get("term", "") for t in entry.get("tags", [])]
        if not any(t in ("Official", "Megathread", "Announcement") for t in tags):
            return None
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:300]
        return {
            "source_type": "Reddit",
            "title": title,
            "link": link,
            "summary": summary,
            "thumbnail_url": "",
        }

    summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:300]
    return {
        "source_type": source_type,
        "title": title,
        "link": link,
        "summary": summary,
        "thumbnail_url": "",
    }


def build_embed(fields: dict, game_name: str, server_name: str) -> discord.Embed:
    source_type = fields["source_type"]
    author = f"{game_name} ({server_name}) | {source_type}"

    now_utc = datetime.now(tz=timezone.utc)

    KST_OFFSET = timedelta(hours=9)

    if source_type == "YouTube":
        pub = (fields.get("published") or now_utc) + KST_OFFSET
        embed = discord.Embed(
            title=fields["title"], url=fields["link"],
            description="새 영상이 업로드됐어요!",
            color=0xFF0000, timestamp=pub,
        )
        embed.set_author(name=author)
        if fields.get("thumbnail_url"):
            embed.set_thumbnail(url=fields["thumbnail_url"])

    elif source_type == "Reddit":
        embed = discord.Embed(
            title=fields["title"], url=fields["link"], description=fields.get("summary", ""),
            color=0xFF4500, timestamp=now_utc,
        )
        embed.set_author(name=author)

    else:
        embed = discord.Embed(
            title=fields["title"], url=fields["link"], description=fields.get("summary", ""),
            color=0x5865F2, timestamp=now_utc,
        )
        embed.set_author(name=author)

    embed.set_footer(text="게임 공식 업데이트")
    return embed


async def send_new_entries(
    client: discord.Client,
    sub: dict,
    entries: list,
    last_sent_at: datetime | None,
    debug: bool = False,
    force_entries: list | None = None,
):
    """
    last_sent_at 이후 항목만 필터링해 Discord로 전송한다.
    force_entries가 주어지면 시간 필터 없이 해당 항목만 전송한다 (초기 구독용).
    """
    guild_id = sub["guild_id"]
    catalog_id = sub["catalog_id"]
    game_name = sub["game_name"]
    server_name = sub["server_name"]
    source_type = sub["source_type"]
    channel_id = sub["channel_id"]

    if force_entries is not None:
        to_send = [(e, entry_published(e) or datetime.now(tz=timezone.utc)) for e in force_entries]
    else:
        candidates = []
        for entry in entries:
            pub = entry_published(entry)
            if pub is None:
                continue
            if last_sent_at is None or pub > last_sent_at:
                candidates.append((entry, pub))
        to_send = sorted(candidates, key=lambda x: x[1])

    if not to_send:
        return

    channel = client.get_channel(int(channel_id))
    if not channel:
        try:
            channel = await client.fetch_channel(int(channel_id))
        except Exception as e:
            log.error("채널 fetch 실패 (channel_id=%s): %s", channel_id, e)
            return

    newest_sent_at: datetime | None = None
    for entry, pub in to_send:
        fields = _extract_entry_fields(entry, source_type)
        if not fields:
            newest_sent_at = max(newest_sent_at, pub) if newest_sent_at else pub
            continue

        try:
            embed = build_embed(fields, game_name, server_name)
            await channel.send(embed=embed)
            newest_sent_at = max(newest_sent_at, pub) if newest_sent_at else pub
            if debug:
                log.debug("전송 완료: %s(%s) / %s", game_name, server_name, fields["title"][:50])
            await asyncio.sleep(1)
        except Exception as e:
            log.error("Discord 전송 실패 %s(%s): %s", game_name, server_name, e)

    if newest_sent_at:
        await run_db(lambda: update_last_sent_at(guild_id, catalog_id, newest_sent_at))
