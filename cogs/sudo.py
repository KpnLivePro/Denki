from __future__ import annotations

import logging
import platform
import re
import sys
import time
from typing import Annotated, Any, cast

import discord
from discord.ext import commands

from postgrest.types import CountMethod

import db
import ui as ui_module
from ui import UI, PaginatorView
from cogs.seasons import run_season_end

logger = logging.getLogger("denki.sudo")

from emojis import E_DB as _DB

_start_time: float = time.time()

# Regex that matches a single emoji token (basic emoji or ZWJ sequences)
_EMOJI_RE = re.compile(
    r"^(?:[\U0001F300-\U0001FAFF]|[\U00002600-\U000027BF]|[\U0001F000-\U0001F9FF]"
    r"|[\u2600-\u27BF]|\u2702|\u2705|[\u2709-\u2764]|\u2795|\u2796|\u2797|\u27A1"
    r"|[\u2934-\u2935]|[\u25AA-\u25FE]|[\u2614-\u26FF]|[\u2702-\u27B0]"
    r"|[\u231A-\u231B]|\u23F0|\u23F3|[\u25FD-\u25FE]|[\u2B50-\u2B55]"
    r"|\u00A9|\u00AE|\u203C|\u2049|\u20E3|[\uFE00-\uFE0F]|\u3030|\u303D"
    r"|\u3297|\u3299)+$"
)


def _looks_like_emoji(token: str) -> bool:
    if token.startswith("#"):
        return False
    if token.isascii():
        return False
    return bool(_EMOJI_RE.match(token))


# ── Converters ────────────────────────────────────────────────────────────────


class UserID(commands.Converter[int]):
    async def convert(self, ctx: commands.Context[Any], argument: str) -> int:
        stripped = argument.strip().lstrip("<@!").rstrip(">")
        try:
            return int(stripped)
        except ValueError:
            raise commands.BadArgument(
                f"`{argument}` is not a valid user ID or mention."
            )


class Amount(commands.Converter[int]):
    """Accepts integers, comma-formatted numbers, decimals, and k/m shorthands."""

    async def convert(self, ctx: commands.Context[Any], argument: str) -> int:
        cleaned = argument.strip().replace(",", "").replace("_", "")
        multiplier = 1
        if cleaned.lower().endswith("k"):
            multiplier = 1_000
            cleaned = cleaned[:-1]
        elif cleaned.lower().endswith("m"):
            multiplier = 1_000_000
            cleaned = cleaned[:-1]
        try:
            value = round(float(cleaned) * multiplier)
            if value == 0:
                raise commands.BadArgument("Amount cannot be zero.")
            return value
        except ValueError:
            raise commands.BadArgument(
                f"`{argument}` is not a valid amount. "
                "Examples: `6000`, `6,000`, `1.5k`, `-500`"
            )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _respond(ctx: commands.Context[Any], embed: discord.Embed) -> None:
    await ctx.reply(embed=embed)


def _fmt_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    return f"{days}d {hours}h {mins}m {secs}s"


# ── Table paginator ───────────────────────────────────────────────────────────


