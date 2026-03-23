"""
cogs/logz.py  —  Denki
Discord log shipping via webhook (silent messages, no pings).

Replaces the old channel-send-based DiscordLogger with a Musubi-style
queue + webhook approach. All existing call sites (bot.log.info / .error /
.cmd / .online / .offline / .restart / .cog_fail) continue to work unchanged.

Deployment notes (Azure Container Apps):
  - Stdout logs are captured by Azure automatically — we keep StreamHandler.
  - Set LOG_CHANNEL_ID in your env (or hard-code below) to ship to Discord too.
  - The webhook is created/cached automatically; no manual setup needed.

Architecture:
  1. _DiscordQueueHandler  — thread-safe logging.Handler, puts records on an
                              asyncio.Queue (never blocks the event loop).
  2. DiscordLogger         — same public API as before (.info/.error/.cmd etc.)
                              now writes structured LogRecords into the queue
                              instead of channel.send() calls.
  3. Logging cog           — owns the queue, the aiohttp session, and the
                              background flush task. Sets up the webhook in
                              on_ready (guild cache guaranteed populated).

Silent messages: Discord flag 4096 (SUPPRESS_NOTIFICATIONS) is set on every
webhook POST so nobody gets pinged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any, Optional, cast

import aiohttp
import discord
from discord.ext import commands

# ── Config ────────────────────────────────────────────────────────────────────

# Set LOG_CHANNEL_ID env var, or hard-code a fallback integer here.
_raw_channel_id = os.environ.get("LOG_CHANNEL_ID", "0")
LOG_CHANNEL_ID: int = int(_raw_channel_id) if _raw_channel_id.isdigit() else 0

WEBHOOK_NAME    = "Denki Logs"
MAX_QUEUE       = 500
FLUSH_INTERVAL  = 2.0    # seconds between drain cycles

logger = logging.getLogger("denki.logz")


# ── Level helpers ─────────────────────────────────────────────────────────────

def _level_icon(level: int) -> str:
    if level >= logging.CRITICAL: return "‼️"
    if level >= logging.ERROR:    return "❌"
    if level >= logging.WARNING:  return "⚠️"
    return "🔵"


def _level_color(level: int) -> int:
    if level >= logging.CRITICAL: return 0xFF0000
    if level >= logging.ERROR:    return 0xFF4444
    if level >= logging.WARNING:  return 0xFFAA00
    return 0x5793F2   # Denki default blue


# ── Embed builder ─────────────────────────────────────────────────────────────

def _record_to_embed(record: logging.LogRecord) -> discord.Embed:
    icon  = _level_icon(record.levelno)
    color = _level_color(record.levelno)
    ts    = f"<t:{int(record.created)}:T>"

    msg = record.getMessage()
    if record.exc_info:
        tb  = "".join(traceback.format_exception(*record.exc_info))
        msg = f"{msg}\n{tb}"
    if len(msg) > 3800:
        msg = msg[:3800] + "\n… (truncated)"

    body = f"```\n{msg}\n```" if record.levelno >= logging.ERROR else f"> *{msg}*"

    return discord.Embed(
        description=f"> `{icon}` `[{record.name}]` {ts}\n{body}",
        color=color,
    )


def _raw_embed(level: int, title: str, description: str, fields: Optional[dict[str, str]] = None) -> discord.Embed:
    """Build a structured embed for DiscordLogger's named methods."""
    color = _level_color(level)
    icon  = _level_icon(level)
    embed = discord.Embed(
        title=f"{icon}  {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    for name, value in (fields or {}).items():
        embed.add_field(name=name, value=value[:512], inline=False)
    return embed


# ── Queue handler ─────────────────────────────────────────────────────────────

class _DiscordQueueHandler(logging.Handler):
    """
    Thread-safe logging.Handler — puts records onto an asyncio.Queue.
    Never blocks; drops silently when the queue is full.
    """

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        # Guard: never log ourselves (infinite recursion)
        if record.name.startswith("denki.logz"):
            return
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            pass


# ── DiscordLogger — same public API as before ─────────────────────────────────

class DiscordLogger:
    """
    Drop-in replacement for the old DiscordLogger.
    All existing call sites work unchanged:
        await bot.log.info("Title", "description")
        await bot.log.error("Title", "description", exc=e)
        await bot.log.cmd(ctx_or_interaction, error)
        await bot.log.online(guild_count, command_count)
        await bot.log.offline()
        await bot.log.restart(triggered_by)
        await bot.log.cog_fail(cog_name, exc)

    Internally each call enqueues a pre-built embed dict that the
    flush loop ships via webhook.
    """

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self._queue: asyncio.Queue[Any] = queue

    def _enqueue(self, embed: discord.Embed) -> None:
        # We ship pre-built embeds as dicts to avoid pickling discord objects
        try:
            self._queue.put_nowait(("embed", embed.to_dict()))
        except asyncio.QueueFull:
            pass

    # ── Named log methods ─────────────────────────────────────────────────────

    async def error(
        self,
        title: str,
        description: str,
        context: str = "",
        exc: Optional[BaseException] = None,
    ) -> None:
        fields: dict[str, str] = {}
        if context:
            fields["Context"] = f"```\n{context[:400]}\n```"
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            fields["Traceback"] = f"```py\n{tb[:800]}\n```"
        self._enqueue(_raw_embed(logging.ERROR, title, description, fields))

    async def warn(self, title: str, description: str, context: str = "") -> None:
        fields = {"Context": f"```\n{context[:400]}\n```"} if context else {}
        self._enqueue(_raw_embed(logging.WARNING, title, description, fields))

    async def info(self, title: str, description: str, context: str = "") -> None:
        fields = {"Context": f"```\n{context[:400]}\n```"} if context else {}
        self._enqueue(_raw_embed(logging.INFO, title, description, fields))

    async def cmd(
        self,
        ctx_or_interaction: Any,
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
                if ctx_or_interaction.command
                else "!d unknown"
            )

        ctx_str = (
            f"Command : {cmd_str}\n"
            f"Author  : {author} ({author.id})\n"
            f"Guild   : {guild} ({guild.id if guild else 'DM'})"
        )
        if note:
            ctx_str += f"\nNote    : {note}"

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        fields = {
            "Context":   f"```\n{ctx_str}\n```",
            "Traceback": f"```py\n{tb[:800]}\n```",
        }
        self._enqueue(_raw_embed(
            logging.ERROR,
            f"Command Error — `{cmd_str}`",
            str(error),
            fields,
        ))

    async def online(self, guild_count: int, command_count: int) -> None:
        self._enqueue(_raw_embed(
            logging.INFO,
            "🟢  Bot Online",
            (
                f"> Guilds: `{guild_count}`\n"
                f"> Commands synced: `{command_count}`\n"
                f"> Environment: Azure Container Apps"
            ),
        ))

    async def offline(self) -> None:
        self._enqueue(_raw_embed(
            logging.WARNING,
            "🔴  Bot Offline",
            "> Shutting down gracefully.",
        ))

    async def restart(self, triggered_by: str) -> None:
        self._enqueue(_raw_embed(
            logging.WARNING,
            "🔁  Bot Restarting",
            f"> Triggered by **{triggered_by}**\n> Process will restart momentarily.",
        ))

    async def cog_fail(self, cog_name: str, exc: BaseException) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._enqueue(_raw_embed(
            logging.ERROR,
            f"Cog Load Failed — `{cog_name}`",
            str(exc),
            {"Traceback": f"```py\n{tb[:800]}\n```"},
        ))


# ── Typed bot subclass ────────────────────────────────────────────────────────

class DenkiBot(commands.Bot):
    """
    Thin subclass of commands.Bot that declares the `log` attribute so the
    type checker knows it exists. The Logging cog assigns it in __init__.
    """
    log: DiscordLogger


# ── Logging Cog ───────────────────────────────────────────────────────────────

class Logging(commands.Cog):
    """
    Webhook-based Discord log shipping for Denki.

    - Installs a queue handler on the root 'denki' logger immediately
      so no records are lost during startup.
    - Defers webhook creation to on_ready (guild cache populated).
    - Flushes the queue every FLUSH_INTERVAL seconds.
    - All messages are sent @silent (flag 4096) — no pings.
    """

    def __init__(self, bot: DenkiBot) -> None:
        self.bot: DenkiBot = bot

        # Shared queue — both the queue handler (stdlib records) and
        # DiscordLogger (pre-built embed dicts) push onto this.
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=MAX_QUEUE)

        # Attach bot.log (DiscordLogger) — declared on DenkiBot so no ignore needed
        bot.log = DiscordLogger(self._queue)

        self._webhook_url: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._handler = _DiscordQueueHandler(self._queue)
        self._task: Optional[asyncio.Task[None]] = None

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
        # Final drain before unload
        await self._drain()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Handler installation ──────────────────────────────────────────────────

    def _install_handler(self) -> None:
        self._handler.setLevel(logging.INFO)
        # Only ship denki.* loggers — keeps discord.py internals out of the channel
        self._handler.addFilter(
            lambda r: r.name.startswith("denki") and r.levelno >= logging.INFO
        )
        logging.getLogger("denki").addHandler(self._handler)

    def _uninstall_handler(self) -> None:
        logging.getLogger("denki").removeHandler(self._handler)

    # ── Webhook setup ─────────────────────────────────────────────────────────

    async def _ensure_webhook(self) -> bool:
        """
        Find or create the Denki Logs webhook.
        Must only be called from on_ready — guild cache must be populated.
        """
        if self._webhook_url:
            return True

        if not LOG_CHANNEL_ID:
            logger.warning(
                "LOG_CHANNEL_ID not set — Discord log shipping disabled. "
                "Set LOG_CHANNEL_ID env var to enable."
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
                "Logz: channel %d not found — bot may not be in that server "
                "or lacks access. Check LOG_CHANNEL_ID.",
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
                "Logz: missing Manage Webhooks permission in channel %d. "
                "Grant it to the bot and reload the cog.",
                LOG_CHANNEL_ID,
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

        batch: list[dict[str, Any]] = []

        try:
            while True:
                item = self._queue.get_nowait()

                if isinstance(item, tuple) and item[0] == "embed":
                    # Pre-built embed dict from DiscordLogger
                    batch.append(item[1])
                elif isinstance(item, logging.LogRecord):
                    # Raw stdlib record — convert to embed dict
                    batch.append(cast(dict[str, Any], _record_to_embed(item).to_dict()))

                if len(batch) >= 10:
                    await self._ship(batch)
                    batch = []

        except asyncio.QueueEmpty:
            pass

        if batch:
            await self._ship(batch)

    async def _ship(self, embed_dicts: list[dict[str, Any]]) -> None:
        if not self._webhook_url or not self._session or self._session.closed:
            return
        payload = {
            "embeds": embed_dicts,
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
        """
        Earliest point where get_channel() is reliable.
        Set up the webhook then flush anything that queued during startup.
        """
        ok = await self._ensure_webhook()
        if not ok:
            return

        # Startup notice — sent as a DiscordLogger embed
        assert self.bot.user is not None
        guild_count   = len(self.bot.guilds)
        command_count = len(self.bot.tree.get_commands())

        self.bot.log._enqueue(_raw_embed(
            logging.INFO,
            "🟢  Denki Online",
            (
                f"> `{self.bot.user}` · `{guild_count}` guilds\n"
                f"> Commands: `{command_count}`\n"
                f"> Environment: **Azure Container Apps**\n"
                f"> Channel: <#{LOG_CHANNEL_ID}>"
            ),
        ))

        # Flush immediately — don't wait for the 2s loop
        await self._drain()

    # ── Error hooks ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """Forward unhandled prefix errors to the log channel."""
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
        """Forward unhandled slash errors to the log channel."""
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
                        color=0xFF4444,
                    ),
                    ephemeral=True,
                )
        except Exception:
            pass

    # ── Sudo commands ─────────────────────────────────────────────────────────

    @commands.command(name="setlog")
    async def setlog(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the log channel at runtime. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return

        global LOG_CHANNEL_ID
        LOG_CHANNEL_ID = channel.id
        # Reset cached webhook URL so it's re-created in the new channel
        self._webhook_url = None

        ok = await self._ensure_webhook()
        status = "✅ Webhook created" if ok else "❌ Webhook setup failed — check permissions"
        await ctx.reply(embed=discord.Embed(
            description=(
                f"> `✅` *Log channel set to {channel.mention}.*\n"
                f"> {status}\n"
                f"> Add `LOG_CHANNEL_ID={channel.id}` to your env to persist across restarts."
            ),
            color=0x5793F2,
        ))

    @commands.command(name="logtest")
    async def logtest(self, ctx: commands.Context) -> None:
        """Send test records at every level. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return

        if not self._webhook_url:
            await ctx.reply(embed=discord.Embed(
                description=(
                    f"> `❗` *Webhook not initialised.*\n"
                    f"> Set `LOG_CHANNEL_ID` env var or use `!d setlog #channel`."
                ),
                color=0xFF4444,
            ))
            return

        test_logger = logging.getLogger("denki.logtest")
        test_logger.info("logtest INFO — handler is working ✅")
        test_logger.warning("logtest WARNING — test warning ⚠️")
        test_logger.error("logtest ERROR — test error ❌")

        await ctx.reply(embed=discord.Embed(
            description=(
                f"> `✅` *3 test records queued for <#{LOG_CHANNEL_ID}>.*\n"
                f"> INFO · WARNING · ERROR"
            ),
            color=0x5793F2,
        ))

    @commands.command(name="logchannel")
    async def logchannel(self, ctx: commands.Context) -> None:
        """Show the current log channel and webhook status. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return

        if LOG_CHANNEL_ID and self._webhook_url:
            desc = f"> `📋` *Log channel: <#{LOG_CHANNEL_ID}>*\n> Webhook: ✅ active"
        elif LOG_CHANNEL_ID:
            desc = f"> `⚠️` *Channel ID `{LOG_CHANNEL_ID}` set but webhook not initialised.*"
        else:
            desc = "> `❗` *No log channel set. Use `!d setlog #channel`.*"

        await ctx.reply(embed=discord.Embed(description=desc, color=0x5793F2))


async def setup(bot: DenkiBot) -> None:
    await bot.add_cog(Logging(bot))