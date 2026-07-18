import discord
from discord import app_commands
from discord.ext import tasks as ext_tasks

from features.rss.commands import register
from features.rss.tasks import create_check_feeds


def setup(client: discord.Client, tree: app_commands.CommandTree, debug: bool) -> ext_tasks.Loop:
    register(tree, client, debug)
    return create_check_feeds(client, debug)