def _build_table_pages(
    table: str, rows: list[Any], rows_per_page: int = 5
) -> list[discord.Embed]:
    if not rows:
        return [Embeds.base(f"> `🗄️` *`{table}` — no rows found*")]
    total_pages = max(1, -(-len(rows) // rows_per_page))
    pages: list[discord.Embed] = []
    for page_num in range(total_pages):
        chunk = rows[page_num * rows_per_page : (page_num + 1) * rows_per_page]
        embed = UI.base(f"> `{_DB}` *Table: `{table}`*")
        for row in chunk:
            items = list(row.items())
            title = f"`{items[0][0]}` = {items[0][1]}"
            body = "\n".join(f"> `{k}` {v}" for k, v in items[1:])
            embed.add_field(name=title, value=body or "> *empty*", inline=False)
        embed.set_footer(
            text=f"Page {page_num + 1} / {total_pages}  ·  {len(rows)} rows total"
        )
        pages.append(embed)
    return pages


class TablePaginatorView(PaginatorView):
    def __init__(self, table: str, rows: list[Any], owner_id: int) -> None:
        self.table = table
        self.msg: discord.Message | None = None
        super().__init__(pages=_build_table_pages(table, rows), owner_id=owner_id)

    async def _rebuild_pages(self) -> list[discord.Embed]:
        try:
            res = db.supabase.table(self.table).select("*").limit(50).execute()
            rows: list[Any] = res.data or []
            return _build_table_pages(self.table, rows)
        except Exception as e:
            return [UI.error(ctx.author, f"Refresh failed: {e}")]

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.msg:
            try:
                await self.msg.edit(view=self)
            except Exception:
                pass


# ── Sudo Cog ──────────────────────────────────────────────────────────────────


class Sudo(commands.Cog):
    """Owner-only prefix commands. All nest under !d."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context[Any]) -> bool:  # type: ignore[override]
        return await self.bot.is_owner(ctx.author)

    # ── Help ──────────────────────────────────────────────────────────────────

    @commands.command(name="sudo")
    async def sudo_help(self, ctx: commands.Context[Any]) -> None:
        embed = UI.base("> `⚡` *Sudo — owner-only commands*")
        embed.add_field(
            name="`👤` User",
            value=(
                "> `!d warn <id> <reason>` — issue a warn\n"
                "> `!d clearwarn <id>` — clear a warn by ID\n"
                "> `!d warns <id>` — view active warns\n"
                "> `!d ban <id> [reason]` — global ban\n"
                "> `!d unban <id>` — remove ban\n"
                "> `!d wallet <id>` — wallet audit\n"
                "> `!d adjust <±amount> <@user|id>` — adjust wallet"
            ),
            inline=False,
        )
        embed.add_field(
            name="`🌸` Season",
            value=(
                "> `!d seasonend` — trigger season end\n"
                "> `!d seasonset <n> [emoji] [#hex]` — rename / set emoji / recolor"
            ),
            inline=False,
        )
        embed.add_field(
            name="`📢` Broadcast",
            value=(
                "> `!d announce <msg>` — send to all servers with a notif channel\n"
                "> `!d reports` — pending reports\n"
                "> `!d dismiss <id>` — dismiss a report"
            ),
            inline=False,
        )
        embed.add_field(
            name="`🤖` Bot",
            value=(
                "> `!d presence <type> <text>` — set activity\n"
                "> `!d status <online|idle|dnd|invisible>` — set status indicator\n"
                "> `!d botstatus <text>` — set custom status note\n"
                "> `!d sys` — system stats\n"
                "> `!d bot restart` — restart the bot"
            ),
            inline=False,
        )
        embed.add_field(
            name="`🧩` Cogs",
            value=(
                "> `!d cogs` — list loaded cogs\n"
                "> `!d cogs reload <name|all>` — reload cog(s)"
            ),
            inline=False,
        )
        embed.add_field(
            name="`🗄️` Data",
            value=(
                "> `!d data` — table row counts\n"
                "> `!d data <table>` — paginated table rows"
            ),
            inline=False,
        )
        embed.add_field(
            name="`📋` Logging",
            value=(
                "> `!d setlog <#channel>` — set the log channel\n"
                "> `!d logchannel` — show current log channel\n"
                "> `!d logtest` — send a test message to the log channel"
            ),
            inline=False,
        )
        embed.set_footer(text="Prefix: !d  ·  Owner only")
        await _respond(ctx, embed)

    # ── Warn ──────────────────────────────────────────────────────────────────

    @commands.command(name="warn")
    async def warn(
        self,
        ctx: commands.Context[Any],
        user_id: Annotated[int, UserID()],
        *,
        reason: str,
    ) -> None:
        await db.get_or_create_user(user_id)
        await db.issue_warn(user_id=user_id, reason=reason, issued_by=ctx.author.id)
        warn_count = await db.count_active_warns(user_id)

        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(embed=UI.warn_dm(reason=reason, warn_count=warn_count))
        except discord.Forbidden:
            pass
        except Exception as e:
            logger.error(f"Error DMing warn to {user_id}: {e}")

        embed = UI.warn_issued(
            user=await self.bot.fetch_user(user_id),
            reason=reason,
            warn_count=warn_count,
        )
        await _respond(ctx, embed)

        if warn_count >= 3:
            await self._execute_ban(
                ctx,
                user_id,
                f"Auto-ban: reached {warn_count} active warnings.",
                silent=True,
            )

    @commands.command(name="clearwarn")
    async def clearwarn(self, ctx: commands.Context[Any], warn_id: int) -> None:
        try:
            await db.clear_warn(warn_id)
            await _respond(ctx, UI.success(ctx.author, f"Warn `{warn_id}` cleared."))
        except Exception:
            await _respond(ctx, UI.error(ctx.author, f"Warn `{warn_id}` not found."))

    @commands.command(name="warns")
    async def warns(
        self, ctx: commands.Context[Any], user_id: Annotated[int, UserID()]
    ) -> None:
        warns_list = await db.get_active_warns(user_id)
        try:
            username = str(await self.bot.fetch_user(user_id))
        except Exception:
            username = f"User {user_id}"

        if not warns_list:
            return await _respond(
                ctx, UI.info(ctx.author, f"**{username}** has no active warns.")
            )

        embed = UI.base(
            f"> `⚠️` *Active warns for **{username}** ({len(warns_list)} / 3)*"
        )
        for w in warns_list:
            embed.add_field(
                name=f"`#{w['warn_id']}` — {w['issued_at'][:10]}",
                value=f"> {w['reason']}\n> Expires: `{w['expires_at'][:10]}`",
                inline=False,
            )
        await _respond(ctx, embed)

    # ── Ban ───────────────────────────────────────────────────────────────────

    @commands.command(name="ban")
    async def ban(
        self,
        ctx: commands.Context[Any],
        user_id: Annotated[int, UserID()],
        *,
        reason: str = "No reason provided.",
    ) -> None:
        await self._execute_ban(ctx, user_id, reason, silent=False)

    async def _execute_ban(
        self, ctx: commands.Context[Any], user_id: int, reason: str, silent: bool
    ) -> None:
        await db.ban_user(user_id=user_id, reason=reason, banned_by=ctx.author.id)
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(embed=UI.ban_dm(reason=reason))
        except discord.Forbidden:
            pass
        except Exception as e:
            logger.error(f"Error DMing ban to {user_id}: {e}")

        if not silent:
            try:
                username = str(await self.bot.fetch_user(user_id))
            except Exception:
                username = f"User {user_id}"
            await _respond(
                ctx,
                UI.success(
                    ctx.author,
                    f"**{username}** has been globally banned from Denki.\n> Reason: `{reason}`",
                ),
            )

    @commands.command(name="unban")
    async def unban(
        self, ctx: commands.Context[Any], user_id: Annotated[int, UserID()]
    ) -> None:
        ban = await db.get_ban(user_id)
        if not ban:
            return await _respond(
                ctx, UI.error(ctx.author, f"User `{user_id}` is not currently banned.")
            )
        await db.unban_user(user_id)
        try:
            username = str(await self.bot.fetch_user(user_id))
        except Exception:
            username = f"User {user_id}"
        await _respond(
            ctx, UI.success(ctx.author, f"**{username}** has been unbanned from Denki.")
        )

    # ── Wallet ────────────────────────────────────────────────────────────────

    @commands.command(name="wallet")
    async def wallet(
        self, ctx: commands.Context[Any], user_id: Annotated[int, UserID()]
    ) -> None:
        user_data = await db.get_user(user_id)
        if not user_data:
            return await _respond(
                ctx, UI.error(ctx.author, f"User `{user_id}` has no wallet record.")
            )
        try:
            username = str(await self.bot.fetch_user(user_id))
        except Exception:
            username = f"User {user_id}"

        warn_count = await db.count_active_warns(user_id)
        ban = await db.get_ban(user_id)

        embed = UI.base(f"> `🔍` *Wallet audit — **{username}***")
        embed.add_field(
            name="`💴` Global wallet",
            value=f"```¥{int(user_data['wallet']):,}```",
            inline=True,
        )
        embed.add_field(name="`🆔` User ID", value=f"```{user_id}```", inline=True)
        embed.add_field(
            name="`⚠️` Active warns", value=f"```{warn_count} / 3```", inline=True
        )
        embed.add_field(
            name="`🔨` Ban status",
            value=f"```{'Banned — ' + str(ban['reason']) if ban else 'Not banned'}```",
            inline=False,
        )
        await _respond(ctx, embed)

    @commands.command(name="adjust")
    async def adjust(
        self,
        ctx: commands.Context[Any],
        amount: Annotated[int, Amount()],
        user_id: Annotated[int, UserID()],
    ) -> None:
        await db.get_or_create_user(user_id)
        try:
            wallet_data = await db.update_wallet(user_id, amount)
        except ValueError as e:
            return await _respond(ctx, UI.error(ctx.author, str(e)))
        await db.log_transaction(ctx.author.id, user_id, abs(amount), "admin_adjust")
        try:
            username = str(await self.bot.fetch_user(user_id))
        except Exception:
            username = f"User {user_id}"
        direction = "added to" if amount > 0 else "removed from"
        await _respond(
            ctx,
            Embeds.success(
                f"¥{abs(amount):,} {direction} **{username}**'s wallet.\n"
                f"> New balance: `¥{int(wallet_data['wallet']):,}`"
            ),
        )

    # ── Season ────────────────────────────────────────────────────────────────

    @commands.command(name="seasonend")
    async def seasonend(self, ctx: commands.Context[Any]) -> None:
        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx, Embeds.error("There is no active season to end.")
            )

        view = ConfirmView(ctx.author.id)
        await ctx.reply(
            embed=Embeds.warn_msg(
                f"Are you sure you want to end **{season['name']}** early?\n"
                "> This will trigger full season end logic including payouts and reset."
            ),
            view=view,
        )
        await view.wait()
        if view.confirmed:
            await run_season_end(self.bot, season)
            await ctx.reply(
                embed=Embeds.success("Season end logic completed successfully.")
            )
        else:
            await ctx.reply(embed=Embeds.info("Season end cancelled."))

    @commands.command(name="seasonset")
    async def seasonset(self, ctx: commands.Context[Any], *, args: str) -> None:
        """
        Set the active season name, optional emoji, and optional theme color.

        Usage:
            !d seasonset Winter Arc
            !d seasonset Winter Arc ❄️
            !d seasonset Winter Arc #F2C84B
            !d seasonset Winter Arc ❄️ #F2C84B
        """
        season = await db.get_active_season()
        if not season:
            return await _respond(ctx, Embeds.error("There is no active season."))

        parts = args.strip().split()
        if not parts:
            return await _respond(ctx, Embeds.error("Provide a season name."))

        color: str | None = None
        last = parts[-1].lstrip("#")
        if len(last) == 6:
            try:
                int(last, 16)
                color = f"#{last.upper()}"
                parts = parts[:-1]
            except ValueError:
                pass

        if not parts:
            return await _respond(
                ctx, Embeds.error("Provide a season name before the color.")
            )

        emoji: str | None = None
        if _looks_like_emoji(parts[-1]):
            emoji = parts[-1]
            parts = parts[:-1]

        if not parts:
            return await _respond(ctx, Embeds.error("Provide a season name."))

        name = " ".join(parts)

        updates: dict[str, Any] = {"name": name}
        if color:
            updates["theme"] = color
        if emoji:
            updates["emoji"] = emoji

        await db.update_season(int(season["season_id"]), updates)

        if color:
            embeds_module.set_color(color)

        parts_msg = [f"Name: `{name}`"]
        if emoji:
            parts_msg.append(f"Emoji: `{emoji}`")
        if color:
            parts_msg.append(f"Color: `{color}`")

        await _respond(
            ctx,
            Embeds.success(
                "Season updated.\n" + "\n".join(f"> {p}" for p in parts_msg)
            ),
        )

    # ── Announce / Reports ────────────────────────────────────────────────────

    @commands.command(name="announce")
    async def announce(self, ctx: commands.Context[Any], *, message: str) -> None:
        """Broadcast to all servers that have a notification channel configured."""
        try:
            result = (
                db.supabase.table("guildconfig")
                .select("guild_id, notif_channel, notif_role")
                .not_.is_("notif_channel", "null")
                .execute()
            )
            configs = result.data or []
        except Exception as e:
            return await _respond(
                ctx, Embeds.error(f"Failed to fetch guild configs: {e}")
            )

        if not configs:
            return await _respond(
                ctx, Embeds.error("No servers have a notification channel configured.")
            )

        sent = 0
        failed = 0
        skipped = 0

        for raw_config in configs:
            config = cast(dict[str, Any], raw_config)
            notif_channel = config.get("notif_channel")
            notif_role = config.get("notif_role")
            if not notif_channel:
                skipped += 1
                continue
            channel = self.bot.get_channel(int(notif_channel))
            if not channel or not isinstance(channel, discord.TextChannel):
                skipped += 1
                continue
            mention = f"<@&{notif_role}> " if notif_role else ""
            try:
                await channel.send(
                    content=mention or None,
                    embed=Embeds.base(f"> `📢` *{message}*"),
                )
                sent += 1
            except discord.Forbidden:
                failed += 1
            except Exception:
                failed += 1

        await _respond(
            ctx,
            Embeds.success(
                f"Announcement sent.\n"
                f"> ✅ Delivered: `{sent}`\n"
                f"> ⚠️ No permission: `{failed}`\n"
                f"> ⏭️ Channel not cached: `{skipped}`"
            ),
        )

    @commands.command(name="reports")
    async def reports(self, ctx: commands.Context[Any]) -> None:
        pending = await db.get_reports(status="pending")
        if not pending:
            return await _respond(ctx, Embeds.info("No pending reports."))
        embed = Embeds.base(f"> `📋` *Pending reports ({len(pending)})*")
        for r in pending[:10]:
            embed.add_field(
                name=f"`#{r['report_id']}` — <@{r['reported_id']}>",
                value=(
                    f"> Reporter: <@{r['reporter_id']}>\n"
                    f"> Server: `{r['guild_id']}`\n"
                    f"> Reason: {r['reason']}\n"
                    f"> Wallet snap: `¥{int(r['wallet_snap']):,}`"
                ),
                inline=False,
            )
        if len(pending) > 10:
            embed.set_footer(text=f"Showing 10 of {len(pending)}")
        await _respond(ctx, embed)

    @commands.command(name="dismiss")
    async def dismiss(self, ctx: commands.Context[Any], report_id: int) -> None:
        await db.update_report_status(report_id, "dismissed")
        await _respond(ctx, Embeds.success(f"Report `{report_id}` dismissed."))

    # ── Bot presence & status ─────────────────────────────────────────────────

    @commands.command(name="presence")
    async def presence(
        self, ctx: commands.Context[Any], activity_type: str, *, text: str = ""
    ) -> None:
        activity_type = activity_type.lower()
        if activity_type == "clear":
            await self.bot.change_presence(activity=None)
            return await _respond(ctx, Embeds.success("Activity cleared."))

        type_map: dict[str, discord.ActivityType] = {
            "watching": discord.ActivityType.watching,
            "playing": discord.ActivityType.playing,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
            "streaming": discord.ActivityType.streaming,
        }
        if activity_type not in type_map:
            valid = ", ".join(f"`{k}`" for k in type_map)
            return await _respond(
                ctx, Embeds.error(f"Invalid type. Choose: {valid}, `clear`")
            )
        if not text:
            return await _respond(
                ctx, Embeds.error("Provide text after the activity type.")
            )

        if activity_type == "streaming":
            activity: discord.BaseActivity = discord.Streaming(
                name=text, url="https://twitch.tv/denki"
            )
        else:
            activity = discord.Activity(type=type_map[activity_type], name=text)

        await self.bot.change_presence(activity=activity)
        await _respond(
            ctx, Embeds.success(f"Activity set to **{activity_type}** `{text}`.")
        )

    @commands.command(name="status")
    async def status(self, ctx: commands.Context[Any], status_val: str) -> None:
        status_map: dict[str, discord.Status] = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
        }
        if status_val.lower() not in status_map:
            valid = ", ".join(f"`{k}`" for k in status_map)
            return await _respond(ctx, Embeds.error(f"Invalid status. Choose: {valid}"))
        await self.bot.change_presence(status=status_map[status_val.lower()])
        await _respond(
            ctx, Embeds.success(f"Status indicator set to `{status_val.lower()}`.")
        )

    @commands.command(name="botstatus")
    async def botstatus(self, ctx: commands.Context[Any], *, text: str) -> None:
        if text.lower() == "clear":
            await self.bot.change_presence(activity=discord.CustomActivity(name=""))
            return await _respond(ctx, Embeds.success("Custom status cleared."))
        await self.bot.change_presence(activity=discord.CustomActivity(name=text))
        await _respond(ctx, Embeds.success(f"Custom status set to `{text}`."))

    # ── System stats ──────────────────────────────────────────────────────────

    @commands.command(name="sys")
    async def sys_stats(self, ctx: commands.Context[Any]) -> None:
        uptime_str = _fmt_uptime(int(time.time() - _start_time))
        latency_ms = round(self.bot.latency * 1000, 2)
        total_guilds = len(self.bot.guilds)
        total_users = sum(g.member_count or 0 for g in self.bot.guilds)

        try:
            import resource

            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            mem_str = f"{mem_mb:.1f} MB"
        except Exception:
            mem_str = "N/A"

        try:
            import psutil

            cpu_str = f"{psutil.cpu_percent(interval=0.1):.1f}%"
        except (ImportError, Exception):
            cpu_str = "N/A"

        embed = Embeds.base("> `📊` *System Stats*")
        embed.add_field(name="`⏱️` Uptime", value=f"```{uptime_str}```", inline=True)
        embed.add_field(name="`📡` Latency", value=f"```{latency_ms}ms```", inline=True)
        embed.add_field(name="`🧠` Memory", value=f"```{mem_str}```", inline=True)
        embed.add_field(name="`⚙️` CPU", value=f"```{cpu_str}```", inline=True)
        embed.add_field(name="`🏠` Guilds", value=f"```{total_guilds}```", inline=True)
        embed.add_field(name="`👥` Users", value=f"```{total_users:,}```", inline=True)
        embed.add_field(
            name="`🐍` Python", value=f"```{sys.version[:6]}```", inline=True
        )
        embed.add_field(
            name="`📦` discord.py", value=f"```{discord.__version__}```", inline=True
        )
        embed.add_field(name="`🖥️` OS", value=f"```{platform.system()}```", inline=True)
        await _respond(ctx, embed)

    # ── Bot control ───────────────────────────────────────────────────────────

    @commands.group(name="bot", invoke_without_command=True)
    async def botctl(self, ctx: commands.Context[Any]) -> None:
        await _respond(ctx, Embeds.info("Usage: `!d bot restart`"))

    @botctl.command(name="restart")
    async def botctl_restart(self, ctx: commands.Context[Any]) -> None:
        view = ConfirmView(ctx.author.id)
        await ctx.reply(
            embed=Embeds.warn_msg(
                "Restart the bot? The bot will be offline for a few seconds."
            ),
            view=view,
        )
        await view.wait()
        if not view.confirmed:
            await ctx.reply(embed=Embeds.info("Restart cancelled."))
            return
        await ctx.reply(embed=Embeds.success("Restarting..."))

        # Notify log channel before process is replaced
        if hasattr(self.bot, "log"):
            await self.bot.log.restart(str(ctx.author))  # type: ignore[attr-defined]

        import os

        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── Cog management ────────────────────────────────────────────────────────

    @commands.group(name="cogs", invoke_without_command=True)
    async def cogs_group(self, ctx: commands.Context[Any]) -> None:
        loaded = sorted(self.bot.extensions.keys())
        lines = "\n".join(f"> ✅ `{ext}`" for ext in loaded)
        embed = Embeds.base(f"> `🧩` *Loaded cogs ({len(loaded)})*\n\n{lines}")
        await _respond(ctx, embed)

    @cogs_group.command(name="reload")
    async def cogs_reload(self, ctx: commands.Context[Any], cog: str = "all") -> None:
        from main import COGS

        if cog.lower() == "all":
            results: list[str] = []
            for ext in COGS:
                try:
                    await self.bot.reload_extension(ext)
                    results.append(f"> ✅ `{ext}`")
                except Exception as e:
                    results.append(f"> ❌ `{ext}` — {e}")
            await _respond(
                ctx, Embeds.base("> `🔄` *Reloaded all cogs*\n\n" + "\n".join(results))
            )
        else:
            ext = cog if "." in cog else f"cogs.{cog}"
            try:
                await self.bot.reload_extension(ext)
                await _respond(ctx, Embeds.success(f"Reloaded `{ext}`."))
            except commands.ExtensionNotLoaded:
                await _respond(ctx, Embeds.error(f"`{ext}` is not loaded."))
            except commands.ExtensionNotFound:
                await _respond(ctx, Embeds.error(f"`{ext}` not found."))
            except Exception as e:
                await _respond(
                    ctx, Embeds.error(f"Failed to reload `{ext}`:\n```{e}```")
                )

    # ── Data / DB health ──────────────────────────────────────────────────────

    @commands.command(name="data")
    async def data_cmd(
        self, ctx: commands.Context[Any], table: str | None = None
    ) -> None:
        valid_tables = [
            "users",
            "banks",
            "guilds",
            "guildconfig",
            "seasons",
            "cooldowns",
            "transactions",
            "shopitems",
            "inventory",
            "reports",
            "warns",
            "bans",
            "cashback",
        ]

        # No table arg — show row counts for all tables
        if table is None:
            results: list[tuple[str, str]] = []
            errors: list[str] = []
            for t in valid_tables:
                try:
                    res = (
                        db.supabase.table(t)
                        .select("*", count=CountMethod.exact)
                        .limit(0)
                        .execute()
                    )
                    count = res.count if res.count is not None else "?"
                    results.append((t, str(count)))
                except Exception as e:
                    errors.append(t)
                    results.append((t, f"ERR — {str(e)[:30]}"))
            lines2 = "\n".join(
                f"> {'❌' if t in errors else '✅'} `{t:<14}` {c} rows"
                for t, c in results
            )
            status = (
                "All tables reachable."
                if not errors
                else f"{len(errors)} table(s) errored."
            )
            embed = Embeds.base(f"> `🗄️` *DB Health — {status}*\n\n{lines2}")
            embed.set_footer(
                text=f"{len(valid_tables)} tables checked  ·  use `!d data <table>` to inspect rows"
            )
            return await _respond(ctx, embed)

        # Table name provided — show paginated rows
        if table not in valid_tables:
            valid = ", ".join(f"`{t}`" for t in valid_tables)
            return await _respond(ctx, Embeds.error(f"Unknown table. Valid: {valid}"))

        try:
            res = db.supabase.table(table).select("*").limit(50).execute()
            rows: list[Any] = res.data or []
        except Exception as e:
            return await _respond(ctx, Embeds.error(f"Query failed: {e}"))

        pages = _build_table_pages(table, rows)
        view = TablePaginatorView(table=table, rows=rows, owner_id=ctx.author.id)
        view.msg = await ctx.reply(embed=pages[0], view=view)


# ── Confirm View ──────────────────────────────────────────────────────────────


class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="✓", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        await interaction.response.edit_message(
            embed=Embeds.info("Confirmed — processing..."), view=None
        )
        self.stop()

    @discord.ui.button(label="✕", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = False
        await interaction.response.edit_message(
            embed=Embeds.info("Cancelled."), view=None
        )
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sudo(bot))
