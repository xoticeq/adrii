import os
import hmac
import hashlib
import anthropic
import discord
from discord.ext import commands
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

BOT_UPDATES_CHANNEL_ID = int(os.getenv("BOT_UPDATES_CHANNEL_ID", 0))
BOT_UPDATES_ROLE_ID    = int(os.getenv("BOT_UPDATES_ROLE_ID", 0))
GITHUB_WEBHOOK_SECRET  = os.getenv("GITHUB_WEBHOOK_SECRET", "").encode()
ANTHROPIC_API_KEY      = os.getenv("ANTHROPIC_API_KEY", "")
WEBHOOK_PORT           = int(os.getenv("WEBHOOK_PORT", 8080))

anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(GITHUB_WEBHOOK_SECRET, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header or "")


async def summarize_with_claude(commits: list[dict]) -> str:
    commit_text = ""
    for c in commits:
        commit_text += f"\nAdded files: {', '.join(c.get('added', [])) or 'none'}\n"
        commit_text += f"Modified files: {', '.join(c.get('modified', [])) or 'none'}\n"
        commit_text += f"Removed files: {', '.join(c.get('removed', [])) or 'none'}\n"

    prompt = f"""You are a changelog writer for a Discord bot project.
Given these file changes from git commits, write a clean human readable summary.

Rules:
- Do not copy file names literally, describe what changed in plain english
- If only one thing changed, write a single plain sentence with no bullet points
- If multiple things changed, use bullet points with no dashes, use a dot or nothing
- Naturally include the words added, fixed, removed, or changed where appropriate
- Keep it short and casual, not formal
- Do not use em dashes
- Only output the summary, nothing else

File changes:
{commit_text}"""

    message = await anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


class GitHub(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.runner = None

    async def cog_load(self):
        app = web.Application()
        app.router.add_post("/github", self.handle_webhook)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", WEBHOOK_PORT)
        await site.start()
        print(f"GitHub webhook server running on port {WEBHOOK_PORT}")

    async def handle_webhook(self, request: web.Request) -> web.Response:
        payload = await request.read()
        sig = request.headers.get("X-Hub-Signature-256", "")

        if not verify_signature(payload, sig):
            return web.Response(status=401, text="Invalid signature")

        event = request.headers.get("X-GitHub-Event", "")
        if event != "push":
            return web.Response(text="ok")

        data = await request.json()
        commits = data.get("commits", [])
        if not commits:
            return web.Response(text="ok")

        # Check if any actual files were changed
        any_changes = any(
            c.get("added") or c.get("modified") or c.get("removed")
            for c in commits
        )
        if not any_changes:
            return web.Response(text="ok")

        summary = await summarize_with_claude(commits)

        channel = self.bot.get_channel(BOT_UPDATES_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="bot update",
                description=f"```{summary}```",
                color=0x5865F2,
            )
            await channel.send(content=f"<@&{BOT_UPDATES_ROLE_ID}>")
            await channel.send(embed=embed)

        return web.Response(text="ok")

    async def cog_unload(self):
        if self.runner:
            await self.runner.cleanup()


async def setup(bot: commands.Bot):
    await bot.add_cog(GitHub(bot))