from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.init")


class InitWizard(discord.ui.View):
    """
    Step-by-step server setup wizard.

    Steps:
    1. Set notification channel
    2. Set notification role (skippable)
    3. Configure earn toggles
    4. Summary + save
    """

    def __init__(self, guild_id: int, admin: discord.Member) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.admin = admin
        self.step = 1

        self.notif_channel: (
            discord.app_commands.AppCommandChannel
            | discord.app_commands.AppCommandThread
            | None
        ) = None
        self.notif_role: discord.Role | None = None
        self.daily_enabled: bool = True
        self.work_enabled: bool = True
        self.rob_enabled: bool = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.admin.id:
            await interaction.response.send_message(
                embed=Embeds.error(
                    "Only the admin who ran `/init` can use this wizard."
                ),
                ephemeral=True,
            )
            return False
        return True

    # Step embeds

    def step1_embed(self) -> discord.Embed:
        return Embeds.base(
            "> `⚙️` *Denki Setup — Step 1 of 4*\n\n"
            "> **Notification channel**\n"
            "> Select the channel where Denki will send season announcements and vault payouts.\n"
            "> Supports **text channels**, **announcement channels**, and **announcement threads**."
        )

    def step2_embed(self) -> discord.Embed:
        if self.notif_channel:
            ch_type = (
                "📣 Announcement"
                if self.notif_channel.type
                in (discord.ChannelType.news, discord.ChannelType.news_thread)
                else "💬 Text"
            )
            channel_val = f"{self.notif_channel.mention} — *{ch_type}*"
        else:
            channel_val = "`Not set`"
        return Embeds.base(
            "> `⚙️` *Denki Setup — Step 2 of 4*\n\n"
            "> **Notification role**\n"
            "> Select a role to mention in announcements, or skip for no mention.\n\n"
            f"> Channel: {channel_val}"
        )

    def step3_embed(self) -> discord.Embed:
        role_val = self.notif_role.mention if self.notif_role else "`No mention`"
        return Embeds.base(
            "> `⚙️` *Denki Setup — Step 3 of 4*\n\n"
            "> **Earn commands**\n"
            "> Select which commands to **disable** (up to 2).\n"
            "> Click **Done** without selecting to keep all enabled.\n\n"
            f"> Role: {role_val}"
        )

    # Step views

    def step1_view(self) -> InitWizard:
        self.clear_items()
        self.add_item(ChannelSelectItem(self))
        self.add_item(CancelButton(self))
        return self

    def step2_view(self) -> InitWizard:
        self.clear_items()
        self.add_item(RoleSelectItem(self))
        self.add_item(SkipButton(self))
        self.add_item(CancelButton(self))
        return self

    def step3_view(self) -> InitWizard:
        self.clear_items()
        self.add_item(EarnToggleSelect(self))
        self.add_item(DoneButton(self))
        self.add_item(CancelButton(self))
        return self

    # Save and show summary

    async def show_summary(self, interaction: discord.Interaction) -> None:
        updates: dict[str, Any] = {
            "daily_enabled": self.daily_enabled,
            "work_enabled": self.work_enabled,
            "rob_enabled": self.rob_enabled,
        }
        if self.notif_channel:
            updates["notif_channel"] = self.notif_channel.id
        if self.notif_role:
            updates["notif_role"] = self.notif_role.id

        await db.update_guild_config(self.guild_id, updates)

        if self.notif_channel:
            ch_type = (
                "📣"
                if self.notif_channel.type
                in (discord.ChannelType.news, discord.ChannelType.news_thread)
                else "💬"
            )
            channel_val = f"{ch_type} {self.notif_channel.mention}"
        else:
            channel_val = "`Not set`"
        role_val = self.notif_role.mention if self.notif_role else "`No mention`"
        daily_val = "`Enabled`" if self.daily_enabled else "`Disabled`"
        work_val = "`Enabled`" if self.work_enabled else "`Disabled`"
        rob_val = "`Enabled`" if self.rob_enabled else "`Disabled`"

        embed = Embeds.base(
            "> `✅` *Denki Setup — Complete!*\n\n"
            "> Your server is ready. Here's what was configured:"
        )
        embed.add_field(name="`📢` Notif channel", value=channel_val, inline=True)
        embed.add_field(name="`🔔` Notif role", value=role_val, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="`📅` Daily", value=daily_val, inline=True)
        embed.add_field(name="`💼` Work", value=work_val, inline=True)
        embed.add_field(name="`🦹` Rob", value=rob_val, inline=True)
        embed.set_footer(text="Use /config anytime to update these settings.")

        self.clear_items()
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)


