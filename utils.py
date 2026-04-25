import discord
from pathlib import Path
import database as db
from state import state

ALLOWED_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}
MAX_FILE_MB = 25

# ── Default colors ────────────────────────────────────────────────────────────
C_INFO    = 0x5865F2
C_SUCCESS = 0x57F287
C_ERROR   = 0xED4245
C_GOLD    = 0xFFD700
C_ORANGE  = 0xFF6B35


async def guild_color(guild_id: int) -> int:
    """Returns the guild's custom color, or blurple as default."""
    return await db.get_guild_color(guild_id)


# ── Embed helpers ─────────────────────────────────────────────────────────────

def e_error(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=C_ERROR)

def e_success(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=C_SUCCESS)

def e_info(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=C_INFO)


# ── Score helpers ─────────────────────────────────────────────────────────────

def fmt(score: float) -> str:
    return str(int(score)) if score == int(score) else f"{score:.1f}"


def parse_score(text: str) -> float | None:
    try:
        val = float(text.strip())
    except ValueError:
        return None
    if val < 0 or val > 10:
        return None
    return round(val * 2) / 2


def validate_attachment(attachment: discord.Attachment) -> str | None:
    ext = Path(attachment.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return f"File type `{ext}` is not allowed. Accepted formats: {', '.join(sorted(ALLOWED_EXT))}"
    if attachment.size / (1024 * 1024) > MAX_FILE_MB:
        return f"File too large. Max size is {MAX_FILE_MB}MB."
    return None


def get_judges_in_vc(guild: discord.Guild, judge_ids: list[int], vc_id: int) -> list[discord.Member]:
    vc = guild.get_channel(vc_id)
    if not vc:
        return []
    return [m for m in vc.members if m.id in judge_ids]


# ── Live scoring embed ────────────────────────────────────────────────────────

async def build_score_embed(
    guild: discord.Guild,
    submission: dict,
    judge_ids: list[int],
    scores: list[dict],
) -> discord.Embed:
    owner = guild.get_member(submission["user_id"])
    owner_name = owner.display_name if owner else submission["username"]
    scored_map = {s["judge_id"]: s["score"] for s in scores}
    count = len(scored_map)
    all_done = count == len(judge_ids) and count > 0

    embed = discord.Embed(
        title="Song Wars: Live Scoring",
        description=(
            f"**Artist:** {owner.mention if owner else owner_name}\n"
            f"**Track:** `{submission['filename']}`"
        ),
        color=C_SUCCESS if all_done else C_INFO,
    )

    lines = ""
    total = 0.0
    for jid in judge_ids:
        judge = guild.get_member(jid)
        jname = judge.mention if judge else f"<@{jid}>"
        if jid in scored_map:
            total += scored_map[jid]
            lines += f"{jname} scored **{fmt(scored_map[jid])}/10**\n"
        else:
            lines += f"{jname} waiting...\n"

    embed.add_field(name="Scores", value=lines or "No scores yet.", inline=False)

    if count > 0:
        embed.add_field(
            name=f"Running average ({count}/{len(judge_ids)} judges)",
            value=f"**{fmt(total / count)}/10**",
            inline=False,
        )

    if all_done:
        embed.add_field(
            name="Final score",
            value=f"## {fmt(total / count)}/10",
            inline=False,
        )

    embed.set_footer(text="DM me your score, 0 to 10, half points ok (e.g. 7.5)")
    return embed


# ── Send initial scoring embeds to all judges ─────────────────────────────────

async def send_scoring_to_judges(
    guild: discord.Guild,
    submission: dict,
    judge_ids: list[int],
    vc_id: int,
) -> int:
    scores = await db.get_scores_for_submission(submission["id"])
    score_embed = await build_score_embed(guild, submission, judge_ids, scores)
    link_embed = discord.Embed(
        description=f"[Listen to the track]({submission['file_url']})",
        color=C_INFO,
    )
    judges_in_vc = get_judges_in_vc(guild, judge_ids, vc_id)
    state["judge_dm_messages"] = {}

    for judge in judges_in_vc:
        try:
            dm = await judge.create_dm()
            msg = await dm.send(embeds=[link_embed, score_embed])
            state["judge_dm_messages"][judge.id] = msg
        except discord.Forbidden:
            pass

    return len(judges_in_vc)


# ── Edit the live embed in all judge DMs ──────────────────────────────────────

async def update_all_judge_dms(
    guild: discord.Guild,
    submission: dict,
    judge_ids: list[int],
) -> list[dict]:
    scores = await db.get_scores_for_submission(submission["id"])
    score_embed = await build_score_embed(guild, submission, judge_ids, scores)
    for jid, msg in state["judge_dm_messages"].items():
        try:
            # Keep the link embed (index 0), update the score embed (index 1)
            await msg.edit(embeds=[msg.embeds[0], score_embed])
        except discord.HTTPException:
            pass
    return scores


# ── Shared submission handler (slash + DM) ────────────────────────────────────

async def handle_submission(
    user: discord.User | discord.Member,
    guild: discord.Guild,
    attachment: discord.Attachment,
    submissions_channel_id: int,
    interaction: discord.Interaction = None,
    dm_channel: discord.DMChannel = None,
):
    async def reply(embed: discord.Embed):
        if interaction:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        elif dm_channel:
            await dm_channel.send(embed=embed)

    event = await db.get_active_event(guild.id)
    if not event:
        await reply(e_error("There's no open round right now. Check back when submissions are open."))
        return

    if await db.is_judge(event["id"], user.id):
        await reply(e_error("Judges can't submit songs."))
        return

    if await db.get_submission_by_user(event["id"], user.id):
        await reply(e_error("You've already submitted a song this round."))
        return

    error = validate_attachment(attachment)
    if error:
        await reply(e_error(error))
        return

    await db.add_submission(
        event["id"], user.id, user.display_name,
        attachment.filename, attachment.url,
    )

    channel = guild.get_channel(submissions_channel_id)
    if channel:
        member = guild.get_member(user.id)
        ping = member.mention if member else f"<@{user.id}>"
        subs = await db.get_all_submissions(event["id"])
        embed = discord.Embed(
            title="New Submission",
            description=f"{ping} dropped a track.",
            color=C_INFO,
        )
        embed.add_field(name="Track", value=f"`{attachment.filename}`", inline=False)
        embed.set_footer(text=f"Submission {len(subs)}")
        await channel.send(embed=embed)

    await reply(e_success("Your song has been submitted. Good luck."))