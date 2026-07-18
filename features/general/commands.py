import discord
from discord import app_commands


HELP_TEXT = """
**📋 명령어 목록**

**구독 관리**
`/games` — 구독 가능한 게임/서버 목록 확인

`/subscribe` — 게임 SNS 소식 구독
　• `game_name` : 구독할 게임 (목록에서 선택)
　• `server_name` : 구독할 서버 (목록에서 선택)
　• `channel` : 소식을 받을 채널 (기본값: 현재 채널)
　• `initial_count` : 구독 시 최근 몇 개를 바로 올릴지 (기본값: 5)

`/unsubscribe` — 구독 취소
　• `game_name` : 게임 이름
　• `server_name` : 서버 이름

`/set_channel` — 소식 받을 채널 변경
　• `game_name` : 게임 이름
　• `server_name` : 서버 이름
　• `channel` : 새 채널

`/subscriptions` — 현재 구독 목록 확인
""".strip()


def register(tree: app_commands.CommandTree):

    @tree.command(name="help", description="명령어 사용법을 안내합니다")
    async def cmd_help(interaction: discord.Interaction):
        embed = discord.Embed(description=HELP_TEXT, color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)