# UI components


class ChannelSelectItem(discord.ui.ChannelSelect):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(
            placeholder="Select a channel for announcements...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
                discord.ChannelType.news_thread,
            ],
            min_values=1,
            max_values=1,
        )
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wizard.notif_channel = self.values[0]
        await interaction.response.edit_message(
            embed=self.wizard.step2_embed(),
            view=self.wizard.step2_view(),
        )


class RoleSelectItem(discord.ui.RoleSelect):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(
            placeholder="Select a role to mention...",
            min_values=1,
            max_values=1,
        )
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wizard.notif_role = self.values[0]
        await interaction.response.edit_message(
            embed=self.wizard.step3_embed(),
            view=self.wizard.step3_view(),
        )


class EarnToggleSelect(discord.ui.Select):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(
            placeholder="Select commands to disable (optional)...",
            min_values=0,
            max_values=2,
            options=[
                discord.SelectOption(
                    label="Daily",
                    value="daily",
                    emoji="📅",
                    description="/daily — 24h reward",
                ),
                discord.SelectOption(
                    label="Work",
                    value="work",
                    emoji="💼",
                    description="/work — 1h job reward",
                ),
                discord.SelectOption(
                    label="Rob",
                    value="rob",
                    emoji="🦹",
                    description="/rob — steal from users",
                ),
            ],
        )
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        disabled = self.values
        self.wizard.daily_enabled = "daily" not in disabled
        self.wizard.work_enabled = "work" not in disabled
        self.wizard.rob_enabled = "rob" not in disabled

        if not any(
            [
                self.wizard.daily_enabled,
                self.wizard.work_enabled,
                self.wizard.rob_enabled,
            ]
        ):
            await interaction.response.send_message(
                embed=Embeds.error(
                    "You cannot disable all three earning methods. At least one must remain active."
                ),
                ephemeral=True,
            )
            # Reset to all enabled so state is valid
            self.wizard.daily_enabled = True
            self.wizard.work_enabled = True
            self.wizard.rob_enabled = True
            return

        # Show updated preview — user must press Done to save
        enabled = [
            k
            for k, v in {
                "Daily": self.wizard.daily_enabled,
                "Work": self.wizard.work_enabled,
                "Rob": self.wizard.rob_enabled,
            }.items()
            if v
        ]
        disabled_names = [
            k
            for k, v in {
                "Daily": self.wizard.daily_enabled,
                "Work": self.wizard.work_enabled,
                "Rob": self.wizard.rob_enabled,
            }.items()
            if not v
        ]
        preview = self.wizard.step3_embed()
        suffix = f"\n\n> Enabled: {', '.join(f'`{n}`' for n in enabled)}" + (
            f"\n> Disabled: {', '.join(f'`{n}`' for n in disabled_names)}"
            if disabled_names
            else ""
        )
        preview.description = (preview.description or "") + suffix
        await interaction.response.edit_message(embed=preview, view=self.wizard)


class DoneButton(discord.ui.Button):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(label="Done", style=discord.ButtonStyle.success, emoji="✅")
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.wizard.show_summary(interaction)


class SkipButton(discord.ui.Button):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(
            label="Skip — no role mention",
            style=discord.ButtonStyle.secondary,
            emoji="⏭️",
        )
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=self.wizard.step3_embed(),
            view=self.wizard.step3_view(),
        )


class CancelButton(discord.ui.Button):
    def __init__(self, wizard: InitWizard) -> None:
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wizard.stop()
        await interaction.response.edit_message(
            embed=Embeds.info(
                "Setup cancelled. Run `/init` again whenever you're ready."
            ),
            view=None,
        )


class Init(commands.Cog):
    """Server setup wizard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="init", description="Set up Denki for your server. Admin only."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def init_slash(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        await db.get_or_create_guild(interaction.guild.id)
        await db.get_or_create_guild_config(interaction.guild.id)

        wizard = InitWizard(guild_id=interaction.guild.id, admin=member)

        await interaction.response.send_message(
            embed=wizard.step1_embed(),
            view=wizard.step1_view(),
            ephemeral=True,
        )

    @init_slash.error
    async def init_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=Embeds.error(
                    "You need **Administrator** permission to run `/init`."
                ),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Init(bot))
