"""
cogs/logz.py  —  Denki
Runtime log shipping to a Discord channel via webhook.

Each log entry is its own embed following the unified Denki embed format.
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

# ── Config ────────────────────────────────────────────────────────────────────

_raw_channel_id = os.environ.get("LOG_CHANNEL_ID", "0")
LOG_CHANNEL_ID: int = int(_raw_channel_id) if _raw_channel_id.isdigit() else 0

WEBHOOK_NAME   = "Denki Logs"
MAX_QUEUE      = 500
FLUSH_INTERVAL = 2.0

logger = logging.getLogger("denki.logz")


# ── Embed builder ─────────────────────────────────────────────────────────────

def _record_to_embed(record: logging.LogRecord) -> discord.Embed:
    """Convert a stdlib LogRecord to a unified-style Denki embed."""
    from embeds import get_color

    msg = record.getMessage()
    if record.exc_info:
        tb  = "".join(traceback.format_exception(*record.exc_info))
        msg = f"{msg}\n```py\n{tb[:1800]}\n```"
    elif len(msg) > 3800:
        msg = msg[:3800] + "\n… (truncated)"

    if record.levelno >= logging.CRITICAL:
        icon, label = "‼️", "CRITICAL"
    elif record.levelno >= logging.ERROR:
        icon, label = "❌", "ERROR"
    elif record.levelno >= logging.WARNING:
        icon, label = "⚠️", "WARNING"
    else:
        icon, label = "🔵", "INFO"

    ts = f"<t:{int(record.created)}:T>"

    return discord.Embed(
        description=f"> `{icon}` *{label} — `{record.name}` {ts}*\n\n{msg}",
        color=get_color(),
    )


# ── Queue handler ─────────────────────────────────────────────────────────────

class _DiscordQueueHandler(logging.Handler):
    """Thread-safe logging.Handler — puts LogRecords onto an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue[logging.LogRecord]) -> None:
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("denki.logz"):
            return  # infinite recursion guard
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            pass


# ── DiscordLogger ─────────────────────────────────────────────────────────────

class DiscordLogger:
    """Facade used by call sites (bot.log.error / .cmd / etc.)."""

    def __init__(self, queue: asyncio.Queue[logging.LogRecord]) -> None:
        self._queue = queue

    def _push(self, level: int, msg: str) -> None:
        record = logging.LogRecord(
            name     = "denki.main",
            level    = level,
            pathname = "",
            lineno   = 0,
            msg      = msg,
            args     = (),
            exc_info = None,
        )
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            pass

    # ── Named methods ─────────────────────────────────────────────────────────

    async def online(self, guild_count: int, command_count: int) -> None:
        self._push(logging.INFO, (
            f"> `🟢` *Denki is online*\n\n"
            f"> `🏠` Guilds: `{guild_count}`\n"
            f"> `⚡` Commands: `{command_count}`\n"
            f"> `☁️` Environment: `Azure Container Apps`"
        ))

    async def offline(self) -> None:
        self._push(logging.WARNING, "> `🔴` *Denki is shutting down.*")

    async def restart(self, triggered_by: str) -> None:
        self._push(logging.WARNING, (
            f"> `🔁` *Denki is restarting*\n\n"
            f"> `👤` Triggered by: `{triggered_by}`"
        ))

    async def cog_fail(self, cog_name: str, exc: BaseException) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._push(logging.ERROR, (
            f"> `❌` *Cog failed to load — `{cog_name}`*\n\n"
            f"```py\n{tb[:1500]}\n```"
        ))

    async def cmd(
        self,
        ctx_or_interaction,
        error: BaseException,
        note: str = "",
    ) -> None:
        is_slash = isinstance(ctx_or_interaction, discord.Interaction)
        if is_slash:
            author  = ctx_or_interaction.user
            guild   = ctx_or_interaction.guild
            cmd     = ctx_or_interaction.command
            cmd_str = f"/{cmd.name}" if cmd else "/unknown"
        else:
            author  = ctx_or_interaction.author
            guild   = ctx_or_interaction.guild
            cmd_str = (
                f"!d {ctx_or_interaction.command}"
                if ctx_or_interaction.command else "!d unknown"
            )

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        self._push(logging.ERROR, (
            f"> `❌` *Command error — `{cmd_str}`*\n\n"
            f"> `👤` User: {author.mention} `({author.id})`\n"
            f"> `🏠` Guild: `{guild}` `({guild.id if guild else 'DM'})`"
            + (f"\n> `📝` Note: `{note}`" if note else "") +
            f"\n\n```py\n{tb[:1200]}\n```"
        ))

    async def error(
        self,
        title: str,
        description: str,
        context: str = "",
        exc: Optional[BaseException] = None,
    ) -> None:
        parts = [f"> `❌` *{title}*\n\n{description}"]
        if context:
            parts.append(f"```\n{context[:400]}\n```")
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            parts.append(f"```py\n{tb[:800]}\n```")
        self._push(logging.ERROR, "\n".join(parts))

    async def warn(self, title: str, description: str, context: str = "") -> None:
        parts = [f"> `⚠️` *{title}*\n\n{description}"]
        if context:
            parts.append(f"```\n{context[:400]}\n```")
        self._push(logging.WARNING, "\n".join(parts))

    async def info(self, title: str, description: str, context: str = "") -> None:
        parts = [f"> `🔵` *{title}*\n\n{description}"]
        if context:
            parts.append(f"```\n{context[:400]}\n```")
        self._push(logging.INFO, "\n".join(parts))


