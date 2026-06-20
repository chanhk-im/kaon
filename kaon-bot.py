import discord
from discord import app_commands
from dotenv import load_dotenv
import os

from db import init_db
from features.rss import setup as rss_setup

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

check_feeds = rss_setup(client, tree, DEBUG)


@client.event
async def on_ready():
    print("▶ DB 초기화")
    init_db()
    await tree.sync()

    if not check_feeds.is_running():
        check_feeds.start()

    print(f"✅ 봇 로그인: {client.user} (ID: {client.user.id})")


if not TOKEN:
    raise RuntimeError(".env 파일에 DISCORD_BOT_TOKEN을 설정해주세요.")

print(f"▶ 봇 시작 (TOKEN 앞 10자: {TOKEN[:10]}...)")
client.run(TOKEN)
