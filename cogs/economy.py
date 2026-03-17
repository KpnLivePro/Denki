from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.economy")

# Cooldown durations
DAILY_COOLDOWN  = timedelta(hours=24)
WORK_COOLDOWN   = timedelta(hours=1)
ROB_COOLDOWN    = timedelta(hours=2)

# Payout config
DAILY_BASE      = 1_000

WORK_JOBS: list[tuple[str, int, int]] = [
    ("⚡ Electrical Engineer",  150, 400),
    ("🚚 Delivery Driver",      100, 300),
    ("🍕 Pizza Chef",            80, 250),
    ("💻 Freelance Developer",  200, 500),
    ("🎨 Graphic Designer",     120, 350),
    ("📦 Warehouse Worker",      90, 220),
    ("🧑‍🏫 Tutor",               100, 280),
    ("🎮 Game Tester",           75, 200),
    ("📸 Photographer",         130, 380),
    ("🌱 Plant Trader",          60, 180),
    ("🔧 Mechanic",             110, 320),
    ("📊 Data Analyst",         140, 420),
]

# Rob config
ROB_SUCCESS_BASE = 0.40
ROB_MIN_STEAL    = 0.10
ROB_MAX_STEAL    = 0.35
ROB_FINE_RATE    = 0.25
ROB_MIN_VICTIM   = 100

# Tier multipliers — index = tier (1-5)
TIER_DAILY_BONUS = [0, 0, 0.10, 0.20, 0.35, 0.50]
TIER_WORK_MULT   = [0, 1.0, 1.1, 1.25, 1.5, 2.0]
TIER_ROB_BONUS   = [0, 0, 0.02, 0.05, 0.08, 0.10]


def _format_remaining(delta: timedelta) -> str:
    """Format a timedelta into human readable string e.g. '1h 23m 10s'."""
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


async def _get_tier(guild_id: int) -> int:
    """Fetch guild tier, defaulting to 1 if not found."""
    try:
        guild = await db.get_guild(guild_id)
        return int(guild["tier"]) if guild else 1
    except Exception:
        return 1


async def _respond(
    ctx_or_interaction: Any,
    embed: discord.Embed,
    is_slash: bool,
    ephemeral: bool = False,
) -> None:
    """Send embed for both slash and prefix commands."""
    if is_slash:
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.reply(embed=embed)


async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    """Defer a slash interaction immediately to extend the 3-second response window."""
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)


