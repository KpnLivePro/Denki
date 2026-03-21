from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks

import db
import embeds as embeds_module
from embeds import Embeds
from cogs.notifications import notify_season_start, notify_vault_payout, notify_tier_change

logger = logging.getLogger("denki.seasons")

SEASON_BONUSES: list[int] = [5_000, 3_000, 1_500]


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


async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)


async def run_season_end(bot: commands.Bot, season: dict) -> None:
    """
    Core season end logic. Called by the background task or sudo /seasonend.

    Steps:
    1. Fetch all guilds that have banks in this season
    2. For each guild: find top 3 investors, pay bonuses, update wins/tier
    3. Close the season
    4. Create a new season
    5. Refresh embed color cache
    6. Tick Tea AI season counters — expire guilds that have used up their 3 seasons
    7. Fire notifications to each guild's configured channel
    """
    season_id: int   = int(season["season_id"])
    season_name: str = str(season["name"])
    logger.info(f"Running season end for season {season_id} — {season_name}")

    # Fetch all guild_ids that participated this season
    try:
        res = db.supabase.table("banks").select("guild_id").eq("season_id", season_id).execute()
        rows = [dict(r) for r in (res.data or [])]  # type: ignore[arg-type]
        guild_ids: list[int] = list({int(row["guild_id"]) for row in rows})
    except Exception as e:
        logger.error(f"Failed to fetch guild list for season end: {e}")
        return

    # Process each guild
    for guild_id in guild_ids:
        try:
            await _process_guild_season_end(bot, guild_id, season_id, season_name)
        except Exception as e:
            logger.error(f"Season end failed for guild {guild_id}: {e}")

    # Close the season
    await db.close_season(season_id)

    # Create a new season
    new_season = await db.create_season(name="New Season")
    logger.info(f"New season created: {new_season['season_id']}")

    # Refresh color cache to bronze default until sudo sets new color
    await embeds_module.refresh_season_color()

    # Tick Tea AI season counters — decrement and expire where needed
    expired_guilds = await db.tick_tea_ai_seasons()
    if expired_guilds:
        logger.info(f"Tea AI expired for {len(expired_guilds)} guild(s): {expired_guilds}")
        for guild_id in expired_guilds:
            try:
                config = await db.get_guild_config(guild_id)
                if config and config.get("notif_channel"):
                    channel = bot.get_channel(int(config["notif_channel"]))
                    if channel and isinstance(channel, discord.TextChannel):
                        mention = f"<@&{config['notif_role']}> " if config.get("notif_role") else ""
                        await channel.send(
                            content=mention or None,
                            embed=Embeds.base(
                                "> `🤖` *Your server's **Tea AI** subscription has expired.*\n"
                                "> Purchase it again from `/shop` to re-enable AI validation."
                            ),
                        )
            except Exception as e:
                logger.error(f"Failed to send Tea AI expiry notice to guild {guild_id}: {e}")

    # Announce new season to all guilds
    await notify_season_start(bot, new_season)


async def _process_guild_season_end(
    bot: commands.Bot,
    guild_id: int,
    season_id: int,
    season_name: str,
) -> None:
    """Handle season end logic for a single guild."""
    top_investors = await db.get_top_investors(guild_id, season_id, limit=3)
    if not top_investors:
        return

    bonuses:  dict[int, int] = {}
    name_map: dict[int, str] = {}

    for i, row in enumerate(top_investors):
        uid   = int(row["user_id"])
        bonus = SEASON_BONUSES[i] if i < len(SEASON_BONUSES) else 0

        if bonus > 0:
            await db.update_wallet(uid, bonus)
            await db.log_transaction(0, uid, bonus, "season_bonus")
            season_bank = await db.get_bank(uid, guild_id, season_id)
            if season_bank:
                db.supabase.table("banks").update({
                    "total_earned": int(season_bank["total_earned"]) + bonus
                }).eq("bank_id", season_bank["bank_id"]).execute()
            bonuses[uid] = bonus

        discord_guild = bot.get_guild(guild_id)
        if discord_guild:
            member = discord_guild.get_member(uid)
            name_map[uid] = member.display_name if member else f"User {uid}"
        else:
            name_map[uid] = f"User {uid}"

    guild_data = await db.get_guild(guild_id)
    if guild_data and guild_data.get("global"):
        updated  = await db.increment_guild_wins(guild_id)
        new_tier = int(updated["tier"])
        await notify_tier_change(bot, guild_id, new_tier=new_tier, won=True)
    else:
        if guild_data and int(guild_data.get("wins", 0)) > 0:
            await db.reset_guild_wins(guild_id)
            await notify_tier_change(bot, guild_id, new_tier=1, won=False)

    await notify_vault_payout(
        bot=bot,
        guild_id=guild_id,
        top_investors=top_investors,
        name_map=name_map,
        bonuses=bonuses,
        season={"season_id": season_id, "name": season_name},
    )


class Seasons(commands.Cog):
    """Season info command and background season end task."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.season_check_loop.start()
        logger.info("Season check loop started")

    async def cog_unload(self) -> None:
        self.season_check_loop.cancel()

    @tasks.loop(hours=1)
    async def season_check_loop(self) -> None:
        try:
            season = await db.get_active_season()
            if not season:
                logger.info("Season check: no active season found")
                return

            end = datetime.fromisoformat(season["end"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            if now >= end:
                logger.info(f"Season {season['season_id']} has expired — running season end")
                await run_season_end(self.bot, season)
        except Exception as e:
            logger.error(f"Season check loop error: {e}")

    @season_check_loop.before_loop
    async def before_season_check(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="season", description="View the current season info.")
    async def season_slash(self, interaction: discord.Interaction) -> None:
        await self._season(interaction, is_slash=True)

    @commands.command(name="season", aliases=["s"])
    async def season_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._season(ctx, is_slash=False)

    async def _season(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("There is no active season right now."),
                is_slash,
            )

        guild_id:  int = ctx_or_interaction.guild.id
        season_id: int = int(season["season_id"])
        vault_total    = await db.get_season_vault_total(guild_id, season_id)

        embed = Embeds.season_info(season=season, vault_total=vault_total)
        await _respond(ctx_or_interaction, embed, is_slash)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Seasons(bot))