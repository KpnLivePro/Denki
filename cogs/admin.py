from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.admin")


async def _respond(
    ctx_or_interaction: Any,
    embed: discord.Embed,
    is_slash: bool,
    ephemeral: bool = False,
) -> None:
    if is_slash:
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.reply(embed=embed)


class Admin(commands.Cog):
    """Server admin commands — config, earnsettings, denkireport."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # /config

    @app_commands.command(name="config", description="View and manage Denki config for your server. Admin only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_slash(self, interaction: discord.Interaction) -> None:
        await self._config(interaction, is_slash=True)

    @commands.command(name="config", aliases=["cfg"])
    @commands.has_permissions(administrator=True)
    async def config_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._config(ctx, is_slash=False)

    async def _config(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash, ephemeral=True)
        guild  = ctx_or_interaction.guild
        config = await db.get_or_create_guild_config(guild.id)

        notif_channel = f"<#{config['notif_channel']}>" if config.get("notif_channel") else "`Not set`"
        notif_role    = f"<@&{config['notif_role']}>"   if config.get("notif_role")    else "`Not set`"
        shop_status   = "`Open`"    if config["shop_enabled"]  else "`Closed`"
        daily_status  = "`Enabled`" if config["daily_enabled"] else "`Disabled`"
        work_status   = "`Enabled`" if config["work_enabled"]  else "`Disabled`"
        rob_status    = "`Enabled`" if config["rob_enabled"]   else "`Disabled`"

        embed = Embeds.base(f"> `⚙️` *Denki config — **{guild.name}***")
        embed.add_field(name="`📢` Notif channel", value=notif_channel, inline=True)
        embed.add_field(name="`🔔` Notif role",    value=notif_role,    inline=True)
        embed.add_field(name="`🏪` Shop",          value=shop_status,   inline=True)
        embed.add_field(name="`📅` Daily",         value=daily_status,  inline=True)
        embed.add_field(name="`💼` Work",          value=work_status,   inline=True)
        embed.add_field(name="`🦹` Rob",           value=rob_status,    inline=True)
        embed.set_footer(text="Use /setnotifchannel, /setnofifrole, or /earnsettings to update.")

        view = ConfigView(guild_id=guild.id, config=config)
        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed, view=view)

    @app_commands.command(name="setnotifchannel", description="Set the channel for Denki announcements. Admin only.")
    @app_commands.describe(channel="Channel to send announcements to")
    @app_commands.checks.has_permissions(administrator=True)
    async def setnotifchannel_slash(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if not interaction.guild:
            return
        await db.update_guild_config(interaction.guild.id, {"notif_channel": channel.id})
        await interaction.response.send_message(
            embed=Embeds.success(f"Notification channel set to {channel.mention}."),
            ephemeral=True,
        )

    @commands.command(name="setnotifchannel")
    @commands.has_permissions(administrator=True)
    async def setnotifchannel_prefix(
        self,
        ctx: commands.Context[Any],
        channel: discord.TextChannel,
    ) -> None:
        if not ctx.guild:
            return
        await db.update_guild_config(ctx.guild.id, {"notif_channel": channel.id})
        await ctx.reply(embed=Embeds.success(f"Notification channel set to {channel.mention}."))

    # /setnofifrole

    @app_commands.command(name="setnofifrole", description="Set the role to mention in announcements. Admin only.")
    @app_commands.describe(role="Role to mention in announcements")
    @app_commands.checks.has_permissions(administrator=True)
    async def setnofifrole_slash(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if not interaction.guild:
            return
        await db.update_guild_config(interaction.guild.id, {"notif_role": role.id})
        await interaction.response.send_message(
            embed=Embeds.success(f"Notification role set to {role.mention}."),
            ephemeral=True,
        )

    @commands.command(name="setnofifrole")
    @commands.has_permissions(administrator=True)
    async def setnofifrole_prefix(
        self,
        ctx: commands.Context[Any],
        role: discord.Role,
    ) -> None:
        if not ctx.guild:
            return
        await db.update_guild_config(ctx.guild.id, {"notif_role": role.id})
        await ctx.reply(embed=Embeds.success(f"Notification role set to {role.mention}."))

    # /earnsettings

    @app_commands.command(name="earnsettings", description="Configure which earn commands are enabled. Admin only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def earnsettings_slash(self, interaction: discord.Interaction) -> None:
        await self._earnsettings(interaction, is_slash=True)

    @commands.command(name="earnsettings")
    @commands.has_permissions(administrator=True)
    async def earnsettings_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._earnsettings(ctx, is_slash=False)

    async def _earnsettings(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash, ephemeral=True)
        guild  = ctx_or_interaction.guild
        config = await db.get_or_create_guild_config(guild.id)

        embed = Embeds.base(
            "> `⚙️` *Earn settings*\n"
            "> Select which commands to **disable**. At least one must stay enabled."
        )
        view = EarnSettingsView(guild_id=guild.id, config=config)

        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed, view=view)

    # /denkireport

    @app_commands.command(name="denkireport", description="Report a user to the bot owner for review. Admin only.")
    @app_commands.describe(user="User to report", reason="Reason for the report")
    @app_commands.checks.has_permissions(administrator=True)
    async def denkireport_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
    ) -> None:
        await self._denkireport(interaction, target=user, reason=reason, is_slash=True)

    @commands.command(name="denkireport", aliases=["report"])
    @commands.has_permissions(administrator=True)
    async def denkireport_prefix(
        self,
        ctx: commands.Context[Any],
        user: discord.Member,
        *,
        reason: str,
    ) -> None:
        await self._denkireport(ctx, target=user, reason=reason, is_slash=False)

    async def _denkireport(
        self,
        ctx_or_interaction: Any,
        target: discord.Member,
        reason: str,
        is_slash: bool,
    ) -> None:
        await _defer(ctx_or_interaction, is_slash, ephemeral=True)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild  = ctx_or_interaction.guild

        user_data   = await db.get_or_create_user(target.id)
        wallet_snap = int(user_data["wallet"])

        await db.create_report(
            reported_id=target.id,
            reporter_id=author.id,
            guild_id=guild.id,
            reason=reason,
            wallet_snap=wallet_snap,
        )

        # DM the bot owner
        if self.bot.owner_id:
            try:
                owner = await self.bot.fetch_user(self.bot.owner_id)
                await owner.send(embed=Embeds.report_dm(
                    reporter=author,
                    reported=target,
                    guild_name=guild.name,
                    reason=reason,
                    wallet_snap=wallet_snap,
                ))
            except discord.Forbidden:
                logger.warning("Could not DM report to bot owner — DMs closed")
            except Exception as e:
                logger.error(f"Failed to DM report to owner: {e}")

        await _respond(
            ctx_or_interaction,
            Embeds.success(f"Report filed against **{target.display_name}**. The bot owner has been notified."),
            is_slash,
            ephemeral=True,
        )

    # Error handlers

    @config_slash.error
    @setnotifchannel_slash.error
    @setnofifrole_slash.error
    @earnsettings_slash.error
    @denkireport_slash.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=Embeds.error("You need **Administrator** permission to use this command."),
                ephemeral=True,
            )


class ConfigView(discord.ui.View):
    """Quick-access buttons shown with /config."""

    def __init__(self, guild_id: int, config: dict) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.config   = config

    @discord.ui.button(label="Earn settings", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def earn_settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view  = EarnSettingsView(guild_id=self.guild_id, config=self.config)
        embed = Embeds.base(
            "> `⚙️` *Earn settings*\n"
            "> Select which commands to **disable**. At least one must stay enabled."
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class EarnSettingsView(discord.ui.View):
    """Dropdown to disable up to 2 of the 3 earn commands."""

    def __init__(self, guild_id: int, config: dict) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.config   = config

    @discord.ui.select(
        placeholder="Select commands to disable (up to 2)...",
        min_values=0,
        max_values=2,
        options=[
            discord.SelectOption(label="Daily", value="daily", emoji="📅", description="/daily — 24h reward"),
            discord.SelectOption(label="Work",  value="work",  emoji="💼", description="/work — 1h job reward"),
            discord.SelectOption(label="Rob",   value="rob",   emoji="🦹", description="/rob — steal from users"),
        ],
    )
    async def select_disabled(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        disabled = select.values

        updates = {
            "daily_enabled": "daily" not in disabled,
            "work_enabled":  "work"  not in disabled,
            "rob_enabled":   "rob"   not in disabled,
        }

        if not any(updates.values()):
            await interaction.response.send_message(
                embed=Embeds.error(
                    "You cannot disable all three earning methods. At least one must remain active."
                ),
                ephemeral=True,
            )
            return

        try:
            await db.update_guild_config(self.guild_id, updates)
        except ValueError as e:
            await interaction.response.send_message(embed=Embeds.error(str(e)), ephemeral=True)
            return

        enabled_names  = [k.replace("_enabled", "").capitalize() for k, v in updates.items() if v]
        disabled_names = [k.replace("_enabled", "").capitalize() for k, v in updates.items() if not v]

        lines = []
        if enabled_names:
            lines.append(f"> Enabled: {', '.join(f'`{n}`' for n in enabled_names)}")
        if disabled_names:
            lines.append(f"> Disabled: {', '.join(f'`{n}`' for n in disabled_names)}")

        await interaction.response.send_message(
            embed=Embeds.success("Earn settings updated.\n" + "\n".join(lines)),
            ephemeral=True,
        )
        self.stop()



async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    """Defer a slash interaction immediately to extend the 3-second response window."""
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))