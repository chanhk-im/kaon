import asyncio
import re
import sqlite3
import time
from datetime import datetime, timezone

import aiohttp
import discord
import feedparser
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "."), "kaon.db")

# ── DB ──────────────────────────────────────────────────────────────────

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
    """)
    conn.close()


def _get_last_sent_at(guild_id: str, feed_url: str) -> datetime | None:
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


def _update_last_sent_at(guild_id: str, feed_url: str, dt: datetime):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE subscriptions SET last_sent_at=? WHERE guild_id=? AND feed_url=?",
            (dt.replace(tzinfo=None).isoformat(), guild_id, feed_url),
        )
        conn.commit()
    finally:
        conn.close()


# ── URL → RSS 변환 ────────────────────────────────────────────────────

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


# ── 피드 파싱 ─────────────────────────────────────────────────────────

def _entry_published(entry) -> datetime | None:
    """feedparser entry의 발행 시각을 UTC datetime으로 반환. 없으면 None."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def _extract_entry_fields(entry, source_type: str) -> dict | None:
    """전송할 필드를 추출한다. 전송 불필요하면 None."""
    entry_id = entry.get("id") or entry.get("link", "")
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
            "published": _entry_published(entry),
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


def _build_embed(fields: dict, game_name: str) -> discord.Embed:
    source_type = fields["source_type"]

    if source_type == "YouTube":
        pub = fields.get("published") or datetime.utcnow()
        embed = discord.Embed(
            title=fields["title"], url=fields["link"],
            description="새 영상이 업로드됐어요!",
            color=0xFF0000, timestamp=pub,
        )
        embed.set_author(name=f"{game_name} | YouTube")
        if fields.get("thumbnail_url"):
            embed.set_thumbnail(url=fields["thumbnail_url"])

    elif source_type == "Reddit":
        embed = discord.Embed(
            title=fields["title"], url=fields["link"], description=fields.get("summary", ""),
            color=0xFF4500, timestamp=datetime.utcnow(),
        )
        embed.set_author(name=f"{game_name} | Reddit")

    else:
        embed = discord.Embed(
            title=fields["title"], url=fields["link"], description=fields.get("summary", ""),
            color=0x5865F2, timestamp=datetime.utcnow(),
        )
        embed.set_author(name=f"{game_name} | {source_type}")

    embed.set_footer(text="게임 공식 업데이트")
    return embed


async def _send_new_entries(
    sub: dict,
    entries: list,
    last_sent_at: datetime | None,
    force_entries: list | None = None,
):
    """
    last_sent_at 이후 항목만 필터링해 Discord로 전송한다.
    force_entries가 주어지면 시간 필터 없이 해당 항목만 전송한다 (초기 구독용).
    """
    guild_id = sub["guild_id"]
    feed_url = sub["feed_url"]
    game_name = sub["game_name"]
    source_type = sub["source_type"]
    channel_id = sub["channel_id"]

    if force_entries is not None:
        to_send = [(e, _entry_published(e) or datetime.now(tz=timezone.utc)) for e in force_entries]
    else:
        candidates = []
        for entry in entries:
            pub = _entry_published(entry)
            if pub is None:
                continue
            if last_sent_at is None or pub > last_sent_at:
                candidates.append((entry, pub))
        # 오래된 순으로 전송
        to_send = sorted(candidates, key=lambda x: x[1])

    if not to_send:
        return

    channel = client.get_channel(int(channel_id))
    if not channel:
        try:
            channel = await client.fetch_channel(int(channel_id))
        except Exception as e:
            print(f"[ERROR] 채널 fetch 실패 (channel_id={channel_id}): {e}")
            return

    newest_sent_at: datetime | None = None
    for entry, pub in to_send:
        fields = _extract_entry_fields(entry, source_type)
        if not fields:
            newest_sent_at = max(newest_sent_at, pub) if newest_sent_at else pub
            continue

        try:
            embed = _build_embed(fields, game_name)
            await channel.send(embed=embed)
            newest_sent_at = max(newest_sent_at, pub) if newest_sent_at else pub
            print(f"[FEED] 전송 완료: {game_name} / {fields['title'][:50]}")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[ERROR] Discord 전송 실패 {game_name}: {e}")

    if newest_sent_at:
        await run_db(lambda: _update_last_sent_at(guild_id, feed_url, newest_sent_at))


