import logging
import discord
from discord import app_commands
from dotenv import load_dotenv
import os

load_dotenv()
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

from logging_setup import setup_logging
setup_logging(DEBUG)

from db import init_db
from features.general import setup as general_setup
from features.rss import setup as rss_setup

log = logging.getLogger(__name__)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

general_setup(client, tree)
check_feeds = rss_setup(client, tree, DEBUG)


@client.event
async def on_ready():
    log.info("DB 초기화")
    init_db()
    await tree.sync()

    if not check_feeds.is_running():
        check_feeds.start()

    log.info("봇 로그인: %s (ID: %s)", client.user, client.user.id)


if not TOKEN:
    raise RuntimeError(".env 파일에 DISCORD_BOT_TOKEN을 설정해주세요.")

log.info("봇 시작 (TOKEN 앞 10자: %s...)", TOKEN[:10])
client.run(TOKEN)
