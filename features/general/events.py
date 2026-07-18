import discord


GREETING = """
안녕하세요! **Kaon Bot**이에요 👋

게임 공식 SNS의 새 소식을 자동으로 알려드릴게요.

**시작하는 방법**
1. `/games` — 구독 가능한 게임/서버 목록 확인
2. `/subscribe` — 게임과 서버를 선택해 구독
3. `/subscriptions` — 현재 구독 목록 확인
4. `/help` — 전체 명령어 안내

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