# ── Discord 봇 설정 ───────────────────────────────────────────────────

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ── 슬래시 커맨드 ─────────────────────────────────────────────────────

@tree.command(name="subscribe", description="게임 SNS 피드를 구독합니다")
@app_commands.describe(
    game_name="게임 이름 (예: Wuthering Waves)",
    url="YouTube·Reddit·RSS URL",
    channel="소식을 받을 채널 (기본값: 현재 채널)",
    initial_count="구독 시 최근 몇 개를 바로 올릴지 (기본값: 5, 0이면 생략)",
)
async def cmd_subscribe(
    interaction: discord.Interaction,
    game_name: str,
    url: str,
    channel: discord.TextChannel | None = None,
    initial_count: int = 5,
):
    await interaction.response.defer(ephemeral=True)
    target = channel or interaction.channel

    try:
        feed_url, source_type = await url_to_feed(url)
    except ValueError as e:
        await interaction.followup.send(f"❌ {e}", ephemeral=True)
        return

    def _subscribe():
        conn = get_db()
        try:
            exists = conn.execute(
                "SELECT id FROM subscriptions WHERE guild_id=? AND feed_url=?",
                (str(interaction.guild_id), feed_url),
            ).fetchone()
            if exists:
                return "duplicate"
            conn.execute(
                "INSERT INTO subscriptions (guild_id, game_name, source_type, feed_url) VALUES (?,?,?,?)",
                (str(interaction.guild_id), game_name, source_type, feed_url),
            )
            conn.execute(
                "INSERT OR IGNORE INTO channels (guild_id, game_name, channel_id) VALUES (?,?,?)",
                (str(interaction.guild_id), game_name, str(target.id)),
            )
            conn.commit()
            return "ok"
        finally:
            conn.close()

    result = await run_db(_subscribe)
    if result == "duplicate":
        await interaction.followup.send("이미 구독 중인 피드입니다.", ephemeral=True)
        return

    await interaction.followup.send(
        f"✅ **{game_name}** ({source_type}) 구독 완료!\n📢 채널: {target.mention}",
        ephemeral=True,
    )

    if initial_count > 0:
        try:
            feed = await asyncio.to_thread(feedparser.parse, feed_url)
            sub = {
                "guild_id": str(interaction.guild_id),
                "game_name": game_name,
                "source_type": source_type,
                "feed_url": feed_url,
                "channel_id": str(target.id),
            }
            await _send_new_entries(sub, [], None, force_entries=feed.entries[:initial_count])
        except Exception as e:
            print(f"[ERROR] 초기 피드 전송 실패 {game_name}: {e}")


@tree.command(name="unsubscribe", description="게임 SNS 구독을 취소합니다")
@app_commands.describe(
    game_name="게임 이름",
    url="특정 피드 URL (생략 시 해당 게임 전체 취소)",
)
async def cmd_unsubscribe(
    interaction: discord.Interaction,
    game_name: str,
    url: str | None = None,
):
    await interaction.response.defer(ephemeral=True)

    if url:
        try:
            feed_url, _ = await url_to_feed(url)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
    else:
        feed_url = None

    def _unsubscribe():
        conn = get_db()
        try:
            if feed_url:
                deleted = conn.execute(
                    "DELETE FROM subscriptions WHERE guild_id=? AND game_name=? AND feed_url=?",
                    (str(interaction.guild_id), game_name, feed_url),
                ).rowcount
            else:
                deleted = conn.execute(
                    "DELETE FROM subscriptions WHERE guild_id=? AND game_name=?",
                    (str(interaction.guild_id), game_name),
                ).rowcount
                conn.execute(
                    "DELETE FROM channels WHERE guild_id=? AND game_name=?",
                    (str(interaction.guild_id), game_name),
                )
            conn.commit()
            return deleted
        finally:
            conn.close()

    deleted = await run_db(_unsubscribe)

    if deleted:
        await interaction.followup.send(f"✅ **{game_name}** 구독 취소 완료!", ephemeral=True)
    else:
        await interaction.followup.send(
            f"**{game_name}** 구독 내역을 찾을 수 없습니다.", ephemeral=True
        )


