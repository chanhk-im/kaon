import discord


GREETING = """
안녕하세요! **Kaon Bot**이에요 👋

게임 공식 SNS의 새 소식을 자동으로 알려드릴게요.

**시작하는 방법**
1. `/subscribe` — 게임 이름과 YouTube·Reddit·RSS URL을 입력해 구독
2. `/subscriptions` — 현재 구독 목록 확인
3. `/help` — 전체 명령어 안내

궁금한 점이 있으면 `/help`를 입력해보세요!
""".strip()


def register(client: discord.Client):

    @client.event
    async def on_guild_join(guild: discord.Guild):
        channel = guild.system_channel
        if channel is None:
            channel = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
        if channel:
            await channel.send(GREETING)
