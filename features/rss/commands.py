import asyncio
import logging
import os

import discord
import feedparser
from discord import app_commands

from db import get_db, run_db
from features.rss import catalog
from features.rss.feed import url_to_feed, send_new_entries

log = logging.getLogger(__name__)

OWNER_IDS = {int(x) for x in os.getenv("BOT_OWNER_IDS", "").split(",") if x.strip()}


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


async def _check_owner(interaction: discord.Interaction) -> bool:
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message(
            "이 명령어는 Kaon 개발자만 사용할 수 있습니다.", ephemeral=True
        )
        return False
    return True


async def _game_name_autocomplete(interaction: discord.Interaction, current: str):
    names = await run_db(lambda: catalog.search_game_names(current))
    return [app_commands.Choice(name=n, value=n) for n in names]


async def _server_name_autocomplete(interaction: discord.Interaction, current: str):
    game_name = interaction.namespace.game_name
    if not game_name:
        return []
    names = await run_db(lambda: catalog.search_server_names(game_name, current))
    return [app_commands.Choice(name=n, value=n) for n in names]


def register(tree: app_commands.CommandTree, client: discord.Client, debug: bool):

    @tree.command(name="games", description="구독 가능한 게임/서버 목록을 확인합니다")
    async def cmd_games(interaction: discord.Interaction):
        if not await _check_command_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        rows = await run_db(catalog.list_all)
        if not rows:
            await interaction.followup.send("아직 등록된 게임이 없습니다.", ephemeral=True)
            return

        per_game: dict[str, dict[str, list[str]]] = {}
        for r in rows:
            servers = per_game.setdefault(r["game_name"], {})
            servers.setdefault(r["server_name"], []).append(r["source_type"])

        embed = discord.Embed(title="🕹️ 구독 가능한 게임 목록", color=0x5865F2)
        for game, servers in per_game.items():
            value = "\n".join(
                f"• {server} ({', '.join(sources)})" for server, sources in servers.items()
            )
            embed.add_field(name=game, value=value, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="subscribe", description="게임 SNS 소식을 구독합니다")
    @app_commands.describe(
        game_name="구독할 게임",
        server_name="구독할 서버",
        channel="소식을 받을 채널 (기본값: 현재 채널)",
        initial_count="구독 시 최근 몇 개를 바로 올릴지 (기본값: 5, 0이면 생략)",
    )
    @app_commands.autocomplete(game_name=_game_name_autocomplete, server_name=_server_name_autocomplete)
    async def cmd_subscribe(
        interaction: discord.Interaction,
        game_name: str,
        server_name: str,
        channel: discord.TextChannel | None = None,
        initial_count: int = 5,
    ):
        if not await _check_command_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel

        entries = await run_db(lambda: catalog.get_entries(game_name, server_name))
        if not entries:
            await interaction.followup.send(
                f"❌ '{game_name} / {server_name}' 조합을 찾을 수 없습니다. `/games`로 목록을 확인해주세요.",
                ephemeral=True,
            )
            return

        def _subscribe():
            conn = get_db()
            try:
                existing_ids = {r["catalog_id"] for r in conn.execute(
                    "SELECT catalog_id FROM subscriptions WHERE guild_id=?",
                    (str(interaction.guild_id),),
                ).fetchall()}
                new_entries = [e for e in entries if e["id"] not in existing_ids]
                if not new_entries:
                    return None
                for e in new_entries:
                    conn.execute(
                        "INSERT INTO subscriptions (guild_id, catalog_id) VALUES (?,?)",
                        (str(interaction.guild_id), e["id"]),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO channels (guild_id, game_name, server_name, channel_id) VALUES (?,?,?,?)",
                    (str(interaction.guild_id), game_name, server_name, str(target.id)),
                )
                conn.commit()
                return new_entries
            finally:
                conn.close()

        new_entries = await run_db(_subscribe)
        if new_entries is None:
            await interaction.followup.send("이미 구독 중인 게임/서버입니다.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ **{game_name} ({server_name})** 구독 완료! ({len(new_entries)}개 피드)\n📢 채널: {target.mention}",
            ephemeral=True,
        )

        if initial_count > 0:
            for entry in new_entries:
                try:
                    feed = await asyncio.to_thread(feedparser.parse, entry["feed_url"])
                    sub = {
                        "guild_id": str(interaction.guild_id),
                        "catalog_id": entry["id"],
                        "game_name": game_name,
                        "server_name": server_name,
                        "source_type": entry["source_type"],
                        "channel_id": str(target.id),
                    }
                    await send_new_entries(
                        client, sub, [], None, debug, force_entries=feed.entries[:initial_count]
                    )
                except Exception as e:
                    log.error("초기 피드 전송 실패 %s(%s): %s", game_name, server_name, e)

    @tree.command(name="unsubscribe", description="게임 SNS 구독을 취소합니다")
    @app_commands.describe(game_name="게임 이름", server_name="서버 이름")
    @app_commands.autocomplete(game_name=_game_name_autocomplete, server_name=_server_name_autocomplete)
    async def cmd_unsubscribe(
        interaction: discord.Interaction,
        game_name: str,
        server_name: str,
    ):
        if not await _check_command_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        def _unsubscribe():
            conn = get_db()
            try:
                deleted = conn.execute(
                    """
                    DELETE FROM subscriptions WHERE guild_id=? AND catalog_id IN (
                        SELECT id FROM game_catalog WHERE game_name=? AND server_name=?
                    )
                    """,
                    (str(interaction.guild_id), game_name, server_name),
                ).rowcount
                conn.execute(
                    "DELETE FROM channels WHERE guild_id=? AND game_name=? AND server_name=?",
                    (str(interaction.guild_id), game_name, server_name),
                )
                conn.commit()
                return deleted
            finally:
                conn.close()

        deleted = await run_db(_unsubscribe)

        if deleted:
            await interaction.followup.send(f"✅ **{game_name} ({server_name})** 구독 취소 완료!", ephemeral=True)
        else:
            await interaction.followup.send(
                f"**{game_name} ({server_name})** 구독 내역을 찾을 수 없습니다.", ephemeral=True
            )

    @tree.command(name="set_channel", description="게임 소식을 받을 채널을 변경합니다")
    @app_commands.describe(game_name="게임 이름", server_name="서버 이름", channel="소식을 받을 채널")
    @app_commands.autocomplete(game_name=_game_name_autocomplete, server_name=_server_name_autocomplete)
    async def cmd_set_channel(
        interaction: discord.Interaction,
        game_name: str,
        server_name: str,
        channel: discord.TextChannel,
    ):
        if not await _check_command_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        def _set_channel():
            conn = get_db()
            try:
                sub = conn.execute(
                    """
                    SELECT 1 FROM subscriptions WHERE guild_id=? AND catalog_id IN (
                        SELECT id FROM game_catalog WHERE game_name=? AND server_name=?
                    )
                    LIMIT 1
                    """,
                    (str(interaction.guild_id), game_name, server_name),
                ).fetchone()
                if not sub:
                    return False
                conn.execute(
                    "INSERT OR REPLACE INTO channels (guild_id, game_name, server_name, channel_id) VALUES (?,?,?,?)",
                    (str(interaction.guild_id), game_name, server_name, str(channel.id)),
                )
                conn.commit()
                return True
            finally:
                conn.close()

        found = await run_db(_set_channel)
        if not found:
            await interaction.followup.send(
                f"**{game_name} ({server_name})** 구독 내역이 없습니다. `/subscribe`로 먼저 구독해주세요.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ **{game_name} ({server_name})** 소식 채널 → {channel.mention}", ephemeral=True
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
                    SELECT gc.game_name, gc.server_name, gc.source_type, c.channel_id
                    FROM subscriptions s
                    JOIN game_catalog gc ON s.catalog_id = gc.id
                    LEFT JOIN channels c
                      ON s.guild_id = c.guild_id AND gc.game_name = c.game_name AND gc.server_name = c.server_name
                    WHERE s.guild_id = ?
                    ORDER BY gc.game_name, gc.server_name, gc.source_type
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
        groups: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["game_name"], r["server_name"])
            if key not in groups:
                groups[key] = {"sources": [], "channel_id": r["channel_id"]}
            groups[key]["sources"].append(r["source_type"])

        for (game, server), info in groups.items():
            ch = f"<#{info['channel_id']}>" if info["channel_id"] else "미설정"
            embed.add_field(
                name=f"{game} ({server})",
                value=f"피드: {', '.join(info['sources'])}\n채널: {ch}",
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

    @tree.command(name="catalog_add", description="[개발자] 게임 카탈로그에 피드를 등록합니다")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        game_name="게임 이름 (예: Wuthering Waves)",
        server_name="서버 이름 (예: Global, KR)",
        url="YouTube·Reddit·RSS URL",
    )
    @app_commands.autocomplete(game_name=_game_name_autocomplete, server_name=_server_name_autocomplete)
    async def cmd_catalog_add(
        interaction: discord.Interaction,
        game_name: str,
        server_name: str,
        url: str,
    ):
        if not await _check_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            feed_url, source_type = await url_to_feed(url)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        result = await run_db(lambda: catalog.add_entry(game_name, server_name, source_type, feed_url))
        if result == "duplicate":
            await interaction.followup.send("이미 카탈로그에 등록된 피드입니다.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ 카탈로그에 등록했습니다: **{game_name} ({server_name})** — {source_type}",
            ephemeral=True,
        )

    @tree.command(name="catalog_remove", description="[개발자] 게임 카탈로그에서 피드를 제거합니다")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        game_name="게임 이름",
        server_name="서버 이름",
        url="특정 피드 URL (생략 시 해당 게임/서버의 피드 전체 제거)",
    )
    @app_commands.autocomplete(game_name=_game_name_autocomplete, server_name=_server_name_autocomplete)
    async def cmd_catalog_remove(
        interaction: discord.Interaction,
        game_name: str,
        server_name: str,
        url: str | None = None,
    ):
        if not await _check_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        feed_url = None
        if url:
            try:
                feed_url, _ = await url_to_feed(url)
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return

        deleted = await run_db(lambda: catalog.remove_entries(game_name, server_name, feed_url))
        if deleted:
            await interaction.followup.send(
                f"✅ 카탈로그에서 제거했습니다: **{game_name} ({server_name})** ({deleted}개)", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"**{game_name} ({server_name})** 카탈로그 항목을 찾을 수 없습니다.", ephemeral=True
            )

    @tree.command(name="catalog_list", description="[개발자] 게임 카탈로그 전체를 확인합니다")
    @app_commands.default_permissions(administrator=True)
    async def cmd_catalog_list(interaction: discord.Interaction):
        if not await _check_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        rows = await run_db(catalog.list_all)
        if not rows:
            await interaction.followup.send("카탈로그가 비어 있습니다.", ephemeral=True)
            return

        embed = discord.Embed(title="📚 게임 카탈로그", color=0x5865F2)
        per_game: dict[str, dict[str, list[str]]] = {}
        for r in rows:
            servers = per_game.setdefault(r["game_name"], {})
            servers.setdefault(r["server_name"], []).append(f"[{r['source_type']}]({r['feed_url']})")

        for game, servers in per_game.items():
            value = "\n".join(
                f"• **{server}**: {', '.join(feeds)}" for server, feeds in servers.items()
            )
            embed.add_field(name=game, value=value, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