@tree.command(name="set_channel", description="게임 소식을 받을 채널을 변경합니다")
@app_commands.describe(game_name="게임 이름", channel="소식을 받을 채널")
async def cmd_set_channel(
    interaction: discord.Interaction,
    game_name: str,
    channel: discord.TextChannel,
):
    await interaction.response.defer(ephemeral=True)

    def _set_channel():
        conn = get_db()
        try:
            sub = conn.execute(
                "SELECT 1 FROM subscriptions WHERE guild_id=? AND game_name=?",
                (str(interaction.guild_id), game_name),
            ).fetchone()
            if not sub:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO channels (guild_id, game_name, channel_id) VALUES (?,?,?)",
                (str(interaction.guild_id), game_name, str(channel.id)),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    found = await run_db(_set_channel)
    if not found:
        await interaction.followup.send(
            f"**{game_name}** 구독 내역이 없습니다. `/subscribe`로 먼저 구독해주세요.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ **{game_name}** 소식 채널 → {channel.mention}", ephemeral=True
    )


@tree.command(name="subscriptions", description="현재 구독 목록을 확인합니다")
async def cmd_subscriptions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    def _list():
        conn = get_db()
        try:
            return conn.execute(
                """
                SELECT s.game_name, s.source_type, s.feed_url, c.channel_id
                FROM subscriptions s
                LEFT JOIN channels c
                  ON s.guild_id = c.guild_id AND s.game_name = c.game_name
                WHERE s.guild_id = ?
                ORDER BY s.game_name, s.source_type
                """,
                (str(interaction.guild_id),),
            ).fetchall()
        finally:
            conn.close()

    rows = await run_db(_list)

    if not rows:
        await interaction.followup.send(
            "구독 중인 게임이 없습니다. `/subscribe`로 추가해보세요!", ephemeral=True
        )
        return

    embed = discord.Embed(title="🎮 게임 구독 목록", color=0x5865F2)
    games: dict[str, dict] = {}
    for r in rows:
        g = r["game_name"]
        if g not in games:
            games[g] = {"feeds": [], "channel_id": r["channel_id"]}
        games[g]["feeds"].append((r["source_type"], r["feed_url"]))

    for game, info in games.items():
        ch = f"<#{info['channel_id']}>" if info["channel_id"] else "미설정"
        feeds_str = "\n".join(
            f"• [{src}]({url})" for src, url in info["feeds"]
        )
        embed.add_field(
            name=game,
            value=f"{feeds_str}\n채널: {ch}",
            inline=False,
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


# ── 피드 폴링 ─────────────────────────────────────────────────────────

@tasks.loop(minutes=10)
async def check_feeds():
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
            await _send_new_entries(sub, feed.entries, last_sent_at)
        except Exception as e:
            print(f"[ERROR] 피드 처리 실패 {sub['game_name']}: {e}")


# ── 봇 시작 ──────────────────────────────────────────────────────────

@client.event
async def on_ready():
    print("▶ on_ready 시작")
    print("▶ DB 초기화")
    init_db()
    print("▶ 슬래시 커맨드 동기화 중...")
    await tree.sync()
    print("✅ 슬래시 커맨드 동기화 완료")

    if not check_feeds.is_running():
        check_feeds.start()

    print(f"✅ 봇 로그인: {client.user} (ID: {client.user.id})")


if not TOKEN:
    raise RuntimeError(".env 파일에 DISCORD_BOT_TOKEN을 설정해주세요.")

print(f"▶ 봇 시작 (TOKEN 앞 10자: {TOKEN[:10]}...)")
client.run(TOKEN)
