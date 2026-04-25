import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import database as db
from utils import e_error, e_success

load_dotenv()

GUILD_ID  = int(os.getenv("GUILD_ID", 0))
guild_obj = discord.Object(id=GUILD_ID)


def parse_hex(hex_str: str) -> int | None:
    hex_str = hex_str.strip().lstrip("#")
    try:
        val = int(hex_str, 16)
        if 0 <= val <= 0xFFFFFF:
            return val
        return None
    except ValueError:
        return None


class EmbedColor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator

    @app_commands.command(name="embedcolor", description="Change the color of all bot embeds.")
    @app_commands.describe(color="Hex color code, e.g. #FF0000 or FF0000")
    @app_commands.guilds(guild_obj)
    async def embedcolor(self, interaction: discord.Interaction, color: str):
        if not self.is_admin(interaction):
            await interaction.response.send_message(embed=e_error("You need Administrator permission to change embed colors."))
            return

        hex_val = parse_hex(color)
        if hex_val is None:
            await interaction.response.send_message(embed=e_error("Invalid hex color. Use a format like `#FF0000` or `FF0000`."))
            return

        await db.set_guild_color(interaction.guild.id, hex_val)

        embed = discord.Embed(
            description=f"Embed color updated to `#{hex_val:06X}`.",
            color=hex_val,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedColor(bot))