from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

import db
import embeds as embeds_module
from embeds import Embeds
from cogs.seasons import run_season_end

logger = logging.getLogger("denki.sudo")


def _is_owner(ctx: commands.Context[Any]) -> bool:
    return ctx.bot.owner_id == ctx.author.id


async def _respond(
    ctx: commands.Context[Any],
    embed: discord.Embed,
) -> None:
    await ctx.reply(embed=embed)


class Sudo(commands.Cog):
    """
    Owner-only commands. All commands use prefix only (!d <command>).
    These are never registered as slash commands and are invisible to all users except the owner.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context[Any]) -> bool:  # type: ignore[override]
        """Block all sudo commands from non-owners silently."""
        return await self.bot.is_owner(ctx.author)

    # Warn

    @commands.command(name="warn")
    async def warn(self, ctx: commands.Context[Any], user_id: int, *, reason: str) -> None:
        """Issue a global warn to a user. Auto-bans at 3 active warns."""
        await db.get_or_create_user(user_id)
        await db.issue_warn(user_id=user_id, reason=reason, issued_by=ctx.author.id)

        warn_count = await db.count_active_warns(user_id)

        # DM the user
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(embed=Embeds.warn_dm(reason=reason, warn_count=warn_count))
        except discord.Forbidden:
            logger.warning(f"Could not DM user {user_id} — DMs closed")
        except Exception as e:
            logger.error(f"Error DMing warn to {user_id}: {e}")

        embed = Embeds.warn_issued(
            user=await self.bot.fetch_user(user_id),
            reason=reason,
            warn_count=warn_count,
        )
        await _respond(ctx, embed)

        # Auto-ban at 3 warns
        if warn_count >= 3:
            await self._execute_ban(
                ctx=ctx,
                user_id=user_id,
                reason=f"Auto-ban: reached {warn_count} active warnings.",
                silent=True,
            )

    # Clear warn

    @commands.command(name="clearwarn")
    async def clearwarn(self, ctx: commands.Context[Any], warn_id: int) -> None:
        """Remove a specific warn by warn ID."""
        try:
            await db.clear_warn(warn_id)
            await _respond(ctx, Embeds.success(f"Warn `{warn_id}` has been cleared."))
        except Exception:
            await _respond(ctx, Embeds.error(f"Warn `{warn_id}` not found."))

    # View warns

    @commands.command(name="warns")
    async def warns(self, ctx: commands.Context[Any], user_id: int) -> None:
        """View all active warns for a user."""
        warns = await db.get_active_warns(user_id)
        try:
            user = await self.bot.fetch_user(user_id)
            username = str(user)
        except Exception:
            username = f"User {user_id}"

        if not warns:
            return await _respond(ctx, Embeds.info(f"**{username}** has no active warns."))

        embed = Embeds.base(f"> `⚠️` *Active warns for **{username}** ({len(warns)} / 3)*")
        for w in warns:
            embed.add_field(
                name=f"`#{w['warn_id']}` — {w['issued_at'][:10]}",
                value=f"> {w['reason']}\n> Expires: `{w['expires_at'][:10]}`",
                inline=False,
            )
        await _respond(ctx, embed)

    # Ban

    @commands.command(name="ban")
    async def ban(self, ctx: commands.Context[Any], user_id: int, *, reason: str = "No reason provided.") -> None:
        """Globally ban a user from Denki."""
        await self._execute_ban(ctx=ctx, user_id=user_id, reason=reason, silent=False)

    async def _execute_ban(
        self,
        ctx: commands.Context[Any],
        user_id: int,
        reason: str,
        silent: bool,
    ) -> None:
        await db.ban_user(user_id=user_id, reason=reason, banned_by=ctx.author.id)

        # DM the banned user
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(embed=Embeds.ban_dm(reason=reason))
        except discord.Forbidden:
            logger.warning(f"Could not DM ban notice to {user_id}")
        except Exception as e:
            logger.error(f"Error DMing ban to {user_id}: {e}")

        if not silent:
            try:
                user = await self.bot.fetch_user(user_id)
                username = str(user)
            except Exception:
                username = f"User {user_id}"
            await _respond(ctx, Embeds.success(f"**{username}** has been globally banned from Denki.\n> Reason: `{reason}`"))

    # Unban

    @commands.command(name="unban")
    async def unban(self, ctx: commands.Context[Any], user_id: int) -> None:
        """Remove a global Denki ban."""
        ban = await db.get_ban(user_id)
        if not ban:
            return await _respond(ctx, Embeds.error(f"User `{user_id}` is not currently banned."))

        await db.unban_user(user_id)

        try:
            user = await self.bot.fetch_user(user_id)
            username = str(user)
        except Exception:
            username = f"User {user_id}"

        await _respond(ctx, Embeds.success(f"**{username}** has been unbanned from Denki."))

    # Wallet audit

    @commands.command(name="wallet")
    async def wallet(self, ctx: commands.Context[Any], user_id: int) -> None:
        """Audit a user's full wallet and active bank records."""
        user_data = await db.get_user(user_id)
        if not user_data:
            return await _respond(ctx, Embeds.error(f"User `{user_id}` has no wallet record."))

        try:
            user = await self.bot.fetch_user(user_id)
            username = str(user)
        except Exception:
            username = f"User {user_id}"

        embed = Embeds.base(f"> `🔍` *Wallet audit — **{username}***")
        embed.add_field(name="`💴` Global wallet", value=f"```¥{int(user_data['wallet']):,}```", inline=True)
        embed.add_field(name="`🆔` User ID", value=f"```{user_id}```", inline=True)

        # Active warns
        warn_count = await db.count_active_warns(user_id)
        embed.add_field(name="`⚠️` Active warns", value=f"```{warn_count} / 3```", inline=True)

        # Ban status
        ban = await db.get_ban(user_id)
        embed.add_field(
            name="`🔨` Ban status",
            value=f"```{'Banned — ' + str(ban['reason']) if ban else 'Not banned'}```",
            inline=False,
        )

        await _respond(ctx, embed)

    # Adjust wallet

    @commands.command(name="adjust")
    async def adjust(self, ctx: commands.Context[Any], user_id: int, amount: int) -> None:
        """
        Directly adjust a user's wallet. Positive = add, negative = subtract.
        Only command that can modify users.wallet directly.
        """
        await db.get_or_create_user(user_id)

        try:
            wallet_data = await db.update_wallet(user_id, amount)
        except ValueError as e:
            return await _respond(ctx, Embeds.error(str(e)))

        await db.log_transaction(ctx.author.id, user_id, abs(amount), "admin_adjust")

        try:
            user = await self.bot.fetch_user(user_id)
            username = str(user)
        except Exception:
            username = f"User {user_id}"

        direction = "added to" if amount > 0 else "removed from"
        await _respond(ctx, Embeds.success(
            f"¥{abs(amount):,} {direction} **{username}**'s wallet.\n"
            f"> New balance: `¥{int(wallet_data['wallet']):,}`"
        ))

    # Season end

    @commands.command(name="seasonend")
    async def seasonend(self, ctx: commands.Context[Any]) -> None:
        """Manually trigger season end logic."""
        season = await db.get_active_season()
        if not season:
            return await _respond(ctx, Embeds.error("There is no active season to end."))

        # Confirmation view
        view = ConfirmView(ctx.author.id)
        await ctx.reply(
            embed=Embeds.warn_msg(
                f"Are you sure you want to end **{season['name']}** early?\n"
                "> This will trigger full season end logic including payouts and reset."
            ),
            view=view,
        )
        await view.wait()

        if view.confirmed:
            await run_season_end(self.bot, season)
            await ctx.reply(embed=Embeds.success("Season end logic completed successfully."))
        else:
            await ctx.reply(embed=Embeds.info("Season end cancelled."))

    # Season set

    @commands.command(name="seasonset")
    async def seasonset(self, ctx: commands.Context[Any], name: str, color: str = "#CD7F32") -> None:
        """
        Set the active season name and color.
        color must be a hex string e.g. #FF5733
        """
        season = await db.get_active_season()
        if not season:
            return await _respond(ctx, Embeds.error("There is no active season."))

        # Validate hex color
        try:
            clean = color.strip().lstrip("#")
            int(clean, 16)
            if len(clean) != 6:
                raise ValueError
        except ValueError:
            return await _respond(ctx, Embeds.error("Invalid color. Use a 6-digit hex e.g. `#FF5733`."))

        hex_with_hash = f"#{clean}"
        await db.update_season(int(season["season_id"]), {"name": name, "theme": hex_with_hash})
        embeds_module.set_color(hex_with_hash)

        await _respond(ctx, Embeds.success(
            f"Season updated.\n"
            f"> Name: `{name}`\n"
            f"> Color: `{hex_with_hash}`"
        ))

    # Announce

    @commands.command(name="announce")
    async def announce(self, ctx: commands.Context[Any], guild_id: int, *, message: str) -> None:
        """
        Send a custom Denki announcement to a guild's configured notification channel.
        Usage: !d announce <guild_id> <message>
        """
        config = await db.get_guild_config(guild_id)
        if not config or not config.get("notif_channel"):
            return await _respond(ctx, Embeds.error(f"Guild `{guild_id}` has no notification channel configured."))

        channel = self.bot.get_channel(int(config["notif_channel"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            return await _respond(ctx, Embeds.error("Could not find the notification channel."))

        mention = f"<@&{config['notif_role']}> " if config.get("notif_role") else ""
        embed = Embeds.base(f"> `📢` *{message}*")

        try:
            await channel.send(content=mention or None, embed=embed)
            await _respond(ctx, Embeds.success(f"Announcement sent to guild `{guild_id}`."))
        except discord.Forbidden:
            await _respond(ctx, Embeds.error("Missing permissions to send in that channel."))

    # Reports — view pending

    @commands.command(name="reports")
    async def reports(self, ctx: commands.Context[Any]) -> None:
        """View all pending reports."""
        pending = await db.get_reports(status="pending")
        if not pending:
            return await _respond(ctx, Embeds.info("No pending reports."))

        embed = Embeds.base(f"> `📋` *Pending reports ({len(pending)})*")
        for r in pending[:10]:
            embed.add_field(
                name=f"`#{r['report_id']}` — <@{r['reported_id']}>",
                value=(
                    f"> Reporter: <@{r['reporter_id']}>\n"
                    f"> Server: `{r['guild_id']}`\n"
                    f"> Reason: {r['reason']}\n"
                    f"> Wallet at time: `¥{int(r['wallet_snap']):,}`"
                ),
                inline=False,
            )
        if len(pending) > 10:
            embed.set_footer(text=f"Showing 10 of {len(pending)}")
        await _respond(ctx, embed)

    # Dismiss report

    @commands.command(name="dismiss")
    async def dismiss(self, ctx: commands.Context[Any], report_id: int) -> None:
        """Dismiss a report by ID."""
        await db.update_report_status(report_id, "dismissed")
        await _respond(ctx, Embeds.success(f"Report `{report_id}` dismissed."))


class ConfirmView(discord.ui.View):
    """Yes / No confirmation for destructive sudo actions."""

    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=30)
        self.owner_id  = owner_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        await interaction.response.edit_message(
            embed=Embeds.info("Confirmed — running season end..."), view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        await interaction.response.edit_message(
            embed=Embeds.info("Cancelled."), view=None
        )
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sudo(bot))