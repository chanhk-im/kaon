import discord
from discord import app_commands

from features.general.commands import register as register_commands
from features.general.events import register as register_events


def setup(client: discord.Client, tree: app_commands.CommandTree):
    register_commands(tree)
    register_events(client)
