from __future__ import annotations

import logging

import discord
from discord.ext import commands

import db
from ui import UI

logger = logging.getLogger("denki.notifications")


async def notify_season_start(bot: commands.Bot, season: dict) -> None:
    """
    Send a season start announcement to every guild's configured notification channel.
    Called by seasons.py after a new season is created.
    """
    try:
        res = (
            db.supabase.table("guildconfig")
            .select("guild_id, notif_channel, notif_role")
            .not_.is_("notif_channel", "null")
            .execute()
        )
        configs = [dict(r) for r in (res.data or [])]  # type: ignore[arg-type]
    except Exception as e:
        logger.error(
            f"Failed to fetch guild configs for season start notification: {e}"
        )
        return

    for config in configs:
        notif_channel = config.get("notif_channel")
        if not notif_channel:
            continue

        try:
            channel = bot.get_channel(int(notif_channel))
            if not channel or not isinstance(channel, discord.TextChannel):
                continue

            # Build a fresh embed per guild so mutations don't bleed across guilds
            embed = UI.season_start(season)
            mention = (
                f"<@&{config['notif_role']}>" if config.get("notif_role") else None
            )
            await channel.send(content=mention, embed=embed)
        except discord.Forbidden:
            logger.warning(
                f"Missing permissions to send season start in guild {config.get('guild_id')}"
            )
        except Exception as e:
            logger.error(
                f"Failed to send season start to guild {config.get('guild_id')}: {e}"
            )


async def notify_vault_payout(
    bot: commands.Bot,
    guild_id: int,
    top_investors: list[dict],
    name_map: dict[int, str],
    bonuses: dict[int, int],
    season: dict,
) -> None:
    """
    Send a vault payout notification to a specific guild's notification channel.
    Called per-guild during season end.
    """
    try:
        config = await db.get_guild_config(guild_id)
        if not config or not config.get("notif_channel"):
            return

        channel = bot.get_channel(int(config["notif_channel"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        embed = UI.season_end(
            season=season,
            top_investors=top_investors,
            name_map=name_map,
            bonuses=bonuses,
        )

        mention = f"<@&{config['notif_role']}>" if config.get("notif_role") else None
        await channel.send(content=mention, embed=embed)

    except discord.Forbidden:
        logger.warning(f"Missing permissions to send vault payout in guild {guild_id}")
    except Exception as e:
        logger.error(f"Failed to send vault payout to guild {guild_id}: {e}")


async def notify_tier_change(
    bot: commands.Bot,
    guild_id: int,
    new_tier: int,
    won: bool,
) -> None:
    """
    Send a tier change notification when a guild gains or loses a tier.
    Called after increment_guild_wins or reset_guild_wins.
    """
    try:
        config = await db.get_guild_config(guild_id)
        if not config or not config.get("notif_channel"):
            return

        channel = bot.get_channel(int(config["notif_channel"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        if won:
            message = (
                f"> `🏆` *Your server won the season and advanced to **Tier {new_tier}**!*\n"
                f"> All members now receive boosted earn rewards."
            )
        else:
            message = (
                f"> `📉` *Your server's win streak has ended — dropped back to **Tier 1**.*\n"
                f"> Win a season to start climbing again."
            )

        embed = UI.base(message)
        mention = f"<@&{config['notif_role']}>" if config.get("notif_role") else None
        await channel.send(content=mention, embed=embed)

    except discord.Forbidden:
        logger.warning(f"Missing permissions to send tier change in guild {guild_id}")
    except Exception as e:
        logger.error(f"Failed to send tier change to guild {guild_id}: {e}")


class Notifications(commands.Cog):
    """
    Notification helpers used by other cogs.
    No user-facing commands — this cog exists to house
    notification logic and make it importable cleanly.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Notifications(bot))
