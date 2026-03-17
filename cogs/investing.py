from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.investing")

MIN_INVEST       = 100
MEMBER_MIN_DAYS  = 30  # Must be in server this many days to invest


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


def _days_remaining(season: dict) -> int:
    """Calculate days left in a season."""
    import math
    end = datetime.fromisoformat(season["end"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, math.ceil((end - now).total_seconds() / 86400))


def _member_days(member: discord.Member) -> int:
    """How many days a member has been in the server."""
    joined = member.joined_at
    if not joined:
        return 0
    joined_aware = joined if joined.tzinfo else joined.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - joined_aware
    return delta.days


class Investing(commands.Cog):
    """Investing commands — invest, vault."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # Invest

    @app_commands.command(name="invest", description="Invest ¥ Yen into your server's season vault.")
    @app_commands.describe(amount="Amount to invest in the vault — minimum ¥100, locked until season ends")
    async def invest_slash(self, interaction: discord.Interaction, amount: int) -> None:
        await self._invest(interaction, amount=amount, is_slash=True)

    @commands.command(name="invest", aliases=["inv"])
    async def invest_prefix(self, ctx: commands.Context[Any], amount: int) -> None:
        await self._invest(ctx, amount=amount, is_slash=False)

    async def _invest(self, ctx_or_interaction: Any, amount: int, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild   = ctx_or_interaction.guild
        member  = guild.get_member(author.id) or author

        # Check minimum invest amount
        if amount < MIN_INVEST:
            return await _respond(
                ctx_or_interaction,
                Embeds.error(f"Minimum investment is ¥{MIN_INVEST:,}."),
                is_slash,
            )

        # Check 30-day membership rule
        days_in_server = _member_days(member)
        if days_in_server < MEMBER_MIN_DAYS:
            days_needed = MEMBER_MIN_DAYS - days_in_server
            return await _respond(
                ctx_or_interaction,
                Embeds.error(
                    f"You must be a member of this server for **{MEMBER_MIN_DAYS} days** to invest.\n"
                    f"> You joined **{days_in_server}** days ago — `{days_needed}` days remaining."
                ),
                is_slash,
            )

        # Check active season
        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("There is no active season right now. Investing is closed."),
                is_slash,
            )

        season_id: int = int(season["season_id"])
        season_name: str = str(season["name"])

        # Check wallet balance
        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])
        if amount > wallet:
            return await _respond(
                ctx_or_interaction,
                Embeds.error(f"Insufficient funds. Wallet: ¥{wallet:,}."),
                is_slash,
            )

        # Ensure guild is registered
        await db.get_or_create_guild(guild.id)

        # Place investment
        try:
            bank = await db.add_investment(author.id, guild.id, season_id, amount)
        except ValueError as e:
            return await _respond(ctx_or_interaction, Embeds.error(str(e)), is_slash)

        vault_total = await db.get_season_vault_total(guild.id, season_id)
        await db.log_transaction(author.id, 0, amount, "invest")

        embed = Embeds.invest(
            user=author,
            amount=amount,
            total_invested=int(bank["invested"]),
            vault_total=vault_total,
            season_name=season_name,
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # Vault

    @app_commands.command(name="vault", description="View your server's season vault and top investors.")
    async def vault_slash(self, interaction: discord.Interaction) -> None:
        await self._vault(interaction, is_slash=True)

    @commands.command(name="vault", aliases=["v"])
    async def vault_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._vault(ctx, is_slash=False)

    async def _vault(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        guild = ctx_or_interaction.guild

        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("There is no active season right now."),
                is_slash,
            )

        season_id: int   = int(season["season_id"])
        season_name: str = str(season["name"])

        vault_total    = await db.get_season_vault_total(guild.id, season_id)
        top_investors  = await db.get_top_investors(guild.id, season_id, limit=7)
        days_left      = _days_remaining(season)

        embed = Embeds.vault(
            guild_name=guild.name,
            season_name=season_name,
            days_remaining=days_left,
            vault_total=vault_total,
            top_investors=top_investors,
        )
        await _respond(ctx_or_interaction, embed, is_slash)



async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    """Defer a slash interaction immediately to extend the 3-second response window."""
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Investing(bot))