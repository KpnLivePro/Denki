from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

import db
import ui as ui_module
from cogs.logz import DenkiBot
from ui import UI as Embeds

# ── Logging Setup ─────────────────────────────────────────────────────────────
IS_LOCAL = os.environ.get("ENV", "production") == "development" or not os.environ.get(
    "CONTAINER_APP_NAME"
)

if IS_LOCAL:
    try:
        import colorama
        from colorama import Fore, Style

        colorama.init(autoreset=True)

        class ColorFormatter(logging.Formatter):
            COLORS = {
                logging.DEBUG: Fore.CYAN,
                logging.INFO: Fore.GREEN,
                logging.WARNING: Fore.YELLOW,
                logging.ERROR: Fore.RED,
                logging.CRITICAL: Fore.MAGENTA,
            }

            def format(self, record: logging.LogRecord) -> str:
                color = self.COLORS.get(record.levelno, "")
                record.levelname = f"{color}[{record.levelname}]{Style.RESET_ALL}"
                record.name = f"{Fore.CYAN}{record.name}{Style.RESET_ALL}"
                return super().format(record)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColorFormatter("[%(levelname)s] %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except ImportError:
        logging.basicConfig(
            level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s"
        )
else:
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s"
    )

for noisy in ("httpx", "httpcore", "discord.http", "discord.gateway", "discord.client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("denki")

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
TOPGG_TOKEN = os.environ.get("TOPGG_TOKEN", "")
BOT_ID = 1422399195062734881
PREFIX = "!d "

if not TOKEN:
    logger.critical("DISCORD_TOKEN is missing!")
    sys.exit(1)

# ── Automatic Cog Detection ───────────────────────────────────────────────────
COGS_DIR = Path("cogs")


def get_cogs() -> list[str]:
    """Automatically detect all cogs in the cogs/ folder."""
    if not COGS_DIR.exists():
        logger.warning("cogs/ directory not found!")
        return []

    cogs = []
    for file in sorted(COGS_DIR.glob("*.py")):  # sorted for consistent load order
        if file.stem.startswith("_"):  # Skip __init__.py and _private files
            continue
        cogs.append(f"cogs.{file.stem}")

    # Ensure help cog loads first (important for custom help command)
    if "cogs.help" in cogs:
        cogs.remove("cogs.help")
        cogs.insert(0, "cogs.help")

    return cogs


# ── Bot Class ─────────────────────────────────────────────────────────────────
class Denki(DenkiBot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX),
            intents=intents,
            owner_id=OWNER_ID,
            help_command=None,  # Disabled default help
        )

        self.topgg_token = TOPGG_TOKEN
        self.bot_id = BOT_ID
        self.logger = logging.getLogger("denki.main")

    async def setup_hook(self) -> None:
        # Auto-load all cogs
        cogs = get_cogs()
        for cog in cogs:
            try:
                await self.load_extension(cog)
                self.logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                self.logger.error(f"Failed to load {cog}: {e}", exc_info=True)

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} slash commands")
        except Exception as e:
            self.logger.error(f"Slash sync failed: {e}")

        # Prime embed color from active season
        await ui_module.refresh_season_color()

        self.logger.info("Denki is ready!")


bot = Denki()


# ── Global Ban Check ──────────────────────────────────────────────────────────
@bot.check
async def global_ban_check(ctx: commands.Context) -> bool:
    if await db.is_banned(ctx.author.id):
        await ctx.reply(
            embed=Embeds.error(ctx.author, "You have been banned from Denki.")
        )
        return False
    return True


async def slash_ban_check(inter: discord.Interaction) -> bool:
    if await db.is_banned(inter.user.id):
        await inter.response.send_message(
            embed=Embeds.error(inter.user, "You have been banned from Denki."),
            ephemeral=True,
        )
        return False
    return True


bot.tree.interaction_check = slash_ban_check


# ── Entry Point ───────────────────────────────────────────────────────────────
async def main() -> None:
    async with bot:
        try:
            await bot.start(TOKEN)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.critical("Bot crashed!", exc_info=True)
        finally:
            if hasattr(bot, "log"):
                await bot.log.offline()


if __name__ == "__main__":
    asyncio.run(main())