class Economy(commands.Cog):
    """Core economy commands — balance, daily, work, rob, pay."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # Balance

    @app_commands.command(name="balance", description="View your ¥ Yen wallet and server bank.")
    @app_commands.describe(user="User to check (defaults to you)")
    async def balance_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        await self._balance(interaction, user=user, is_slash=True)

    @commands.command(name="balance", aliases=["bal", "b"])
    async def balance_prefix(
        self,
        ctx: commands.Context[Any],
        user: discord.Member | None = None,
    ) -> None:
        await self._balance(ctx, user=user, is_slash=False)

    async def _balance(self, ctx_or_interaction: Any, user: discord.Member | None, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        target = user or author

        wallet_data = await db.get_or_create_user(target.id)
        season = await db.get_active_season()

        if season:
            bank = await db.get_or_create_bank(target.id, ctx_or_interaction.guild.id, season["season_id"])
            season_name: str = str(season["name"])
            bank_balance: int = int(bank["balance"])
            bank_invested: int = int(bank["invested"])
        else:
            season_name = "No active season"
            bank_balance = 0
            bank_invested = 0

        embed = Embeds.balance(
            user=target,
            wallet=int(wallet_data["wallet"]),
            bank_balance=bank_balance,
            bank_invested=bank_invested,
            season_name=season_name,
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # Daily

    @app_commands.command(name="daily", description="Claim your daily ¥ Yen reward.")
    async def daily_slash(self, interaction: discord.Interaction) -> None:
        await self._daily(interaction, is_slash=True)

    @commands.command(name="daily", aliases=["d"])
    async def daily_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._daily(ctx, is_slash=False)

    async def _daily(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id: int = ctx_or_interaction.guild.id

        config = await db.get_or_create_guild_config(guild_id)
        if not config["daily_enabled"]:
            return await _respond(ctx_or_interaction, Embeds.error("The `/daily` command is disabled in this server."), is_slash)

        last = await db.get_cooldown(author.id, "daily")
        if last:
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < DAILY_COOLDOWN:
                remaining = DAILY_COOLDOWN - elapsed
                return await _respond(ctx_or_interaction, Embeds.cooldown("Daily", _format_remaining(remaining)), is_slash)

        tier = await _get_tier(guild_id)
        bonus_rate = TIER_DAILY_BONUS[min(tier, 5)]
        amount = int(DAILY_BASE * (1 + bonus_rate))

        wallet_data = await db.update_wallet(author.id, amount)
        await db.set_cooldown(author.id, "daily")
        await db.log_transaction(0, author.id, amount, "daily")

        embed = Embeds.daily(user=author, amount=amount, wallet=int(wallet_data["wallet"]))
        await _respond(ctx_or_interaction, embed, is_slash)

    # Work

    @app_commands.command(name="work", description="Work a job to earn ¥ Yen. 1-hour cooldown.")
    async def work_slash(self, interaction: discord.Interaction) -> None:
        await self._work(interaction, is_slash=True)

    @commands.command(name="work", aliases=["w"])
    async def work_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._work(ctx, is_slash=False)

    async def _work(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id: int = ctx_or_interaction.guild.id

        config = await db.get_or_create_guild_config(guild_id)
        if not config["work_enabled"]:
            return await _respond(ctx_or_interaction, Embeds.error("The `/work` command is disabled in this server."), is_slash)

        last = await db.get_cooldown(author.id, "work")
        if last:
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < WORK_COOLDOWN:
                remaining = WORK_COOLDOWN - elapsed
                return await _respond(ctx_or_interaction, Embeds.cooldown("Work", _format_remaining(remaining)), is_slash)

        tier = await _get_tier(guild_id)
        mult = TIER_WORK_MULT[min(tier, 5)]
        job, min_pay, max_pay = random.choice(WORK_JOBS)
        amount = int(random.randint(min_pay, max_pay) * mult)

        wallet_data = await db.update_wallet(author.id, amount)
        await db.set_cooldown(author.id, "work")
        await db.log_transaction(0, author.id, amount, "work")

        embed = Embeds.work(user=author, job=job, amount=amount, wallet=int(wallet_data["wallet"]))
        await _respond(ctx_or_interaction, embed, is_slash)

    # Rob

    @app_commands.command(name="rob", description="Attempt to steal ¥ Yen from a user. 2-hour cooldown.")
    @app_commands.describe(user="Who to rob")
    async def rob_slash(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._rob(interaction, target=user, is_slash=True)

    @commands.command(name="rob", aliases=["r"])
    async def rob_prefix(self, ctx: commands.Context[Any], user: discord.Member) -> None:
        await self._rob(ctx, target=user, is_slash=False)

    async def _rob(self, ctx_or_interaction: Any, target: discord.Member, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id: int = ctx_or_interaction.guild.id

        if target.id == author.id:
            return await _respond(ctx_or_interaction, Embeds.error("You can't rob yourself."), is_slash)
        if target.bot:
            return await _respond(ctx_or_interaction, Embeds.error("You can't rob bots."), is_slash)

        config = await db.get_or_create_guild_config(guild_id)
        if not config["rob_enabled"]:
            return await _respond(ctx_or_interaction, Embeds.error("The `/rob` command is disabled in this server."), is_slash)

        last = await db.get_cooldown(author.id, "rob")
        if last:
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < ROB_COOLDOWN:
                remaining = ROB_COOLDOWN - elapsed
                return await _respond(ctx_or_interaction, Embeds.cooldown("Rob", _format_remaining(remaining)), is_slash)

        victim_data = await db.get_or_create_user(target.id)
        victim_wallet = int(victim_data["wallet"])
        if victim_wallet < ROB_MIN_VICTIM:
            return await _respond(ctx_or_interaction, Embeds.error(f"{target.display_name} doesn't have enough ¥ Yen to rob."), is_slash)

        # Set cooldown immediately regardless of outcome
        await db.set_cooldown(author.id, "rob")

        tier = await _get_tier(guild_id)
        success_chance = ROB_SUCCESS_BASE + TIER_ROB_BONUS[min(tier, 5)]

        if random.random() < success_chance:
            steal_pct = random.uniform(ROB_MIN_STEAL, ROB_MAX_STEAL)
            stolen = max(1, int(victim_wallet * steal_pct))

            await db.update_wallet(target.id, -stolen)
            await db.update_wallet(author.id, stolen)
            await db.log_transaction(author.id, target.id, stolen, "rob")

            embed = Embeds.rob_success(robber=author, victim=target, stolen=stolen)
        else:
            robber_data = await db.get_or_create_user(author.id)
            fine = max(50, int(int(robber_data["wallet"]) * ROB_FINE_RATE))
            fine = min(fine, int(robber_data["wallet"]))

            await db.update_wallet(author.id, -fine)
            await db.log_transaction(author.id, 0, fine, "rob_fine")

            embed = Embeds.rob_fail(robber=author, victim=target, fine=fine)

        await _respond(ctx_or_interaction, embed, is_slash)

    # Pay

    @app_commands.command(name="pay", description="Send ¥ Yen to another user.")
    @app_commands.describe(user="Who to pay", amount="Amount to send — enter a number or 'all' for your full balance")
    async def pay_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: str,
    ) -> None:
        await self._pay(interaction, target=user, amount_str=amount, is_slash=True)

    @commands.command(name="pay", aliases=["p"])
    async def pay_prefix(
        self,
        ctx: commands.Context[Any],
        user: discord.Member,
        amount: str,
    ) -> None:
        await self._pay(ctx, target=user, amount_str=amount, is_slash=False)

    async def _pay(self, ctx_or_interaction: Any, target: discord.Member, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author

        if target.id == author.id:
            return await _respond(ctx_or_interaction, Embeds.error("You can't pay yourself."), is_slash)
        if target.bot:
            return await _respond(ctx_or_interaction, Embeds.error("You can't pay bots."), is_slash)

        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])

        if amount_str.lower() == "all":
            amount = wallet
        else:
            try:
                amount = int(amount_str)
            except ValueError:
                return await _respond(ctx_or_interaction, Embeds.error("Invalid amount. Enter a number or `all`."), is_slash)

        if amount <= 0:
            return await _respond(ctx_or_interaction, Embeds.error("Amount must be greater than ¥0."), is_slash)

        await db.get_or_create_user(target.id)

        try:
            await db.update_wallet(author.id, -amount)
        except ValueError as e:
            return await _respond(ctx_or_interaction, Embeds.error(str(e)), is_slash)

        await db.update_wallet(target.id, amount)
        await db.log_transaction(author.id, target.id, amount, "transfer")

        embed = Embeds.pay(sender=author, receiver=target, amount=amount)
        await _respond(ctx_or_interaction, embed, is_slash)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))