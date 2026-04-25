import discord
from discord.ext import commands
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import database as db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("songwars")

# ── Intents ───────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.dm_messages = True

# ── Bot ───────────────────────────────────────────────────────────────────────

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await db.init_db()
    guild = discord.Object(id=int(os.getenv("GUILD_ID", 0)))
    await bot.tree.sync(guild=guild)
    log.info(f"Logged in as {bot.user} | Synced slash commands to guild {guild.id}")


@bot.event
async def setup_hook():
    await load_cogs()


async def load_cogs():
    cogs_path = Path(__file__).parent / "cogs"
    loaded, failed = [], []

    for file in sorted(cogs_path.glob("*.py")):
        if file.name.startswith("_"):
            continue
        ext = f"cogs.{file.stem}"
        try:
            await bot.load_extension(ext)
            loaded.append(file.stem)
            log.info(f"Loaded cog: {file.stem}")
        except Exception as e:
            failed.append(file.stem)
            log.error(f"Failed to load cog {file.stem}: {e}")

    log.info(f"Cogs loaded: {loaded}")
    if failed:
        log.warning(f"Cogs failed: {failed}")


# ── Run ───────────────────────────────────────────────────────────────────────

bot.run(os.getenv("BOT_TOKEN", ""), log_handler=None)