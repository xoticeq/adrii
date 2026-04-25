import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import aiosqlite
from dotenv import load_dotenv
import database as db
from utils import fmt, C_INFO, C_SUCCESS, C_ERROR, C_GOLD, C_ORANGE, e_error, e_success, e_info

load_dotenv()

GUILD_ID            = int(os.getenv("GUILD_ID", 0))
SUBMISSIONS_CHANNEL = int(os.getenv("SUBMISSIONS_CHANNEL_ID", 0))
ADMIN_ROLE_ID       = int(os.getenv("ADMIN_ROLE_ID", 0))
HOST_ROLE_ID        = int(os.getenv("HOST_ROLE_ID", 0))

guild_obj = discord.Object(id=GUILD_ID)


class Tournament(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_host(self, interaction: discord.Interaction) -> bool:
        return any(r.id in (HOST_ROLE_ID, ADMIN_ROLE_ID) for r in interaction.user.roles)

    # ── /starttournament ──────────────────────────────────────────────────────

    @app_commands.command(name="starttournament", description="Seed a random bracket from current submissions.")
    @app_commands.guilds(guild_obj)
    async def starttournament(self, interaction: discord.Interaction):
        if not self.is_host(interaction):
            await interaction.response.send_message(embed=e_error("Hosts only."))
            return

        event = await db.get_active_event(interaction.guild.id)
        if not event:
            await interaction.response.send_message(embed=e_error("No active event."))
            return

        subs = await db.get_all_submissions(event["id"])
        if len(subs) < 2:
            await interaction.response.send_message(
                embed=e_error("Need at least 2 submissions to start a tournament.")
            )
            return

        players = [s["user_id"] for s in subs]
        random.shuffle(players)

        matches = []
        if len(players) % 2 != 0:
            bye_player = players.pop(0)
            matches.append({
                "event_id": event["id"], "round_number": 1,
                "player1_id": bye_player, "player2_id": None,
                "is_bye": 1, "status": "done",
            })

        for i in range(0, len(players), 2):
            matches.append({
                "event_id": event["id"], "round_number": 1,
                "player1_id": players[i], "player2_id": players[i + 1],
                "is_bye": 0, "status": "pending",
            })

        await db.create_bracket_matches(event["id"], matches)

        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("UPDATE events SET mode = 'tournament' WHERE id = ?", (event["id"],))
            await conn.commit()

        embed = await self.build_bracket_embed(interaction.guild, event["id"])
        channel = interaction.guild.get_channel(SUBMISSIONS_CHANNEL)
        if channel:
            await channel.send(embed=embed)

        await interaction.response.send_message(embed=e_success("Tournament bracket created."))

    # ── /nextmatch ────────────────────────────────────────────────────────────

    @app_commands.command(name="nextmatch", description="Open the next tournament matchup for submissions.")
    @app_commands.guilds(guild_obj)
    async def nextmatch(self, interaction: discord.Interaction):
        if not self.is_host(interaction):
            await interaction.response.send_message(embed=e_error("Hosts only."))
            return

        event = await db.get_active_event(interaction.guild.id)
        if not event:
            await interaction.response.send_message(embed=e_error("No active event."))
            return

        bracket = await db.get_bracket(event["id"])
        pending = [m for m in bracket if m["status"] == "pending"]
        if not pending:
            await interaction.response.send_message(
                embed=e_success("No more matches pending.")
            )
            return

        match = pending[0]
        await db.set_match_active(match["id"])

        p1 = interaction.guild.get_member(match["player1_id"])
        p2 = interaction.guild.get_member(match["player2_id"])
        p1m = p1.mention if p1 else f"<@{match['player1_id']}>"
        p2m = p2.mention if p2 else f"<@{match['player2_id']}>"

        channel = interaction.guild.get_channel(SUBMISSIONS_CHANNEL)
        if channel:
            embed = discord.Embed(
                title="Next Matchup",
                description=(
                    f"{p1m} **vs** {p2m}\n\n"
                    "Both players, submit your song now with `/submit` or by DMing the bot."
                ),
                color=C_ORANGE,
            )
            await channel.send(embed=embed)

        await interaction.response.send_message(embed=e_success("Next match opened."))

    # ── /bracket ──────────────────────────────────────────────────────────────

    @app_commands.command(name="bracket", description="Show the current tournament bracket.")
    @app_commands.guilds(guild_obj)
    async def bracket(self, interaction: discord.Interaction):
        event = await db.get_active_event(interaction.guild.id)
        if not event:
            await interaction.response.send_message(embed=e_error("No active event."))
            return
        embed = await self.build_bracket_embed(interaction.guild, event["id"])
        await interaction.response.send_message(embed=embed)

    # ── Bracket embed builder ─────────────────────────────────────────────────

    async def build_bracket_embed(self, guild: discord.Guild, event_id: int) -> discord.Embed:
        bracket = await db.get_bracket(event_id)
        if not bracket:
            return discord.Embed(title="No bracket yet.", color=C_INFO)

        rounds: dict[int, list] = {}
        for m in bracket:
            rounds.setdefault(m["round_number"], []).append(m)

        embed = discord.Embed(title="Tournament Bracket", color=C_ORANGE)

        for rnum, matches in sorted(rounds.items()):
            lines = ""
            for m in matches:
                p1 = guild.get_member(m["player1_id"])
                p1n = p1.display_name if p1 else f"User {m['player1_id']}"

                if m["is_bye"]:
                    lines += f"**{p1n}** got a bye\n"
                    continue

                p2 = guild.get_member(m["player2_id"]) if m["player2_id"] else None
                p2n = p2.display_name if p2 else f"User {m['player2_id']}"

                if m["status"] == "done" and m["winner_id"]:
                    winner_is_p1 = m["winner_id"] == m["player1_id"]
                    winner_n = p1n if winner_is_p1 else p2n
                    loser_n  = p2n if winner_is_p1 else p1n
                    lines += f"**{winner_n}** def. ~~{loser_n}~~\n"
                elif m["status"] == "active":
                    lines += f"**{p1n}** vs **{p2n}** (scoring now)\n"
                else:
                    lines += f"{p1n} vs {p2n}\n"

            embed.add_field(name=f"Round {rnum}", value=lines or "nothing yet", inline=False)

        return embed

    # ── Match resolver (called by Rounds cog) ─────────────────────────────────

    async def resolve_match(self, guild: discord.Guild, event: dict):
        active_match = await db.get_active_match(event["id"])
        if not active_match or active_match["is_bye"]:
            return

        p1_sub = await db.get_submission_by_user(event["id"], active_match["player1_id"])
        p2_sub = await db.get_submission_by_user(event["id"], active_match["player2_id"])
        if not p1_sub or not p2_sub:
            return

        p1_scores = await db.get_scores_for_submission(p1_sub["id"])
        p2_scores = await db.get_scores_for_submission(p2_sub["id"])
        if not p1_scores or not p2_scores:
            return

        p1_avg = sum(s["score"] for s in p1_scores) / len(p1_scores)
        p2_avg = sum(s["score"] for s in p2_scores) / len(p2_scores)
        channel = guild.get_channel(SUBMISSIONS_CHANNEL)

        if p1_avg == p2_avg:
            from state import state
            state["sudden_death"] = True
            p1 = guild.get_member(active_match["player1_id"])
            p2 = guild.get_member(active_match["player2_id"])
            embed = discord.Embed(
                title="Sudden Death",
                description=(
                    f"It's a tie between {p1.mention if p1 else 'Player 1'} "
                    f"and {p2.mention if p2 else 'Player 2'}.\n\n"
                    "Both players, submit a new song now."
                ),
                color=C_ERROR,
            )
            if channel:
                await channel.send(embed=embed)
        else:
            winner_id = active_match["player1_id"] if p1_avg > p2_avg else active_match["player2_id"]
            await db.set_match_winner(active_match["id"], winner_id)
            winner = guild.get_member(winner_id)

            bracket_embed = await self.build_bracket_embed(guild, event["id"])
            winner_embed = discord.Embed(
                title="Match Result",
                description=f"{winner.mention if winner else 'Winner'} advances to the next round.",
                color=C_GOLD,
            )
            if channel:
                await channel.send(embeds=[winner_embed, bracket_embed])


async def setup(bot: commands.Bot):
    await bot.add_cog(Tournament(bot))