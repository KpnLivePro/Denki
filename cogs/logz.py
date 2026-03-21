from __future__ import annotations

"""
cogs/logz.py

Central Discord channel logger for Denki.
Attaches to bot.log — call from anywhere:

    await bot.log.error("Title", "description", context="optional")
    await bot.log.info("Title", "description")
    await bot.log.warn("Title", "description")
    await bot.log.cmd(ctx_or_interaction, "optional extra info")

The log channel ID is read from the LOG_CHANNEL_ID env var, and can also
be set at runtime with  !d setlog <#channel>  (owner only).
"""

import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("denki.logging")

# Colour palette for log embeds
_COLOURS = {
    "error": 0xFF4444,   # red
    "warn":  0xFEE75C,   # yellow
    "info":  0x57F287,   # green
    "cmd":   0x5865F2,   # blurple
    "debug": 0x99AAB5,   # grey
}

_MAX_FIELD = 1000   # Discord field value limit is 1024 — stay safe


def _truncate(text: str, limit: int = _MAX_FIELD) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class DiscordLogger:
    """
    Thin wrapper around a Discord TextChannel that formats and sends log embeds.
    Attached to the bot as bot.log after the cog loads.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot        = bot
        self.channel_id = int(os.environ.get("LOG_CHANNEL_ID", "0"))

    def set_channel(self, channel_id: int) -> None:
        self.channel_id = channel_id

    def _channel(self) -> discord.TextChannel | None:
        if not self.channel_id:
            return None
        ch = self.bot.get_channel(self.channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    def _build(
        self,
        level: str,
        title: str,
        description: str,
        context: str = "",
        fields: dict[str, str] | None = None,
    ) -> discord.Embed:
        color = _COLOURS.get(level, _COLOURS["debug"])
        embed = discord.Embed(
            title=title,
            description=_truncate(description),
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if context:
            embed.add_field(name="Context", value=f"```\n{_truncate(context, 512)}\n```", inline=False)
        for name, value in (fields or {}).items():
            embed.add_field(name=name, value=_truncate(value, 512), inline=False)
        return embed

    async def _send(self, embed: discord.Embed) -> None:
        ch = self._channel()
        if not ch:
            return
        try:
            await ch.send(embed=embed)
        except Exception as e:
            logger.warning("DiscordLogger._send failed: %s", e)

    # ── Public API ────────────────────────────────────────────────────────────

    async def error(
        self,
        title: str,
        description: str,
        context: str = "",
        exc: BaseException | None = None,
    ) -> None:
        """Send a red error embed. Optionally attach a traceback."""
        fields: dict[str, str] = {}
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            fields["Traceback"] = f"```py\n{_truncate(tb, 900)}\n```"
        embed = self._build("error", f"❌  {title}", description, context, fields)
        await self._send(embed)

    async def warn(self, title: str, description: str, context: str = "") -> None:
        """Send a yellow warning embed."""
        embed = self._build("warn", f"⚠️  {title}", description, context)
        await self._send(embed)

    async def info(self, title: str, description: str, context: str = "") -> None:
        """Send a green info embed."""
        embed = self._build("info", f"ℹ️  {title}", description, context)
        await self._send(embed)

    async def cmd(
        self,
        ctx_or_interaction: Any,
        error: BaseException,
        note: str = "",
    ) -> None:
        """
        Log a command error — extracts author, guild, command name automatically.
        Pass the raw exception so the traceback is always included.
        """
        is_slash = isinstance(ctx_or_interaction, discord.Interaction)

        if is_slash:
            author  = ctx_or_interaction.user
            guild   = ctx_or_interaction.guild
            cmd     = ctx_or_interaction.command
            cmd_str = f"/{cmd.name}" if cmd else "/unknown"
        else:
            author  = ctx_or_interaction.author
            guild   = ctx_or_interaction.guild
            cmd_str = f"!d {ctx_or_interaction.command}" if ctx_or_interaction.command else "!d unknown"

        ctx_str = (
            f"Command : {cmd_str}\n"
            f"Author  : {author} ({author.id})\n"
            f"Guild   : {guild} ({guild.id if guild else 'DM'})"
        )
        if note:
            ctx_str += f"\nNote    : {note}"

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        fields = {"Traceback": f"```py\n{_truncate(tb, 900)}\n```"}
        embed  = self._build(
            "error",
            f"❌  Command Error — `{cmd_str}`",
            str(error),
            ctx_str,
            fields,
        )
        await self._send(embed)

    async def online(self, guild_count: int, command_count: int) -> None:
        """Bot ready notification."""
        embed = self._build(
            "info",
            "🟢  Bot Online",
            f"> Guilds: `{guild_count}`  ·  Commands synced: `{command_count}`",
        )
        await self._send(embed)

    async def offline(self) -> None:
        """Bot shutdown notification."""
        embed = self._build("warn", "🔴  Bot Offline", "> Shutting down.")
        await self._send(embed)

    async def restart(self, triggered_by: str) -> None:
        """Bot restart notification."""
        embed = self._build(
            "warn",
            "🔁  Bot Restarting",
            f"> Triggered by **{triggered_by}**\n> Process will restart momentarily.",
        )
        await self._send(embed)

    async def cog_fail(self, cog_name: str, exc: BaseException) -> None:
        """Cog load failure notification."""
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        fields = {"Traceback": f"```py\n{_truncate(tb, 900)}\n```"}
        embed  = self._build(
            "error",
            f"❌  Cog Load Failed — `{cog_name}`",
            str(exc),
            fields=fields,
        )
        await self._send(embed)


class Logging(commands.Cog):
    """Attaches DiscordLogger to bot.log and provides !d setlog / !d logtest."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot     = bot
        bot.log      = DiscordLogger(bot)  # type: ignore[attr-defined]

    # ── App-level error hooks ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context[Any], error: commands.CommandError) -> None:
        """
        Forward unhandled prefix command errors to the log channel.
        Skips errors that are handled gracefully (NotFound, checks, bad args).
        """
        # These are handled in main.py's on_command_error — don't double-log
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

        # Unwrap CommandInvokeError to get the real exception
        real = getattr(error, "original", error)
        await self.bot.log.cmd(ctx, real)  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Forward unhandled slash command errors to the log channel."""
        ignored = (discord.app_commands.MissingPermissions, discord.app_commands.CheckFailure)
        if isinstance(error, ignored):
            return

        real = getattr(error, "original", error)
        await self.bot.log.cmd(interaction, real)  # type: ignore[attr-defined]

        # Also respond to the user if the interaction hasn't been responded to
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
    async def setlog(self, ctx: commands.Context[Any], channel: discord.TextChannel) -> None:
        """Set the log channel. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return
        self.bot.log.set_channel(channel.id)  # type: ignore[attr-defined]
        await ctx.reply(embed=discord.Embed(
            description=f"> `✅` *Log channel set to {channel.mention}.*\n"
                        f"> Channel ID: `{channel.id}` — add `LOG_CHANNEL_ID={channel.id}` to your env to persist.",
            color=0x57F287,
        ))

    @commands.command(name="logtest")
    async def logtest(self, ctx: commands.Context[Any]) -> None:
        """Send a test message to the log channel. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return

        log: DiscordLogger = self.bot.log  # type: ignore[attr-defined]
        ch = log._channel()

        if not ch:
            await ctx.reply(embed=discord.Embed(
                description=(
                    "> `❗` *No log channel set.*\n"
                    "> Use `!d setlog #channel` to set one, or add `LOG_CHANNEL_ID=<id>` to your env."
                ),
                color=0xFF4444,
            ))
            return

        await log.info(
            "Log Test",
            f"> Test triggered by **{ctx.author}** (`{ctx.author.id}`)\n"
            f"> Log channel is working correctly.",
        )
        await ctx.reply(embed=discord.Embed(
            description=f"> `✅` *Test message sent to {ch.mention}.*",
            color=0x57F287,
        ))

    @commands.command(name="logchannel")
    async def logchannel(self, ctx: commands.Context[Any]) -> None:
        """Show the current log channel. Owner only."""
        if not await self.bot.is_owner(ctx.author):
            return

        log: DiscordLogger = self.bot.log  # type: ignore[attr-defined]
        ch = log._channel()

        if ch:
            desc = f"> `📋` *Log channel: {ch.mention} (`{ch.id}`)*"
        elif log.channel_id:
            desc = f"> `⚠️` *Log channel ID `{log.channel_id}` is set but the channel isn't cached. Is the bot in that server?*"
        else:
            desc = "> `❗` *No log channel set. Use `!d setlog #channel`.*"

        await ctx.reply(embed=discord.Embed(description=desc, color=0x5865F2))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logging(bot))