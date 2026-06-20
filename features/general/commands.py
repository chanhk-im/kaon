import discord
from discord import app_commands


HELP_TEXT = """
**📋 명령어 목록**

**구독 관리**
`/subscribe` — 게임 SNS 피드 구독
　• `game_name` : 게임 이름 (예: Wuthering Waves)
　• `url` : YouTube·Reddit·RSS URL
　• `channel` : 소식을 받을 채널 (기본값: 현재 채널)
　• `initial_count` : 구독 시 최근 몇 개를 바로 올릴지 (기본값: 5)

`/unsubscribe` — 구독 취소
　• `game_name` : 게임 이름
　• `url` : 특정 피드 URL (생략 시 해당 게임 전체 취소)

`/set_channel` — 소식 받을 채널 변경
　• `game_name` : 게임 이름
　• `channel` : 새 채널

`/subscriptions` — 현재 구독 목록 확인

**지원 URL 형식**
• YouTube 채널 URL / `@핸들` URL
• Reddit 서브레딧 URL (`reddit.com/r/...`)
• RSS·Atom 피드 URL
""".strip()


def register(tree: app_commands.CommandTree):

    @tree.command(name="help", description="명령어 사용법을 안내합니다")
    async def cmd_help(interaction: discord.Interaction):
        embed = discord.Embed(description=HELP_TEXT, color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)
