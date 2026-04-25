import discord
from discord.ext import commands
from discord import app_commands
import os
from pathlib import Path
from dotenv import load_dotenv
import database as db
from state import state
from utils import (
    ALLOWED_EXT, C_INFO, C_SUCCESS, C_ERROR, C_GOLD,
    fmt, parse_score, get_judges_in_vc,
    send_scoring_to_judges, update_all_judge_dms,
    handle_submission, build_score_embed,
    e_error, e_success, e_info,
)

load_dotenv()

GUILD_ID  = int(os.getenv("GUILD_ID", 0))
guild_obj = discord.Object(id=GUILD_ID)


class VCPickerView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.selected_channel = None
        self.create_new = False

        voice_channels = [c for c in guild.channels if isinstance(c, (discord.VoiceChannel, discord.StageChannel))]
        options = [
            discord.SelectOption(label=f"{('#' if isinstance(c, discord.StageChannel) else '') }{c.name}", value=str(c.id))
            for c in voice_channels[:25]
        ]

        if options:
            select = discord.ui.Select(placeholder="Pick an existing channel...", options=options)
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_channel = interaction.guild.get_channel(int(interaction.data["values"][0]))
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Create a stage channel for me", style=discord.ButtonStyle.secondary)
    async def create_stage(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.create_new = True
        self.stop()
        await interaction.response.defer()


async def get_submissions_channel(guild: discord.Guild) -> discord.TextChannel | None:
    settings = await db.get_guild_settings(guild.id)
    if not settings or not settings.get("submissions_channel_id"):
        return None
    return guild.get_channel(settings["submissions_channel_id"])


async def get_host_role_ids(guild_id: int) -> list[int]:
    settings = await db.get_guild_settings(guild_id)
    if not settings:
        return []
    return settings.get("host_role_ids", [])


async def post_final_result(guild: discord.Guild, submission: dict, scores: list[dict]):
    channel = await get_submissions_channel(guild)
    if not channel:
        return

    owner = guild.get_member(submission["user_id"])
    ping = owner.mention if owner else f"<@{submission['user_id']}>"
    avg = sum(s["score"] for s in scores) / len(scores)

    embed = discord.Embed(
        title="Final Score",
        description=f"**Artist:** {ping}\n**Track:** `{submission['filename']}`",
        color=C_GOLD,
    )
    lines = ""
    for s in scores:
        judge = guild.get_member(s["judge_id"])
        jname = judge.mention if judge else f"<@{s['judge_id']}>"
        lines += f"{jname} scored **{fmt(s['score'])}/10**\n"

    embed.add_field(name="Judge scores", value=lines, inline=False)
    embed.add_field(name="Final average", value=f"## {fmt(avg)}/10", inline=False)
    await channel.send(embed=embed)


class Rounds(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def is_host(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == interaction.guild.owner_id:
            return True
        host_ids = await get_host_role_ids(interaction.guild.id)
        return any(r.id in host_ids for r in interaction.user.roles)

    async def is_host_ctx(self, ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id:
            return True
        host_ids = await get_host_role_ids(ctx.guild.id)
        return any(r.id in host_ids for r in ctx.author.roles)

    # ── !judges ───────────────────────────────────────────────────────────────

    @commands.command(name="judges")
    async def set_judges(self, ctx: commands.Context, *members: discord.Member):
        if not await self.is_host_ctx(ctx):
            await ctx.send(embed=e_error("Only the server owner or a host can set judges."), delete_after=5)
            return
        event = await db.get_active_event(ctx.guild.id)
        if not event:
            await ctx.send(embed=e_error("No active event. Run `/startround` first."), delete_after=5)
            return
        await db.set_judges(event["id"], [m.id for m in members])
        names = ", ".join(m.mention for m in members)
        await ctx.send(embed=e_success(f"Judges set for this event: {names}"))

    # ── /startround ───────────────────────────────────────────────────────────

    @app_commands.command(name="startround", description="Open a new round for submissions.")
    @app_commands.guilds(guild_obj)
    async def startround(self, interaction: discord.Interaction):
        if not await self.is_host(interaction):
            await interaction.response.send_message(embed=e_error("Hosts only."))
            return

        settings = await db.get_guild_settings(interaction.guild.id)
        if not settings or not settings.get("setup_complete"):
            await interaction.response.send_message(embed=e_error("Run `/setup` first before starting a round."))
            return

        if await db.get_active_event(interaction.guild.id):
            await interaction.response.send_message(embed=e_error("A round is already open."))
            return

        # Ask which VC to use
        vc_view = VCPickerView(interaction.guild)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Starting a Round: Event Channel",
                description="Pick a voice or stage channel for the event, or let the bot create a stage.",
                color=C_INFO,
            ),
            view=vc_view
        )

        await vc_view.wait()

        if vc_view.create_new:
            try:
                event_channel = await interaction.guild.create_stage_channel("Song Wars Stage")
            except discord.Forbidden:
                await interaction.followup.send(embed=e_error("I don't have permission to create a stage channel."))
                return
        elif vc_view.selected_channel:
            event_channel = vc_view.selected_channel
        else:
            await interaction.followup.send(embed=e_error("No channel selected. Run `/startround` again."))
            return

        # Save event VC to state so scoring can find it
        event_id = await db.create_event(interaction.guild.id, "Song Wars Round", "standard")
        state["active_song"] = None
        state["judge_dm_messages"] = {}
        state["event_vc_id"] = event_channel.id

        channel = await get_submissions_channel(interaction.guild)
        if channel:
            embed = discord.Embed(
                title="Song Wars: Submissions Open",
                description=f"Submit your song using `/submit` or by DMing the bot your file directly.\nOne submission per person.\n\nEvent channel: {event_channel.mention}",
                color=C_INFO,
            )
            await channel.send(embed=embed)

        await interaction.followup.send(embed=e_success(f"Round opened. Event channel: {event_channel.mention}"))

    # ── /endround ─────────────────────────────────────────────────────────────

    @app_commands.command(name="endround", description="Close submissions for the current round.")
    @app_commands.guilds(guild_obj)
    async def endround(self, interaction: discord.Interaction):
        if not await self.is_host(interaction):
            await interaction.response.send_message(embed=e_error("Hosts only."))
            return
        event = await db.get_active_event(interaction.guild.id)
        if not event:
            await interaction.response.send_message(embed=e_error("No active round."))
            return

        subs = await db.get_all_submissions(event["id"])
        await db.close_event(event["id"])
        state["event_vc_id"] = None
        await interaction.response.send_message(
            embed=e_success(f"Submissions closed. **{len(subs)}** song(s) received."),
        )

    # ── /submit ───────────────────────────────────────────────────────────────

    @app_commands.command(name="submit", description="Submit your song for the current round.")
    @app_commands.describe(song="Your audio file (.mp3, .wav, .flac, .ogg, .m4a)")
    @app_commands.guilds(guild_obj)
    async def submit(self, interaction: discord.Interaction, song: discord.Attachment):
        settings = await db.get_guild_settings(interaction.guild.id)
        channel_id = settings["submissions_channel_id"] if settings else 0
        await handle_submission(
            interaction.user, interaction.guild, song,
            channel_id, interaction=interaction,
        )

    # ── /score ────────────────────────────────────────────────────────────────

    @app_commands.command(name="score", description="Score the next song in the queue.")
    @app_commands.guilds(guild_obj)
    async def score(self, interaction: discord.Interaction):
        if not await self.is_host(interaction):
            await interaction.response.send_message(embed=e_error("Hosts only."))
            return
        if state["active_song"]:
            await interaction.response.send_message(
                embed=e_error("A song is currently being scored. Wait for all judges to finish."),
            )
            return

        event = await db.get_active_event(interaction.guild.id)
        if not event:
            for e in await db.get_all_events(interaction.guild.id):
                if await db.get_next_unscored_submission(e["id"]):
                    event = e
                    break

        if not event:
            await interaction.response.send_message(embed=e_error("No event found."))
            return

        submission = await db.get_next_unscored_submission(event["id"])
        if not submission:
            await interaction.response.send_message(embed=e_success("All songs have been scored."))
            return

        judge_ids = await db.get_judges(event["id"])
        if not judge_ids:
            await interaction.response.send_message(
                embed=e_error("No judges set. Use `!judges @user1 @user2` first."),
            )
            return

        # Get VC from active voice states - find VC with most judges in it
        vc_id = await self._find_event_vc(interaction.guild, judge_ids)
        if not vc_id:
            await interaction.response.send_message(
                embed=e_error("No judges found in any voice channel."),
            )
            return

        state["active_song"] = submission
        count = await send_scoring_to_judges(interaction.guild, submission, judge_ids, vc_id)

        owner = interaction.guild.get_member(submission["user_id"])
        name = owner.display_name if owner else submission["username"]
        await interaction.response.send_message(
            embed=e_success(f"Scoring **{name}**'s song. Sent to {count} judge(s)."),
        )

    async def _find_event_vc(self, guild: discord.Guild, judge_ids: list[int]) -> int | None:
        """Use the saved event VC from state, or fall back to finding VC with most judges."""
        if state.get("event_vc_id"):
            return state["event_vc_id"]
        best_vc = None
        best_count = 0
        for vc in guild.voice_channels:
            count = sum(1 for m in vc.members if m.id in judge_ids)
            if count > best_count:
                best_count = count
                best_vc = vc.id
        return best_vc

    # ── /submissions ──────────────────────────────────────────────────────────

    @app_commands.command(name="submissions", description="List all submissions for the current round.")
    @app_commands.guilds(guild_obj)
    async def submissions(self, interaction: discord.Interaction):
        event = await db.get_active_event(interaction.guild.id)
        if not event:
            await interaction.response.send_message(embed=e_error("No active round."))
            return
        subs = await db.get_all_submissions(event["id"])
        if not subs:
            await interaction.response.send_message(embed=e_info("No submissions yet."))
            return
        lines = "\n".join(
            f"{i}. <@{s['user_id']}> `{s['filename']}` {'[scored]' if s['scored'] else '[pending]'}"
            for i, s in enumerate(subs, 1)
        )
        embed = discord.Embed(title="Submissions this round", description=lines, color=C_INFO)
        await interaction.response.send_message(embed=embed)

    # ── DM listener ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        user = message.author
        settings = await db.get_guild_settings(guild.id)
        channel_id = settings["submissions_channel_id"] if settings else 0

        # File → submission attempt
        if message.attachments:
            att = message.attachments[0]
            ext = Path(att.filename).suffix.lower()
            if ext in ALLOWED_EXT:
                await handle_submission(user, guild, att, channel_id, dm_channel=message.channel)
            else:
                await message.channel.send(
                    embed=e_error(f"That file type isn't supported. Send an audio file: {', '.join(sorted(ALLOWED_EXT))}")
                )
            return

        # Plain text → judge scoring attempt
        event = await db.get_active_event(guild.id)
        if not event:
            for e in await db.get_all_events(guild.id):
                if await db.is_judge(e["id"], user.id):
                    event = e
                    break

        if not event or not await db.is_judge(event["id"], user.id):
            await message.channel.send(
                embed=e_info("Submit your song by sending an audio file here during an open round.")
            )
            return

        if not state["active_song"]:
            await message.channel.send(embed=e_info("No song is being scored right now."))
            return

        submission = state["active_song"]

        if await db.has_judge_scored(submission["id"], user.id):
            await message.channel.send(embed=e_info("You've already scored this song."))
            return

        judge_ids = await db.get_judges(event["id"])
        vc_id = await self._find_event_vc(guild, judge_ids)
        if not vc_id or user.id not in [j.id for j in get_judges_in_vc(guild, judge_ids, vc_id)]:
            await message.channel.send(
                embed=e_error("You need to be in a voice channel with other judges to submit a score.")
            )
            return

        score = parse_score(message.content)
        if score is None:
            await message.channel.send(
                embed=e_error("Invalid score. Send a number between 0 and 10, half points ok (e.g. `8.5`).")
            )
            return

        await db.add_score(submission["id"], user.id, score)
        await message.channel.send(embed=e_success(f"Score of **{fmt(score)}/10** recorded."))

        scores = await update_all_judge_dms(guild, submission, judge_ids)

        scored_ids = {s["judge_id"] for s in scores}
        if all(jid in scored_ids for jid in judge_ids):
            await post_final_result(guild, submission, scores)
            await db.mark_submission_scored(submission["id"])
            state["active_song"] = None
            state["judge_dm_messages"] = {}

            if event["mode"] == "tournament":
                tournament_cog = self.bot.cogs.get("Tournament")
                if tournament_cog:
                    await tournament_cog.resolve_match(guild, event)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rounds(bot))