import discord
from discord.ext import commands
from discord import app_commands
import os
import datetime
from dotenv import load_dotenv
import database as db
from utils import fmt, C_INFO, C_GOLD, e_info

load_dotenv()

GUILD_ID  = int(os.getenv("GUILD_ID", 0))
guild_obj = discord.Object(id=GUILD_ID)


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /leaderboard ──────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="Show the all-time leaderboard.")
    @app_commands.guilds(guild_obj)
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await db.get_leaderboard(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(embed=e_info("No data yet."))
            return

        places = ["1st", "2nd", "3rd"]
        lines = ""
        for i, r in enumerate(rows[:10]):
            place = places[i] if i < 3 else f"{i + 1}th"
            wins   = r["wins"]
            losses = r["losses"]
            total  = wins + losses
            ratio  = f"{wins}/{losses} W/L" if total > 0 else "no matches"
            lines += (
                f"`{place}` <@{r['user_id']}> | avg **{fmt(r['avg_score'])}/10** "
                f"({r['total_submissions']} songs) | {ratio}\n"
            )

        embed = discord.Embed(title="All-Time Leaderboard", description=lines, color=C_GOLD)
        await interaction.response.send_message(embed=embed)

    # ── /history ──────────────────────────────────────────────────────────────

    @app_commands.command(name="history", description="Show past events.")
    @app_commands.guilds(guild_obj)
    async def history(self, interaction: discord.Interaction):
        events = await db.get_all_events(interaction.guild.id)
        if not events:
            await interaction.response.send_message(embed=e_info("No events yet."))
            return

        lines = ""
        for e in events[:15]:
            status = "open" if e["status"] == "open" else "closed"
            dt = datetime.datetime.fromisoformat(e["created_at"])
            lines += f"`{e['id']}` {e['name']} ({e['mode']}) {status} <t:{int(dt.timestamp())}:d>\n"

        embed = discord.Embed(title="Event History", description=lines, color=C_INFO)
        await interaction.response.send_message(embed=embed)

    # ── /mystats ──────────────────────────────────────────────────────────────

    @app_commands.command(name="mystats", description="Show your personal stats.")
    @app_commands.guilds(guild_obj)
    async def mystats(self, interaction: discord.Interaction):
        stats = await db.get_user_stats(interaction.guild.id, interaction.user.id)
        if not stats:
            await interaction.response.send_message(
                embed=e_info("You haven't been scored in any events yet.")
            )
            return

        wins   = stats["wins"]
        losses = stats["losses"]
        total  = wins + losses
        ratio  = f"{wins}/{losses}" if total > 0 else "no matches yet"

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Stats",
            color=C_INFO,
        )
        embed.add_field(name="Songs submitted", value=str(stats["total_submissions"]), inline=True)
        embed.add_field(name="Average score",   value=f"{fmt(stats['avg_score'])}/10",    inline=True)
        embed.add_field(name="Best score",      value=f"{fmt(stats['best_score'])}/10",   inline=True)
        embed.add_field(name="Lowest score",    value=f"{fmt(stats['lowest_score'])}/10", inline=True)
        embed.add_field(name="W/L",             value=ratio,                              inline=True)
        if total > 0:
            pct = round((wins / total) * 100)
            embed.add_field(name="Win rate", value=f"{pct}%", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))