# ── Typed bot subclass ────────────────────────────────────────────────────────

class DenkiBot(commands.Bot):
    log: DiscordLogger


# ── Logging Cog ───────────────────────────────────────────────────────────────

class Logging(commands.Cog):

    def __init__(self, bot: DenkiBot) -> None:
        self.bot: DenkiBot = bot

        self._queue: asyncio.Queue[logging.LogRecord] = asyncio.Queue(maxsize=MAX_QUEUE)
        bot.log = DiscordLogger(self._queue)

        self._webhook_url: Optional[str]                   = None
        self._session:     Optional[aiohttp.ClientSession] = None
        self._handler      = _DiscordQueueHandler(self._queue)
        self._task:        Optional[asyncio.Task[None]]    = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession()
        self._install_handler()
        self._task = asyncio.create_task(
            self._flush_loop(), name="denki-logz-flush"
        )

    async def cog_unload(self) -> None:
        self._uninstall_handler()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._drain()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Handler installation ──────────────────────────────────────────────────

    def _install_handler(self) -> None:
        self._handler.setLevel(logging.ERROR)
        self._handler.addFilter(
            lambda r: r.name.startswith("denki") and r.levelno >= logging.ERROR
        )
        logging.getLogger("denki").addHandler(self._handler)

    def _uninstall_handler(self) -> None:
        logging.getLogger("denki").removeHandler(self._handler)

    # ── Webhook setup ─────────────────────────────────────────────────────────

    async def _ensure_webhook(self) -> bool:
        if self._webhook_url:
            return True

        if not LOG_CHANNEL_ID:
            logger.warning(
                "LOG_CHANNEL_ID not set — Discord log shipping disabled."
            )
            return False

        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            try:
                channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                pass
        if not isinstance(channel, discord.TextChannel):
            logger.error(
                "Logz: channel %d not found — check LOG_CHANNEL_ID and bot permissions.",
                LOG_CHANNEL_ID,
            )
            return False

        try:
            webhooks = await channel.webhooks()
            existing = next((w for w in webhooks if w.name == WEBHOOK_NAME), None)
            if existing:
                self._webhook_url = existing.url
                logger.info("Logz: webhook ready (existing) — channel %d", LOG_CHANNEL_ID)
                return True

            wh = await channel.create_webhook(
                name=WEBHOOK_NAME,
                reason="Denki runtime log shipping",
            )
            self._webhook_url = wh.url
            logger.info("Logz: webhook created — channel %d", LOG_CHANNEL_ID)
            return True

        except discord.Forbidden:
            logger.error(
                "Logz: missing Manage Webhooks permission in channel %d.", LOG_CHANNEL_ID
            )
            return False
        except discord.HTTPException as e:
            logger.error("Logz: webhook setup failed — %s", e)
            return False

    # ── Flush loop ────────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL)
            await self._drain()

    async def _drain(self) -> None:
        if not self._webhook_url:
            return

        batch: list[logging.LogRecord] = []
        try:
            while True:
                record = self._queue.get_nowait()
                batch.append(record)
                if len(batch) >= 10:
                    await self._ship(batch)
                    batch = []
        except asyncio.QueueEmpty:
            pass

        if batch:
            await self._ship(batch)

    async def _ship(self, records: list[logging.LogRecord]) -> None:
        if not self._webhook_url or not self._session or self._session.closed:
            return

        # Each record is its own embed — send individually so they don't merge
        for record in records:
            embed   = _record_to_embed(record)
            payload = {
                "embeds": [embed.to_dict()],
                "flags":  4096,  # SUPPRESS_NOTIFICATIONS — @silent
            }
            try:
                async with self._session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 429:
                        retry_after = float((await resp.json()).get("retry_after", 2.0))
                        await asyncio.sleep(retry_after)
            except Exception:
                pass  # never crash the bot over a log message

    # ── Events ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        ok = await self._ensure_webhook()
        if not ok:
            return
        assert self.bot.user is not None
        await self.bot.log.online(
            guild_count   = len(self.bot.guilds),
            command_count = len(self.bot.tree.get_commands()),
        )
        await self._drain()

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        ignored = (
            commands.CommandNotFound,
            commands.NotOwner,
            commands.MissingPermissions,
            commands.MissingRequiredArgument,
            commands.BadArgument,
            commands.CheckFailure,
        )
        if isinstance(error, ignored):
            return
        real = getattr(error, "original", error)
        await self.bot.log.cmd(ctx, real)

    @commands.Cog.listener()
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        ignored = (
            discord.app_commands.MissingPermissions,
            discord.app_commands.CheckFailure,
        )
        if isinstance(error, ignored):
            return
        real = getattr(error, "original", error)
        await self.bot.log.cmd(interaction, real)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="> `❗` *Something went wrong. The error has been logged.*",
                        color=__import__("embeds").get_color(),
                    ),
                    ephemeral=True,
                )
        except Exception:
            pass

    # ── Owner commands ────────────────────────────────────────────────────────

    @commands.command(name="setlog")
    async def setlog(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the log channel at runtime. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return
        global LOG_CHANNEL_ID
        LOG_CHANNEL_ID    = channel.id
        self._webhook_url = None
        ok     = await self._ensure_webhook()
        status = "Webhook ready" if ok else "Webhook setup failed — check permissions"
        from embeds import Embeds
        await ctx.reply(embed=Embeds.success(
            f"Log channel set to {channel.mention}.\n"
            f"> {status}\n"
            f"> Add `LOG_CHANNEL_ID={channel.id}` to your env to persist."
        ))

    @commands.command(name="logtest")
    async def logtest(self, ctx: commands.Context) -> None:
        """Fire test records at every level. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return
        from embeds import Embeds
        if not self._webhook_url:
            await ctx.reply(embed=Embeds.error(
                "Webhook not initialised.\n"
                "> Set `LOG_CHANNEL_ID` env var or use `!d setlog #channel`."
            ))
            return
        test_log = logging.getLogger("denki.logtest")
        test_log.warning("logtest WARNING — test warning ⚠️")
        test_log.error("logtest ERROR — test error ❌")
        test_log.critical("logtest CRITICAL — test critical ‼️")
        await ctx.reply(embed=Embeds.success(
            f"3 test records queued for <#{LOG_CHANNEL_ID}>.\n"
            f"> WARNING · ERROR · CRITICAL"
        ))

    @commands.command(name="logchannel")
    async def logchannel(self, ctx: commands.Context) -> None:
        """Show current log channel and webhook status. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return
        from embeds import Embeds
        if LOG_CHANNEL_ID and self._webhook_url:
            await ctx.reply(embed=Embeds.success(
                f"Log channel: <#{LOG_CHANNEL_ID}>\n> Webhook: ✅ active"
            ))
        elif LOG_CHANNEL_ID:
            await ctx.reply(embed=Embeds.error(
                f"Channel ID `{LOG_CHANNEL_ID}` set but webhook not initialised."
            ))
        else:
            await ctx.reply(embed=Embeds.error(
                "No log channel set. Use `!d setlog #channel`."
            ))


async def setup(bot: DenkiBot) -> None:
    await bot.add_cog(Logging(bot))