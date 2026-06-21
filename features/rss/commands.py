import asyncio
import logging

import discord
import feedparser
from discord import app_commands

from db import get_db, run_db
from features.rss.feed import url_to_feed, send_new_entries

log = logging.getLogger(__name__)


async def _check_command_channel(interaction: discord.Interaction) -> bool:
    """허용된 채널 목록이 있으면 현재 채널이 포함됐는지 확인한다. 없으면 통과."""
    def _query():
        conn = get_db()
        try:
            return [r["channel_id"] for r in conn.execute(
                "SELECT channel_id FROM command_channels WHERE guild_id=?",
                (str(interaction.guild_id),),
            ).fetchall()]
        finally:
            conn.close()

    allowed = await run_db(_query)
    if not allowed or str(interaction.channel_id) not in allowed:
        msg = "이 채널에서는 명령어를 사용할 수 없습니다."
        if allowed:
            mentions = " ".join(f"<#{cid}>" for cid in allowed)
            msg += f"\n사용 가능한 채널: {mentions}"
        await interaction.response.send_message(msg, ephemeral=True)
        return False
    return True


def register(tree: app_commands.CommandTree, client: discord.Client, debug: bool):

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
        if not await _check_command_channel(interaction):
            return
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
                await send_new_entries(client, sub, [], None, debug, force_entries=feed.entries[:initial_count])
            except Exception as e:
                log.error("초기 피드 전송 실패 %s: %s", game_name, e)

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
        if not await _check_command_channel(interaction):
            return
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
        if not await _check_command_channel(interaction):
            return
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
        if not await _check_command_channel(interaction):
            return
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

    @tree.command(name="channel", description="Kaon 명령어를 사용할 수 있는 채널을 등록/해제합니다")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="등록하거나 해제할 채널 (이미 등록됐으면 해제)")
    async def cmd_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        def _toggle():
            conn = get_db()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM command_channels WHERE guild_id=? AND channel_id=?",
                    (str(interaction.guild_id), str(channel.id)),
                ).fetchone()
                if exists:
                    conn.execute(
                        "DELETE FROM command_channels WHERE guild_id=? AND channel_id=?",
                        (str(interaction.guild_id), str(channel.id)),
                    )
                    conn.commit()
                    return "removed"
                else:
                    conn.execute(
                        "INSERT INTO command_channels (guild_id, channel_id) VALUES (?,?)",
                        (str(interaction.guild_id), str(channel.id)),
                    )
                    conn.commit()
                    return "added"
            finally:
                conn.close()

        result = await run_db(_toggle)
        if result == "added":
            await interaction.followup.send(
                f"✅ {channel.mention} 채널에서 Kaon 명령어를 사용할 수 있습니다.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"🗑️ {channel.mention} 채널 등록을 해제했습니다.", ephemeral=True
            )
