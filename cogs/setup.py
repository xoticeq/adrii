import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import database as db
from utils import C_INFO, C_SUCCESS, C_ERROR, C_GOLD, e_error, e_success, e_info

load_dotenv()

GUILD_ID      = int(os.getenv("GUILD_ID", 0))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
OWNER_ID      = int(os.getenv("OWNER_ID", 0))

guild_obj = discord.Object(id=GUILD_ID)


def is_authorized(interaction: discord.Interaction) -> bool:
    if interaction.user.id == interaction.guild.owner_id:
        return True
    if ADMIN_ROLE_ID and any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
        return True
    return False


# ── Step 1: Channel select view ───────────────────────────────────────────────

class ChannelSelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.selected_channel = None
        self.create_new = False

        options = [
            discord.SelectOption(label=f"#{c.name}", value=str(c.id))
            for c in guild.text_channels[:25]
        ]
        select = discord.ui.Select(placeholder="Pick an existing channel...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_channel = interaction.guild.get_channel(int(interaction.data["values"][0]))
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Create a new channel for me", style=discord.ButtonStyle.secondary)
    async def create_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.create_new = True
        self.stop()
        await interaction.response.defer()


# ── Step 2: Role select view ──────────────────────────────────────────────────

# ── Bot updates channel view ──────────────────────────────────────────────────

class BotUpdatesView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.selected_channel = None
        self.create_new = False
        self.skip = False

        options = [
            discord.SelectOption(label=f"#{c.name}", value=str(c.id))
            for c in guild.text_channels[:25]
        ]
        select = discord.ui.Select(placeholder="Pick an existing channel...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_channel = interaction.guild.get_channel(int(interaction.data["values"][0]))
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Create a new channel for me", style=discord.ButtonStyle.secondary)
    async def create_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.create_new = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Skip, I don't want one", style=discord.ButtonStyle.danger)
    async def skip_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.skip = True
        self.stop()
        await interaction.response.defer()




class CreateRoleModal(discord.ui.Modal, title="Create a Host Role"):
    role_name = discord.ui.TextInput(
        label="Role name",
        placeholder="Song Wars Host",
        default="Song Wars Host",
        max_length=50,
    )
    role_color = discord.ui.TextInput(
        label="Role color (hex code)",
        placeholder="#5865F2",
        default="#5865F2",
        max_length=7,
    )

    def __init__(self, view: "RoleSelectView"):
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.role_color.value.strip().lstrip("#")
        try:
            color = discord.Color(int(raw, 16))
        except ValueError:
            color = discord.Color.blurple()

        self.parent_view.new_role_name = self.role_name.value.strip() or "Song Wars Host"
        self.parent_view.new_role_color = color
        self.parent_view.create_new = True
        self.parent_view.stop()
        await interaction.response.defer()


class RoleSelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.selected_roles = []
        self.create_new = False
        self.new_role_name = "Song Wars Host"
        self.new_role_color = discord.Color.blurple()

        options = [
            discord.SelectOption(label=f"@{r.name}", value=str(r.id))
            for r in guild.roles
            if not r.managed and r.name != "@everyone"
        ][:25]

        select = discord.ui.Select(
            placeholder="Pick one or more host roles...",
            options=options,
            min_values=1,
            max_values=min(len(options), 5)
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_roles = [
            interaction.guild.get_role(int(v))
            for v in interaction.data["values"]
        ]
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Create a new host role for me", style=discord.ButtonStyle.secondary)
    async def create_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoleModal(self))


# ── Confirm view ──────────────────────────────────────────────────────────────

class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.confirmed = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Start over", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


# ── Settings edit view ────────────────────────────────────────────────────────

class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.action = None

    @discord.ui.button(label="Change submissions channel", style=discord.ButtonStyle.secondary)
    async def change_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action = "channel"
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Change host roles", style=discord.ButtonStyle.secondary)
    async def change_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action = "roles"
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Change bot updates channel", style=discord.ButtonStyle.secondary)
    async def change_updates(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action = "updates"
        self.stop()
        await interaction.response.defer()


# ── Cog ───────────────────────────────────────────────────────────────────────

class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup ────────────────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Set up the bot for this server.")
    @app_commands.guilds(guild_obj)
    async def setup(self, interaction: discord.Interaction):
        if not is_authorized(interaction):
            await interaction.response.send_message(embed=e_error("Only the server owner or an admin can run setup."))
            return

        existing = await db.get_guild_settings(interaction.guild.id)
        if existing and existing["setup_complete"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="This server is already set up. Use `/settings` to make changes.",
                    color=C_ERROR,
                )
            )
            return

        channel_view = ChannelSelectView(interaction.guild)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Song Wars Setup (1 of 2): Submissions Channel",
                description="Where should song submissions be posted? Pick an existing channel or let the bot create one.",
                color=C_INFO,
            ),
            view=channel_view
        )

        await self.run_wizard(interaction, channel_view)

    async def run_wizard(self, interaction: discord.Interaction, channel_view: ChannelSelectView):
        guild = interaction.guild

        # ── Step 1: wait for channel ──────────────────────────────────────────

        await channel_view.wait()

        if channel_view.create_new:
            submissions_channel = await guild.create_text_channel("submissions")
        elif channel_view.selected_channel:
            submissions_channel = channel_view.selected_channel
        else:
            await interaction.followup.send(embed=e_error("No channel selected. Run `/setup` again."))
            return

        # ── Step 2: Host roles ────────────────────────────────────────────────

        role_view = RoleSelectView(guild)
        await interaction.followup.send(
            embed=discord.Embed(
                title="Step 2 of 3: Host Role",
                description="Pick who can run events, or let the bot create a host role.",
                color=C_INFO,
            ),
            view=role_view
        )

        await role_view.wait()

        if role_view.create_new:
            host_role = await guild.create_role(
                name=role_view.new_role_name,
                color=role_view.new_role_color
            )
            host_roles = [host_role]
        elif role_view.selected_roles:
            host_roles = role_view.selected_roles
        else:
            await interaction.followup.send(embed=e_error("No role selected. Run `/setup` again."))
            return

        # ── Step 3: Bot updates channel ───────────────────────────────────────

        updates_view = BotUpdatesView(guild)
        await interaction.followup.send(
            embed=discord.Embed(
                title="Step 3 of 3: Bot Updates Channel",
                description="Want a channel where the bot posts updates when code changes are pushed? Pick one, create one, or skip.",
                color=C_INFO,
            ),
            view=updates_view
        )

        await updates_view.wait()

        if updates_view.skip:
            bot_updates_channel = None
        elif updates_view.create_new:
            bot_updates_channel = await guild.create_text_channel("bot-updates")
        elif updates_view.selected_channel:
            bot_updates_channel = updates_view.selected_channel
        else:
            bot_updates_channel = None

        # ── Confirm ───────────────────────────────────────────────────────────

        role_names = ", ".join(r.mention for r in host_roles)
        updates_line = bot_updates_channel.mention if bot_updates_channel else "none"
        confirm_view = ConfirmView()
        await interaction.followup.send(
            embed=discord.Embed(
                title="Confirm Setup",
                description=(
                    f"**Submissions channel:** {submissions_channel.mention}\n"
                    f"**Host roles:** {role_names}\n"
                    f"**Bot updates channel:** {updates_line}\n\n"
                    "Does this look right?"
                ),
                color=C_GOLD,
            ),
            view=confirm_view
        )

        await confirm_view.wait()

        if not confirm_view.confirmed:
            await interaction.followup.send(embed=e_info("Setup cancelled. Run `/setup` to start over."))
            return

        # ── Save ──────────────────────────────────────────────────────────────

        await db.save_guild_settings(
            interaction.guild.id,
            submissions_channel.id,
            [r.id for r in host_roles],
            bot_updates_channel.id if bot_updates_channel else None,
        )

        updates_done = f"Bot updates will post in {bot_updates_channel.mention}." if bot_updates_channel else "No bot updates channel set."
        await interaction.followup.send(
            embed=discord.Embed(
                title="Setup complete",
                description=(
                    f"Submissions will post in {submissions_channel.mention}.\n"
                    f"Host roles: {role_names}\n"
                    f"{updates_done}\n\n"
                    "You're ready to run events. Use `/startround` to open submissions."
                ),
                color=C_SUCCESS,
            )
        )

    # ── /settings ─────────────────────────────────────────────────────────────

    @app_commands.command(name="settings", description="View and edit server settings.")
    @app_commands.guilds(guild_obj)
    async def settings(self, interaction: discord.Interaction):
        if not is_authorized(interaction):
            await interaction.response.send_message(embed=e_error("Only the server owner or an admin can change settings."))
            return

        settings = await db.get_guild_settings(interaction.guild.id)
        if not settings or not settings["setup_complete"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="No settings found. Run `/setup` first.",
                    color=C_ERROR,
                )
            )
            return

        channel = interaction.guild.get_channel(settings["submissions_channel_id"])
        updates_ch = interaction.guild.get_channel(settings["bot_updates_channel_id"]) if settings.get("bot_updates_channel_id") else None
        role_names = []
        for rid in settings["host_role_ids"]:
            r = interaction.guild.get_role(rid)
            if r:
                role_names.append(r.mention)

        settings_view = SettingsView()
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Server Settings",
                description=(
                    f"**Submissions channel:** {channel.mention if channel else 'not set'}\n"
                    f"**Host roles:** {', '.join(role_names) if role_names else 'none'}\n"
                    f"**Bot updates channel:** {updates_ch.mention if updates_ch else 'none'}"
                ),
                color=C_INFO,
            ),
            view=settings_view
        )

        await settings_view.wait()

        if settings_view.action == "channel":
            channel_view = ChannelSelectView(interaction.guild)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Change Submissions Channel",
                    description="Pick a channel or let the bot create one.",
                    color=C_INFO,
                ),
                view=channel_view
            )
            await channel_view.wait()

            if channel_view.create_new:
                new_channel = await interaction.guild.create_text_channel("submissions")
            elif channel_view.selected_channel:
                new_channel = channel_view.selected_channel
            else:
                new_channel = None

            if new_channel:
                await db.save_guild_settings(
                    interaction.guild.id,
                    new_channel.id,
                    settings["host_role_ids"],
                    settings.get("bot_updates_channel_id"),
                )
                await interaction.followup.send(
                    embed=e_success(f"Submissions channel updated to {new_channel.mention}.")
                )

        elif settings_view.action == "roles":
            role_view = RoleSelectView(interaction.guild)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Change Host Roles",
                    description="Pick roles or let the bot create a new host role.",
                    color=C_INFO,
                ),
                view=role_view
            )
            await role_view.wait()

            if role_view.create_new:
                new_role = await interaction.guild.create_role(
                    name=role_view.new_role_name,
                    color=role_view.new_role_color
                )
                new_roles = [new_role]
            elif role_view.selected_roles:
                new_roles = role_view.selected_roles
            else:
                new_roles = []

            if new_roles:
                await db.save_guild_settings(
                    interaction.guild.id,
                    settings["submissions_channel_id"],
                    [r.id for r in new_roles],
                    settings.get("bot_updates_channel_id"),
                )
                names = ", ".join(r.mention for r in new_roles)
                await interaction.followup.send(embed=e_success(f"Host roles updated to {names}."))

        elif settings_view.action == "updates":
            updates_view = BotUpdatesView(interaction.guild)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Change Bot Updates Channel",
                    description="Pick a channel, create one, or skip to remove it.",
                    color=C_INFO,
                ),
                view=updates_view
            )
            await updates_view.wait()

            if updates_view.skip:
                new_updates = None
            elif updates_view.create_new:
                new_updates = await interaction.guild.create_text_channel("bot-updates")
            elif updates_view.selected_channel:
                new_updates = updates_view.selected_channel
            else:
                new_updates = None
# test
            await db.save_guild_settings(
                interaction.guild.id,
                settings["submissions_channel_id"],
                settings["host_role_ids"],
                new_updates.id if new_updates else None,
            )
            msg = f"Bot updates channel set to {new_updates.mention}." if new_updates else "Bot updates channel removed."
            await interaction.followup.send(embed=e_success(msg))


async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))