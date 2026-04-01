from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from typing import Any

import discord
from discord.ext import commands

import db
import ui as ui_module
from cogs.logz import DenkiBot
from ui import UI as Embeds

# ── Logging ───────────────────────────────────────────────────────────────────

# Prefer an explicit ENV var; fall back to absence of the ACA env var.
IS_LOCAL: bool = os.environ.get("ENV", "production") == "development" or not os.environ.get(
    "CONTAINER_APP_NAME"
)

if IS_LOCAL:
    try:
        import colorama
        from colorama import Fore, Style

        colorama.init(autoreset=True)

        class ColorFormatter(logging.Formatter):
            COLORS = {
                logging.DEBUG:    Fore.CYAN,
                logging.INFO:     Fore.GREEN,
                logging.WARNING:  Fore.YELLOW,
                logging.ERROR:    Fore.RED,
                logging.CRITICAL: Fore.MAGENTA,
            }

            def format(self, record: logging.LogRecord) -> str:
                color = self.COLORS.get(record.levelno, "")
                record.levelname = f"{color}[{record.levelname}]{Style.RESET_ALL}"
                record.name      = f"{Fore.CYAN}{record.name}{Style.RESET_ALL}"
                return super().format(record)

        _handler = logging.StreamHandler(sys.stdout)
        _handler.setFormatter(ColorFormatter("[%(levelname)s] %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[_handler])

    except ImportError:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(name)s: %(message)s",
            stream=sys.stdout,
        )
else:
    # Azure Container Apps — plain text, no ANSI codes
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

# Silence noisy third-party loggers
for _noisy in ("httpx", "httpcore", "discord.http", "discord.gateway", "discord.client"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("denki")

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN:       str = os.environ.get("DISCORD_TOKEN", "")
OWNER_ID:    int = int(os.environ.get("OWNER_ID", "0") or "0")
TOPGG_TOKEN: str = os.environ.get("TOPGG_TOKEN", "")
BOT_ID:      int = 1422399195062734881
PREFIX:      str = "!d "
INVITE:      str = (
    "https://discord.com/oauth2/authorize"
    "?client_id=1422399195062734881&permissions=8&scope=bot+applications.commands"
)

if not TOKEN:
    logger.critical("DISCORD_TOKEN is not set — cannot start.")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID is not set — sudo commands will not work.")

if not TOPGG_TOKEN:
    logger.warning("TOPGG_TOKEN is not set — /vote rewards will not work.")

# ── Cogs ──────────────────────────────────────────────────────────────────────

COGS: list[str] = [
    "cogs.logz",        # must be first — attaches bot.log before other cogs need it
    "cogs.help",
    "cogs.init",
    "cogs.economy",
    "cogs.gambling",
    "cogs.investing",
    "cogs.seasons",
    "cogs.shop",
    "cogs.leaderboard",
    "cogs.admin",
    "cogs.sudo",
    "cogs.notifications",
    "cogs.tea",
    "cogs.arcade",
    "cogs.website_push",
]

# ── Bot subclass ──────────────────────────────────────────────────────────────

class Denki(DenkiBot):
    """
    Bot subclass that loads extensions and syncs the command tree
    inside setup_hook — the correct discord.py 2.x pattern.
    This guarantees cogs are loaded before the bot connects to the gateway.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members          = True

        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            owner_id=OWNER_ID,
            help_command=None,
        )
        # Expose runtime tokens to cogs via bot attributes
        self.topgg_token: str = TOPGG_TOKEN
        self.bot_id:      int = BOT_ID

    async def setup_hook(self) -> None:
        """Called once after login, before connecting to the gateway."""
        # Load all cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("denki.cog action=loaded name=%s", cog)
            except Exception as exc:
                logger.error(
                    "denki.cog action=failed name=%s error=%r",
                    cog, str(exc), exc_info=exc,
                )

        # Sync slash commands globally once on startup.
        # On local dev you may want to guild-sync for instant propagation:
        # await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
        try:
            synced = await self.tree.sync()
            logger.info("denki.startup synced=%d slash commands", len(synced))
        except Exception as exc:
            logger.error("denki.startup slash sync failed: %s", exc)

        # Prime the embed colour cache from the active season
        await ui_module.refresh_season_color()


bot = Denki()

# ── Global checks ─────────────────────────────────────────────────────────────

@bot.check
async def global_ban_check(ctx: commands.Context[Any]) -> bool:
    if await db.is_banned(ctx.author.id):
        await ctx.reply(
            embed=Embeds.error(
                "You have been banned from Denki. "
                "If you believe this is a mistake, contact the bot owner."
            )
        )
        return False
    return True


async def slash_ban_check(interaction: discord.Interaction) -> bool:
    if await db.is_banned(interaction.user.id):
        await interaction.response.send_message(
            embed=Embeds.error(
                "You have been banned from Denki. "
                "If you believe this is a mistake, contact the bot owner."
            ),
            ephemeral=True,
        )
        return False
    return True


bot.tree.interaction_check = slash_ban_check  # type: ignore[assignment]

# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready() -> None:
    assert bot.user is not None
    logger.info(
        "denki.startup bot=%s id=%s guilds=%d",
        str(bot.user), bot.user.id, len(bot.guilds),
    )
    logger.info("denki.startup invite=%s", INVITE)
    logger.info("denki.startup topgg_configured=%s", bool(TOPGG_TOKEN))
    logger.info("denki.startup status=ready")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="the global economy ⚡",
        )
    )


@bot.event
async def on_disconnect() -> None:
    logger.warning("denki.gateway status=disconnected")


@bot.event
async def on_resumed() -> None:
    logger.info("denki.gateway status=resumed")


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await db.get_or_create_guild(guild.id)
    await db.get_or_create_guild_config(guild.id)
    icon_url = str(guild.icon.url) if guild.icon else None
    await db.update_guild_meta(guild.id, guild.name, icon_url)
    logger.info(
        "denki.guild action=join id=%d name=%r members=%d",
        guild.id, guild.name, guild.member_count or 0,
    )
    if hasattr(bot, "log"):
        await bot.log.info(
            "Guild Joined",
            f"> **{guild.name}** (`{guild.id}`)\n> Members: `{guild.member_count or 0}`",
        )


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    logger.info("denki.guild action=leave id=%d name=%r", guild.id, guild.name)
    if hasattr(bot, "log"):
        await bot.log.warn("Guild Left", f"> **{guild.name}** (`{guild.id}`)")


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
    if before.name != after.name or before.icon != after.icon:
        icon_url = str(after.icon.url) if after.icon else None
        await db.update_guild_meta(after.id, after.name, icon_url)
        logger.info(
            "denki.guild action=update id=%d name=%r icon_changed=%s",
            after.id, after.name, before.icon != after.icon,
        )


@bot.event
async def on_member_join(member: discord.Member) -> None:
    guild      = member.guild
    guild_data = await db.get_guild(guild.id)
    if not guild_data:
        return
    if guild.member_count and guild.member_count >= 250:
        await db.set_guild_global(guild.id, True)
        logger.info(
            "denki.guild action=global_unlock id=%d members=%d",
            guild.id, guild.member_count,
        )


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    guild      = member.guild
    guild_data = await db.get_guild(guild.id)
    if not guild_data:
        return
    if guild.member_count and guild.member_count < 250:
        await db.set_guild_global(guild.id, False)
        logger.info(
            "denki.guild action=global_revoke id=%d members=%d",
            guild.id, guild.member_count,
        )


@bot.event
async def on_command_error(ctx: commands.Context[Any], error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.NotOwner):
        await ctx.reply(embed=Embeds.error("This command is restricted to the bot owner."))
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(embed=Embeds.error("You don't have permission to use this command."))
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(embed=Embeds.error(f"Missing argument: `{error.param.name}`"))
        return
    if isinstance(error, commands.BadArgument):
        await ctx.reply(embed=Embeds.error(f"Bad argument: {error}"))
        return
    if isinstance(error, commands.CheckFailure):
        return

    logger.error(
        "denki.command error=%r command=%r",
        str(error), str(ctx.command),
        exc_info=error,
    )
    await ctx.reply(embed=Embeds.error("Something went wrong. The error has been logged."))


@bot.event
async def on_error(event: str, *args: Any, **kwargs: Any) -> None:
    tb = traceback.format_exc()
    if not tb or tb.strip() == "NoneType: None":
        return
    logger.error("denki.event error event=%r", event, exc_info=True)
    if hasattr(bot, "log"):
        await bot.log.error(
            f"Event Error — `{event}`",
            tb[:500],
            context=f"Event: {event}",
        )

# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with bot:
        try:
            await bot.start(TOKEN)
        except asyncio.CancelledError:
            pass
        finally:
            if hasattr(bot, "log"):
                await bot.log.offline()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("denki.shutdown reason=keyboard_interrupt")