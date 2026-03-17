from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive
import db
import embeds as embeds_module
from embeds import Embeds

load_dotenv()

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("denki")

# Config

TOKEN: str = os.getenv("DISCORD_TOKEN", "")
PREFIX: str = "!d "
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

if not TOKEN:
    logger.critical("DISCORD_TOKEN is not set. Bot cannot start.")
    raise RuntimeError("DISCORD_TOKEN is not set.")

if not OWNER_ID:
    logger.warning("OWNER_ID is not set. Owner-only commands will not work.")

# Cogs

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
    "cogs.blacktea",
]

# Bot setup

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    owner_id=OWNER_ID,
    help_command=None,
)


# Global ban check
# Runs before every command — blocks banned users immediately

@bot.check
async def global_ban_check(ctx: commands.Context[Any]) -> bool:
    if await db.is_banned(ctx.author.id):
        await ctx.reply(embed=Embeds.error("You have been banned from Denki. If you believe this is a mistake, contact the bot owner."))
        return False
    return True


# Global slash command ban check

# Set as attribute (not decorator) to avoid "coroutine never awaited" warning on shutdown
async def slash_ban_check(interaction: discord.Interaction) -> bool:
    if await db.is_banned(interaction.user.id):
        await interaction.response.send_message(
            embed=Embeds.error("You have been banned from Denki. If you believe this is a mistake, contact the bot owner."),
            ephemeral=True,
        )
        return False
    return True

bot.tree.interaction_check = slash_ban_check  # type: ignore[assignment]


# Events

@bot.event
async def on_ready() -> None:
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")
    logger.info(f"Prefix: {PREFIX!r} | Owner ID: {OWNER_ID}")

    # Load season color into embed cache
    await embeds_module.refresh_season_color()
    logger.info("Season color cache refreshed")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="the global economy ⚡",
        )
    )

    synced: list[Any] = []
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands globally")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    invite_url = f"https://discord.com/oauth2/authorize?client_id={bot.user.id if bot.user else 'unknown'}&permissions=8&scope=bot%20applications.commands"
    logger.info("─────────────────────────────────────────────")
    logger.info("⚡ Denki is online and ready.")
    logger.info(f"Invite: {invite_url}")
    logger.info("─────────────────────────────────────────────")

    print("\n" + "─" * 50)
    print("  ⚡ Denki is online")
    print(f"  Logged in as: {bot.user}")
    print(f"  Servers: {len(bot.guilds)}")
    print(f"  Slash commands synced: {len(synced)}")
    print(f"  Invite URL: {invite_url}")
    print("─" * 50 + "\n")


@bot.event
async def on_disconnect() -> None:
    logger.warning("Denki disconnected from Discord gateway.")


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    """Register guild and config when bot joins a new server."""
    await db.get_or_create_guild(guild.id)
    await db.get_or_create_guild_config(guild.id)
    logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")


@bot.event
async def on_member_join(member: discord.Member) -> None:
    """Check member count and update guilds.global flag if threshold reached."""
    guild = member.guild
    if guild.member_count and guild.member_count >= 250:
        await db.set_guild_global(guild.id, True)
        logger.info(f"Guild {guild.id} unlocked global leaderboard ({guild.member_count} members)")


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    """Re-check member count if someone leaves — may lose global status."""
    guild = member.guild
    if guild.member_count and guild.member_count < 250:
        await db.set_guild_global(guild.id, False)
        logger.info(f"Guild {guild.id} lost global leaderboard status ({guild.member_count} members)")


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
    logger.error(f"Unhandled command error in {ctx.command}: {error}", exc_info=error)
    await ctx.reply(embed=Embeds.error("Something went wrong. Please try again."))


# Entry point

async def main() -> None:
    keep_alive()
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}", exc_info=e)

        try:
            await bot.start(TOKEN)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested — Denki stopped cleanly.")