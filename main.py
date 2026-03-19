from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import discord
from discord.ext import commands

import db
import embeds as embeds_module
from embeds import Embeds

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("denki")

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN:        str = os.environ.get("DISCORD_TOKEN", "")
OWNER_ID:     int = int(os.environ.get("OWNER_ID", "0"))
TOPGG_TOKEN:  str = os.environ.get("TOPGG_TOKEN", "")
BOT_ID:       int = 1422399195062734881
PREFIX:       str = "!d "
INVITE:       str = "https://discord.com/oauth2/authorize?client_id=1422399195062734881&permissions=8&scope=bot+applications.commands"

if not TOKEN:
    logger.critical("DISCORD_TOKEN is not set — cannot start.")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID is not set — sudo commands will not work.")

if not TOPGG_TOKEN:
    logger.warning("TOPGG_TOKEN is not set — /vote rewards will not work.")

# ── Cogs ──────────────────────────────────────────────────────────────────────

COGS: list[str] = [
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
]

# ── Bot ───────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    owner_id=OWNER_ID,
    help_command=None,
)

# Attach top.gg config so cogs can access via self.bot
bot.topgg_token = TOPGG_TOKEN  # type: ignore[attr-defined]
bot.bot_id      = BOT_ID       # type: ignore[attr-defined]

# ── Global checks ─────────────────────────────────────────────────────────────

@bot.check
async def global_ban_check(ctx: commands.Context[Any]) -> bool:
    if await db.is_banned(ctx.author.id):
        await ctx.reply(embed=Embeds.error(
            "You have been banned from Denki. "
            "If you believe this is a mistake, contact the bot owner."
        ))
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
    user_id   = bot.user.id   if bot.user else "unknown"
    user_name = str(bot.user) if bot.user else "unknown"

    await embeds_module.refresh_season_color()

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="the global economy ⚡",
        )
    )

    try:
        synced = await bot.tree.sync()
        synced_count = len(synced)
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")
        synced_count = 0

    logger.info("denki.startup bot=%s id=%s guilds=%d cogs=%d commands=%d",
        user_name, user_id, len(bot.guilds), len(COGS), synced_count)
    logger.info("denki.startup invite=%s", INVITE)
    logger.info("denki.startup topgg_configured=%s", bool(TOPGG_TOKEN))
    logger.info("denki.startup status=ready")


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
    logger.info("denki.guild action=join id=%d name=%r members=%d",
        guild.id, guild.name, guild.member_count or 0)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    guild = member.guild
    if guild.member_count and guild.member_count >= 250:
        await db.set_guild_global(guild.id, True)
        logger.info("denki.guild action=global_unlock id=%d members=%d",
            guild.id, guild.member_count)


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    guild = member.guild
    if guild.member_count and guild.member_count < 250:
        await db.set_guild_global(guild.id, False)
        logger.info("denki.guild action=global_revoke id=%d members=%d",
            guild.id, guild.member_count)


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
    logger.error("denki.command error=%r command=%r", str(error), str(ctx.command), exc_info=error)
    await ctx.reply(embed=Embeds.error("Something went wrong. Please try again."))


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info("denki.cog action=loaded name=%s", cog)
            except Exception as e:
                logger.error("denki.cog action=failed name=%s error=%r", cog, str(e), exc_info=e)

        try:
            await bot.start(TOKEN)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("denki.shutdown reason=keyboard_interrupt")