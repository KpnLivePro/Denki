"""
ui.py — Denki
Unified UI layer: embed factory, views, modals, pagination, and input converters.

Design rules
────────────
• Every embed description opens with:
      > `{emoji}` *{title}*
  followed by a blank line and content. No exceptions.
• Fields always come in multiples of 3 (Discord's grid is 3 columns).
  Pad with zero-width space fields when needed.
• Monetary values always render as  ¥{n:,}  inside code blocks.
• Outcome language lives in the embed, not the caller — callers pass data only.
• All views/modals live here; cogs never subclass discord.ui directly.
"""
from __future__ import annotations

import math
import traceback
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

import discord
from discord.ext import commands as _commands

import db
from emojis import (
    E_ALIAS, E_ANNOUNCE, E_BANNED, E_BANK, E_BELL, E_BOT, E_BOOK, E_BUY,
    E_CALENDAR, E_CARDS, E_CLOSE, E_COIN, E_CONFIRM, E_COOLDOWN, E_CRITICAL,
    E_CPU, E_DAILY, E_DB, E_DICE, E_DONE, E_ENDS, E_ERROR, E_EXAMPLE,
    E_EXPLOSION, E_GEAR, E_GLOBAL, E_GUILD, E_INFO, E_INVEST, E_INVENTORY,
    E_ITEM, E_MATH, E_MEDAL_1, E_MEDAL_2, E_MEDAL_3, E_MEMORY, E_NEXT,
    E_NOTE, E_OFFLINE, E_ONLINE, E_PAY, E_PING, E_POT, E_PREV, E_PYTHON,
    E_REACTION, E_REFRESH, E_REPORT, E_RESTART, E_ROB, E_ROLE_ITEM,
    E_RPS, E_SEASON, E_SEASON_END, E_SHOP, E_SKULL, E_SKIP, E_SLOTS, E_START,
    E_STATS, E_STREAK, E_SUCCESS, E_TIER_DOWN, E_TIER_UP, E_TROPHY,
    E_USAGE, E_USER, E_VAULT, E_VOTE, E_WARN, E_WALLET, E_WORK, E_YEN,
    E_TEA_AI, E_CANCEL, E_BOMB, E_EXPLOSION as _EXP,
    MEDALS, RPS_EMOJI, TIER_EMOJI,
)

if TYPE_CHECKING:
    from cogs.arcade import ArcadeChallenge, TicTacToeView

# ── Color cache ───────────────────────────────────────────────────────────────

import logging as _logging
_log = _logging.getLogger("denki.ui")

DEFAULT_COLOR  = 0xCD7F32
_cached_color: int = DEFAULT_COLOR


async def refresh_season_color() -> None:
    global _cached_color
    try:
        season = await db.get_active_season()
        if season and season.get("theme"):
            _cached_color = int(str(season["theme"]).strip().lstrip("#"), 16)
        else:
            _cached_color = DEFAULT_COLOR
    except Exception as exc:
        _log.warning("refresh_season_color failed: %s", exc)
        _cached_color = DEFAULT_COLOR


def get_color() -> int:
    return _cached_color


def set_color(hex_str: str) -> None:
    global _cached_color
    try:
        _cached_color = int(hex_str.strip().lstrip("#"), 16)
    except ValueError:
        _cached_color = DEFAULT_COLOR


# ── Zero-width pad field ──────────────────────────────────────────────────────

_ZW = "\u200b"


def _pad(embed: discord.Embed, n: int = 1) -> None:
    """Add n invisible pad fields to keep the 3-column grid aligned."""
    for _ in range(n):
        embed.add_field(name=_ZW, value=_ZW, inline=True)


# ── Streak helpers ────────────────────────────────────────────────────────────

def _streak_label(streak: int) -> str:
    if streak >= 30: return f"{E_STREAK} **30-day streak!**  `2x bonus`"
    if streak >= 14: return f"{E_STREAK} **14-day streak!**  `1.5x bonus`"
    if streak >= 7:  return f"{E_STREAK} **7-day streak!**   `1.25x bonus`"
    if streak >= 3:  return f"{E_STREAK} **3-day streak!**   `1.1x bonus`"
    return ""


def _next_milestone(streak: int) -> str:
    if streak < 3:  return f"`{3  - streak}` more for **1.1x**"
    if streak < 7:  return f"`{7  - streak}` more for **1.25x**"
    if streak < 14: return f"`{14 - streak}` more for **1.5x**"
    if streak < 30: return f"`{30 - streak}` more for **2x**"
    return "Max streak bonus! 🎉"

# EMBED FACTORY

class UI:
    """
    Central embed factory for Denki.
    All methods are static — call as UI.balance(...) etc.
    Cogs import UI instead of the old Embeds class.
    """

    # ── Base / feedback ───────────────────────────────────────────────────────

    @staticmethod
    def base(description: str, footer: Optional[str] = None) -> discord.Embed:
        e = discord.Embed(description=description, color=get_color())
        if footer:
            e.set_footer(text=footer)
        return e

    @staticmethod
    def error(message: str) -> discord.Embed:
        return discord.Embed(
            description=f"> `{E_ERROR}` *{message}*",
            color=get_color(),
        )

    @staticmethod
    def success(message: str) -> discord.Embed:
        return discord.Embed(
            description=f"> `{E_SUCCESS}` *{message}*",
            color=get_color(),
        )

    @staticmethod
    def info(message: str) -> discord.Embed:
        return discord.Embed(
            description=f"> `{E_INFO}` *{message}*",
            color=get_color(),
        )

    @staticmethod
    def warn_msg(message: str) -> discord.Embed:
        return discord.Embed(
            description=f"> `{E_WARN}` *{message}*",
            color=get_color(),
        )

    @staticmethod
    def critical(error: BaseException | str) -> discord.Embed:
        tb = (
            "".join(traceback.format_exception(type(error), error, error.__traceback__))
            if isinstance(error, BaseException)
            else str(error)
        )
        return discord.Embed(
            description=f"> `{E_CRITICAL}` *Critical error:*\n```\n{tb[:1800]}\n```",
            color=get_color(),
        )

    # ── Economy ───────────────────────────────────────────────────────────────

    @staticmethod
    def balance(
        user: discord.User | discord.Member,
        wallet: int,
        bank_balance: int,
        bank_invested: int,
        season_name: str,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_USER}` *{user.display_name}'s balance*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name=f"`{E_WALLET}` Pocket",      value=f"```¥{wallet:,}```",        inline=True)
        e.add_field(name=f"`{E_BANK}` Server bank",   value=f"```¥{bank_balance:,}```",  inline=True)
        e.add_field(name=f"`{E_INVEST}` Invested",    value=f"```¥{bank_invested:,}```", inline=True)
        e.set_footer(text=f"Season: {season_name}")
        return e

    @staticmethod
    def daily(
        user: discord.User | discord.Member,
        amount: int,
        wallet: int,
        tier: int = 1,
    ) -> discord.Embed:
        tier_note = f"  ·  Tier {tier} bonus applied" if tier > 1 else ""
        e = discord.Embed(
            description=f"> `{E_DAILY}` *Daily reward claimed!{tier_note}*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name=f"`{E_YEN}` Earned",       value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        _pad(e)
        return e

    @staticmethod
    def work(
        user: discord.User | discord.Member,
        job: str,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_WORK}` *You worked as a **{job}**!*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name=f"`{E_YEN}` Earned",        value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        _pad(e)
        return e

    @staticmethod
    def rob_success(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        stolen: int,
    ) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_ROB}` *{robber.display_name} robbed {victim.display_name}!*\n"
                f"> Snatched `¥{stolen:,}` from their pocket."
            ),
            color=get_color(),
        )

    @staticmethod
    def rob_fail(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        fine: int,
    ) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_ROB}` *{robber.display_name} got caught trying to rob {victim.display_name}!*\n"
                f"> Paid a fine of `¥{fine:,}`."
            ),
            color=get_color(),
        )

    @staticmethod
    def pay(
        sender: discord.User | discord.Member,
        receiver: discord.User | discord.Member,
        amount: int,
    ) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_PAY}` *Payment sent!*\n\n"
                f"> {sender.mention} → {receiver.mention}  ·  `¥{amount:,}`"
            ),
            color=get_color(),
        )

    @staticmethod
    def cooldown(command: str, remaining: str) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_COOLDOWN}` *`/{command}` is on cooldown.*\n"
                f"> Try again in `{remaining}`."
            ),
            color=get_color(),
        )

    # ── Vote ──────────────────────────────────────────────────────────────────

    @staticmethod
    def vote_prompt(vote_url: str, current_streak: int = 0) -> discord.Embed:
        streak_line = (
            f"> {E_STREAK} Streak: `{current_streak}` day(s)  ·  {_next_milestone(current_streak)}\n"
            if current_streak > 0 else ""
        )
        return discord.Embed(
            description=(
                f"> `{E_VOTE}` *You haven't voted yet!*\n\n"
                f"> [**Vote for Denki on top.gg**]({vote_url})\n"
                f"> Then run `/vote` again to claim your reward.\n\n"
                f"{streak_line}"
                f"> Base `¥2,000`  ·  Weekend `¥4,000`  ·  Streak bonuses apply\n"
                f"> Cooldown: **12 hours**"
            ),
            color=get_color(),
        )

    @staticmethod
    def vote_cooldown(remaining: str, vote_url: str) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_COOLDOWN}` *Vote reward already claimed.*\n\n"
                f"> Next claim in `{remaining}`\n"
                f"> [Vote early]({vote_url}) — reward waits until cooldown expires."
            ),
            color=get_color(),
        )

    @staticmethod
    def vote_reward(
        user: discord.User | discord.Member,
        amount: int,
        wallet: int,
        streak: int,
        is_weekend: bool,
    ) -> discord.Embed:
        weekend = "  ·  `2x weekend!` 🎉" if is_weekend else ""
        milestone = _streak_label(streak)
        desc = f"> `{E_VOTE}` *Thanks for voting!{weekend}*"
        if milestone:
            desc += f"\n> {milestone}"

        e = discord.Embed(description=desc, color=get_color())
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name=f"`{E_YEN}` Reward",        value=f"```¥{amount:,}```",     inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```",     inline=True)
        e.add_field(name=f"`{E_STREAK}` Streak",      value=f"```{streak} day(s)```", inline=True)
        e.set_footer(text=f"{_next_milestone(streak)}  ·  Vote again in 12h")
        return e

    # ── Gambling ──────────────────────────────────────────────────────────────

    @staticmethod
    def coinflip(
        choice: str,
        result: str,
        won: bool,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"`{E_SUCCESS}` *You won!*" if won else f"`{E_ERROR}` *You lost!*"
        e = discord.Embed(
            description=f"> `{E_COIN}` *Coinflip — {outcome}*",
            color=get_color(),
        )
        e.add_field(name="`🎯` Your call",          value=f"```{choice}```",    inline=True)
        e.add_field(name=f"`{E_COIN}` Result",       value=f"```{result}```",    inline=True)
        e.add_field(name=f"`{E_YEN}` Bet",           value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        _pad(e, 2)
        return e

    @staticmethod
    def slots(
        reels: list[str],
        won: bool,
        multiplier: float,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"`{E_SUCCESS}` *You won `¥{payout:,}`!*" if won else f"`{E_ERROR}` *No match — lost!*"
        e = discord.Embed(
            description=f"> `{E_SLOTS}` *Slots — {outcome}*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_SLOTS}` Reels", value=f"```{'  '.join(reels)}```", inline=False)
        e.add_field(name=f"`{E_YEN}` Bet",     value=f"```¥{amount:,}```",        inline=True)
        if won:
            e.add_field(name="`✖️` Multiplier",      value=f"```{multiplier}x```",   inline=True)
        else:
            _pad(e)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        return e

    @staticmethod
    def blackjack_start(
        player_hand: list[str],
        dealer_card: str,
        player_total: int,
        amount: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_CARDS}` *Blackjack — your turn*",
            color=get_color(),
        )
        e.add_field(
            name=f"`🧑` Your hand  ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        e.add_field(
            name="`🤖` Dealer shows",
            value=f"```{dealer_card}  🂠```",
            inline=True,
        )
        e.add_field(name=f"`{E_YEN}` Bet", value=f"```¥{amount:,}```", inline=True)
        _pad(e)
        e.set_footer(text="Hit to draw  ·  Stand to end your turn")
        return e

    @staticmethod
    def blackjack_end(
        player_hand: list[str],
        dealer_hand: list[str],
        player_total: int,
        dealer_total: int,
        result: str,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_CARDS}` *Blackjack — `{result}`*",
            color=get_color(),
        )
        e.add_field(
            name=f"`🧑` Your hand  ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        e.add_field(
            name=f"`🤖` Dealer  ({dealer_total})",
            value=f"```{'  '.join(dealer_hand)}```",
            inline=False,
        )
        e.add_field(name=f"`{E_YEN}` Bet",           value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_POT}` Payout",        value=f"```¥{payout:,}```", inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        return e

    @staticmethod
    def guess(
        mode: str,
        answer: str,
        won: bool,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = (
            f"`{E_SUCCESS}` *Correct — won `¥{payout:,}`!*"
            if won else
            f"`{E_ERROR}` *Wrong — answer was `{answer}`*"
        )
        e = discord.Embed(
            description=f"> `{E_DICE}` *Guess ({mode}) — {outcome}*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_YEN}` Bet",           value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True)
        _pad(e)
        return e

    # ── Investing ─────────────────────────────────────────────────────────────

    @staticmethod
    def invest(
        user: discord.User | discord.Member,
        amount: int,
        total_invested: int,
        vault_total: int,
        season_name: str,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_INVEST}` *Investment placed!*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name=f"`{E_YEN}` Invested",      value=f"```¥{amount:,}```",         inline=True)
        e.add_field(name="`📊` Your total",           value=f"```¥{total_invested:,}```", inline=True)
        e.add_field(name=f"`{E_VAULT}` Vault total",  value=f"```¥{vault_total:,}```",    inline=True)
        e.set_footer(text=f"Season: {season_name}  ·  Locked until season ends")
        return e

    @staticmethod
    def vault(
        guild_name: str,
        season_name: str,
        days_remaining: int,
        vault_total: int,
        top_investors: list[dict],
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_VAULT}` *{guild_name} — Season Vault*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_POT}` Total pooled",    value=f"```¥{vault_total:,}```", inline=True)
        e.add_field(name=f"`{E_CALENDAR}` Days left",  value=f"```{days_remaining}```",  inline=True)
        _pad(e)
        lines = []
        for i, row in enumerate(top_investors):
            medal = MEDALS[i] if i < len(MEDALS) else f"`#{i+1}`"
            lines.append(f"{medal} <@{row['user_id']}> — `¥{int(row['invested']):,}`")
        if lines:
            e.add_field(name=f"`{E_TROPHY}` Top investors", value="\n".join(lines), inline=False)
        e.set_footer(text=f"Season: {season_name}")
        return e

    # ── Season ────────────────────────────────────────────────────────────────

    @staticmethod
    def season_info(season: dict, vault_total: int) -> discord.Embed:
        end = datetime.fromisoformat(season["end"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = max(0, math.ceil((end - datetime.now(timezone.utc)).total_seconds() / 86400))
        e = discord.Embed(
            description=f"> `{E_SEASON}` *Season: **{season['name']}***",
            color=get_color(),
        )
        e.add_field(name=f"`{E_CALENDAR}` Days left",  value=f"```{days_left}```",            inline=True)
        e.add_field(name=f"`{E_VAULT}` Vault total",   value=f"```¥{vault_total:,}```",       inline=True)
        e.add_field(name=f"`{E_ENDS}` Ends",           value=f"<t:{int(end.timestamp())}:F>", inline=True)
        return e

    @staticmethod
    def season_start(season: dict) -> discord.Embed:
        end_raw = datetime.fromisoformat(season["end"])
        if end_raw.tzinfo is None:
            end_raw = end_raw.replace(tzinfo=timezone.utc)
        e = discord.Embed(
            description=f"> `{E_SEASON}` *A new season has begun — **{season['name']}***",
            color=get_color(),
        )
        e.add_field(name=f"`{E_ENDS}` Ends", value=f"<t:{int(end_raw.timestamp())}:F>", inline=True)
        e.set_footer(text="Invest in the vault to compete for season bonuses.")
        return e

    @staticmethod
    def season_end(
        season: dict,
        top_investors: list[dict],
        name_map: dict[int, str],
        bonuses: dict[int, int],
    ) -> discord.Embed:
        lines = []
        for i, row in enumerate(top_investors[:3]):
            uid   = int(row["user_id"])
            medal = [E_MEDAL_1, E_MEDAL_2, E_MEDAL_3][i]
            lines.append(
                f"{medal} **{name_map.get(uid, f'User {uid}')}**"
                f" — invested `¥{int(row['invested']):,}`"
                f" — bonus `¥{bonuses.get(uid, 0):,}`"
            )
        e = discord.Embed(
            description=f"> `{E_SEASON_END}` *Season **{season['name']}** has ended!*",
            color=get_color(),
        )
        if lines:
            e.add_field(name=f"`{E_TROPHY}` Top 3 investors", value="\n".join(lines), inline=False)
        e.set_footer(text="Bonuses paid to wallets  ·  New season starting shortly.")
        return e

    # ── Shop / inventory ──────────────────────────────────────────────────────

    @staticmethod
    def shop(
        guild_name: str,
        server_items: list[dict],
        global_items: list[dict],
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_SHOP}` *{guild_name} Shop*",
            color=get_color(),
        )

        def _item_line(item: dict) -> str:
            desc  = item.get("description") or "No description"
            itype = item.get("type", "")
            icon  = E_ROLE_ITEM if itype == "role" else E_ITEM
            return (
                f"`{icon}` **{item['name']}** — `¥{int(item['price']):,}`\n"
                f"> *{desc}*  ·  ID `{item['item_id']}`"
            )

        if server_items:
            e.add_field(
                name=f"`{E_GUILD}` Server items",
                value="\n".join(_item_line(i) for i in server_items),
                inline=False,
            )
        if global_items:
            e.add_field(
                name=f"`{E_GLOBAL}` Global items",
                value="\n".join(_item_line(i) for i in global_items),
                inline=False,
            )
        if not server_items and not global_items:
            e.add_field(name="Empty", value="> *No items available right now.*", inline=False)

        e.set_footer(text="Use /buy <item_id> to purchase")
        return e

    @staticmethod
    def purchase(item_name: str, price: int, wallet: int) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_BUY}` *Purchase successful!*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_ITEM}` Item",          value=f"```{item_name}```", inline=True)
        e.add_field(name=f"`{E_PAY}` Paid",           value=f"```¥{price:,}```",  inline=True)
        e.add_field(name=f"`{E_WALLET}` New balance",  value=f"```¥{wallet:,}```", inline=True)
        return e

    @staticmethod
    def inventory(
        user: discord.User | discord.Member,
        items: list[dict],
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_INVENTORY}` *{user.display_name}'s inventory*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        if not items:
            e.add_field(name="Empty", value="> *No items yet.*", inline=False)
        else:
            for item in items:
                shop  = item.get("shopitems") or {}
                itype = shop.get("type", "")
                icon  = E_ROLE_ITEM if itype == "role" else E_ITEM
                e.add_field(
                    name=f"`{icon}` {shop.get('name', 'Unknown')}",
                    value=(
                        f"> *{shop.get('description') or 'No description'}*\n"
                        f"> Type: `{itype or '?'}`"
                    ),
                    inline=False,
                )
        return e

    # ── Leaderboard ───────────────────────────────────────────────────────────

    @staticmethod
    def leaderboard(
        title: str,
        rows: list[dict],
        name_map: dict[int, str],
        value_key: str,
        value_prefix: str = "¥",
        season_name: str = "",
    ) -> discord.Embed:
        lines = []
        for i, row in enumerate(rows):
            medal = MEDALS[i] if i < len(MEDALS) else f"`#{i+1}`"
            uid   = int(row["user_id"])
            name  = name_map.get(uid, f"User {uid}")
            val   = int(row.get(value_key, 0))
            lines.append(f"{medal} **{name}** — `{value_prefix}{val:,}`")
        body = "\n".join(lines) if lines else "*No data yet.*"
        e = discord.Embed(
            description=f"> `{E_TROPHY}` *{title}*\n\n{body}",
            color=get_color(),
        )
        if season_name:
            e.set_footer(text=f"Season: {season_name}")
        return e

    @staticmethod
    def leaderboard_global(rows: list[dict]) -> discord.Embed:
        lines = []
        for i, row in enumerate(rows):
            medal   = MEDALS[i] if i < len(MEDALS) else f"`#{i+1}`"
            name    = row.get("guild_name", f"Server {row['guild_id']}")
            invite  = row.get("invite_url")
            display = f"[{name}]({invite})" if invite else f"**{name}**"
            tier    = int(row.get("tier", 1))
            tier_badge = TIER_EMOJI.get(tier, "")
            lines.append(
                f"{medal} {display} {tier_badge} — `¥{int(row['wallet_total']):,}`"
            )
        e = discord.Embed(
            description=f"> `{E_GLOBAL}` *Global Leaderboard — Top Servers*\n\n" + "\n".join(lines),
            color=get_color(),
        )
        e.set_footer(text="Ranked by total ¥ Yen held  ·  /global enrol to join")
        return e

    # ── Moderation ────────────────────────────────────────────────────────────

    @staticmethod
    def warn_issued(
        user: discord.User | discord.Member,
        reason: str,
        warn_count: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_WARN}` *Warning issued to **{user.display_name}***",
            color=get_color(),
        )
        e.add_field(name=f"`{E_REPORT}` Reason",     value=f"```{reason}```",          inline=False)
        e.add_field(name="`🔢` Count",               value=f"```{warn_count} / 3```",   inline=True)
        if warn_count >= 3:
            e.add_field(
                name=f"`{E_BANNED}` Auto-ban",
                value="> *3 warnings reached — user auto-banned.*",
                inline=False,
            )
        return e

    @staticmethod
    def warn_dm(reason: str, warn_count: int) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_WARN}` *You received a Denki warning.*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_REPORT}` Reason",  value=f"```{reason}```",        inline=False)
        e.add_field(name="`🔢` Warnings",         value=f"```{warn_count} / 3```", inline=True)
        e.set_footer(text="3 warnings = permanent ban from Denki.")
        return e

    @staticmethod
    def ban_dm(reason: str) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_BANNED}` *You have been permanently banned from Denki.*\n"
                f"> `{E_REPORT}` Reason: `{reason}`\n"
                f"> *Contact the bot owner if you believe this is a mistake.*"
            ),
            color=get_color(),
        )

    @staticmethod
    def report_dm(
        reporter: discord.User | discord.Member,
        reported: discord.User | discord.Member,
        guild_name: str,
        reason: str,
        wallet_snap: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_REPORT}` *New report filed*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_USER}` Reported",     value=f"```{reported} ({reported.id})```",  inline=False)
        e.add_field(name=f"`{E_GUILD}` Server",      value=f"```{guild_name}```",                 inline=True)
        e.add_field(name="`👮` Reporter",            value=f"```{reporter} ({reporter.id})```",   inline=True)
        _pad(e)
        e.add_field(name=f"`{E_REPORT}` Reason",     value=f"```{reason}```",                     inline=False)
        e.add_field(name=f"`{E_WALLET}` Wallet snap", value=f"```¥{wallet_snap:,}```",             inline=True)
        e.set_footer(text=f"!d warn {reported.id} <reason>  or  !d ban {reported.id} <reason>")
        return e

    # ── Notifications ─────────────────────────────────────────────────────────

    @staticmethod
    def notify_tier_change(new_tier: int, won: bool) -> discord.Embed:
        tier_badge = TIER_EMOJI.get(new_tier, "")
        if won:
            desc = (
                f"> `{E_TIER_UP}` *Your server won the season and advanced to "
                f"**Tier {new_tier}** {tier_badge}!*\n"
                f"> All members now receive boosted earn rewards."
            )
        else:
            desc = (
                f"> `{E_TIER_DOWN}` *Your server's win streak ended — dropped back to **Tier 1**.*\n"
                f"> Win a season to start climbing again."
            )
        return discord.Embed(description=desc, color=get_color())

    # ── Help ──────────────────────────────────────────────────────────────────

    @staticmethod
    def help_home() -> discord.Embed:
        modules = [
            (E_WALLET,    "economy",     "balance · daily · work · rob · pay · vote"),
            (E_COIN,      "gambling",    "coinflip · slots · blackjack · guess"),
            (E_INVEST,    "investing",   "invest · vault"),
            (E_SEASON,    "season",      "season info"),
            (E_SHOP,      "shop",        "shop · buy · inventory · additem"),
            (E_TROPHY,    "leaderboard", "server · investors · global"),
            (E_GEAR,      "admin",       "config · earnsettings · init"),
            (E_TEA_AI,    "tea",         "black · green · white · red · blue"),
        ]
        lines = "\n".join(
            f"> `{e}` **{mod}** — *{desc}*" for e, mod, desc in modules
        )
        e = discord.Embed(
            description=(
                f"> `{E_BOT}` *Welcome to **Denki** — the global Discord economy bot.*\n\n"
                f"> Your **¥ Yen wallet** is global — one balance across every server.\n"
                f"> Each server runs a **30-day season** — invest to win bonuses.\n\n"
                f"> Use `/help [module]` or `/help [command]` for details.\n\n"
                f"{lines}"
            ),
            color=get_color(),
        )
        e.set_footer(text="Prefix: !d  ·  Slash: /  ·  Both supported")
        return e

    @staticmethod
    def help_module(module: str, commands: list[dict]) -> discord.Embed:
        lines = []
        for cmd in commands:
            aliases = "  ".join(f"`{a}`" for a in cmd.get("aliases", []))
            line    = f"**{cmd['name']}** `{cmd['usage']}`"
            if aliases:
                line += f"  ·  {aliases}"
            line += f"\n> *{cmd['description']}*"
            lines.append(line)
        e = discord.Embed(
            description=f"> `{E_BOOK}` *Module: **{module}***\n\n" + "\n\n".join(lines),
            color=get_color(),
        )
        e.set_footer(text="<required>  [optional]  ·  Prefix: !d  ·  Slash: /")
        return e

    @staticmethod
    def help_command(
        name: str,
        aliases: list[str],
        usage: str,
        description: str,
        examples: list[str],
        notes: Optional[str] = None,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_BOOK}` *Command: **{name}***\n> *{description}*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_USAGE}` Usage",    value=f"```{usage}```", inline=False)
        if aliases:
            e.add_field(
                name=f"`{E_ALIAS}` Aliases",
                value="  ".join(f"`{a}`" for a in aliases),
                inline=False,
            )
        if examples:
            e.add_field(
                name=f"`{E_EXAMPLE}` Examples",
                value="\n".join(f"> `{ex}`" for ex in examples),
                inline=False,
            )
        if notes:
            e.add_field(name=f"`{E_NOTE}` Notes", value=f"> *{notes}*", inline=False)
        e.set_footer(text="<required>  [optional]  ·  Prefix: !d  ·  Slash: /")
        return e

    # ── Arcade ────────────────────────────────────────────────────────────────

    @staticmethod
    def arcade_challenge(challenge: "ArcadeChallenge") -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{challenge.game_emoji}` **{challenge.game_name}**\n\n"
                f"> {challenge.challenger.mention} challenged {challenge.opponent.mention}\n"
                f"> *{challenge.game_desc}*\n\n"
                f"> Bet: `¥{challenge.bet:,}` each  ·  Winner takes `¥{challenge.bet * 2:,}`"
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_challenge_accepted(challenge: "ArcadeChallenge") -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_SUCCESS}` *{challenge.opponent.display_name} accepted!*\n"
                f"> `{challenge.game_emoji}` **{challenge.game_name}** is starting…"
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_challenge_declined(challenge: "ArcadeChallenge") -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_CANCEL}` *{challenge.opponent.display_name} declined.*\n"
                f"> Bet `¥{challenge.bet:,}` refunded to {challenge.challenger.mention}."
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_challenge_expired(challenge: "ArcadeChallenge") -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_COOLDOWN}` *Challenge expired — {challenge.opponent.display_name} didn't respond.*\n"
                f"> Bet `¥{challenge.bet:,}` refunded to {challenge.challenger.mention}."
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_game_start(challenge: "ArcadeChallenge", rules: str) -> discord.Embed:
        e = discord.Embed(
            description=(
                f"> `{challenge.game_emoji}` **{challenge.game_name}**\n"
                f"> {challenge.challenger.mention}  vs  {challenge.opponent.mention}\n"
                f"> Pot: `¥{challenge.bet * 2:,}`"
            ),
            color=get_color(),
        )
        e.add_field(name=f"`{E_REPORT}` Rules", value=rules, inline=False)
        return e

    @staticmethod
    def arcade_game_over(
        winner: discord.Member,
        bet: int,
        scores: dict[int, int],
        p1: discord.Member,
        p2: discord.Member,
    ) -> discord.Embed:
        loser = p2 if winner.id == p1.id else p1
        e = discord.Embed(
            description=f"> `{E_TROPHY}` *{winner.display_name} wins!*",
            color=get_color(),
        )
        e.add_field(
            name="`📊` Score",
            value=f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
            inline=False,
        )
        e.add_field(name=f"`{E_POT}` Prize",  value=f"```¥{bet * 2:,}```",        inline=True)
        e.add_field(name=f"`{E_PAY}` Paid by", value=f"```{loser.display_name}```", inline=True)
        _pad(e)
        return e

    @staticmethod
    def arcade_tie(challenge: "ArcadeChallenge") -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `🤝` *It's a tie!*\n"
                f"> Both players receive their `¥{challenge.bet:,}` back."
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_timeout(player: discord.Member) -> discord.Embed:
        return discord.Embed(
            description=f"> `{E_COOLDOWN}` *{player.display_name} took too long — round forfeited.*",
            color=get_color(),
        )

    @staticmethod
    def arcade_round_result(
        winner: discord.Member | None,
        answer: str,
        timed_out: bool,
    ) -> discord.Embed:
        if timed_out:
            desc = f"> `{E_COOLDOWN}` *Nobody answered in time!*  ·  Answer: `{answer}`"
        elif winner:
            desc = f"> `{E_SUCCESS}` **{winner.display_name}** got it!  ·  `{answer}`"
        else:
            desc = f"> `{E_CANCEL}` *Nobody got it right.*  ·  Answer: `{answer}`"
        return discord.Embed(description=desc, color=get_color())

    @staticmethod
    def arcade_mathduel_round(
        rnd: int,
        total: int,
        equation: str,
        scores: dict[int, int],
        p1: discord.Member,
        p2: discord.Member,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_MATH}` *Math Duel — Round {rnd}/{total}*",
            color=get_color(),
        )
        e.add_field(name="`❓` Equation", value=f"```{equation} = ?```", inline=False)
        e.add_field(
            name="`📊` Score",
            value=f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
            inline=False,
        )
        e.set_footer(text="Type your answer — first correct wins the round!")
        return e

    @staticmethod
    def arcade_numberbomb_turn(
        player: discord.Member,
        available: list[int],
        picked: set[int],
    ) -> discord.Embed:
        remaining = "  ".join(str(n) for n in available)
        e = discord.Embed(
            description=f"> `{E_BOMB}` *Number Bomb — {player.display_name}'s turn*",
            color=get_color(),
        )
        e.add_field(name="`🔢` Available", value=f"```{remaining}```", inline=False)
        if picked:
            e.add_field(
                name=f"`{E_SUCCESS}` Picked",
                value=f"```{', '.join(str(n) for n in sorted(picked))}```",
                inline=False,
            )
        e.set_footer(text="Pick a number — don't hit the bomb!")
        return e

    @staticmethod
    def arcade_numberbomb_safe(player: discord.Member, chosen: int) -> discord.Embed:
        return discord.Embed(
            description=f"> `😌` *{player.display_name} picked `{chosen}` — safe!*",
            color=get_color(),
        )

    @staticmethod
    def arcade_numberbomb_explosion(
        loser: discord.Member,
        chosen: int,
        winner: discord.Member,
        bet: int,
    ) -> discord.Embed:
        e = discord.Embed(
            description=(
                f"> `{E_EXPLOSION}` **BOOM!** {loser.display_name} picked `{chosen}` — that was the bomb!\n\n"
                f"> `{E_TROPHY}` *{winner.display_name} wins!*"
            ),
            color=get_color(),
        )
        e.add_field(name=f"`{E_POT}` Prize", value=f"```¥{bet * 2:,}```", inline=True)
        return e

    @staticmethod
    def arcade_rps_dm(player: discord.Member) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `{E_RPS}` *Rock Paper Scissors*\n\n"
                f"> {player.display_name}, pick your move!\n"
                f"> *Your opponent won't see this until both picks are in.*"
            ),
            color=get_color(),
        )

    @staticmethod
    def arcade_rps_round(
        rnd: int,
        total: int,
        scores: dict[int, int],
        p1: discord.Member,
        p2: discord.Member,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_RPS}` *Rock Paper Scissors — Round {rnd}/{total}*\n> Check your DMs to pick!",
            color=get_color(),
        )
        e.add_field(
            name="`📊` Score",
            value=f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
            inline=False,
        )
        return e

    @staticmethod
    def arcade_rps_result(
        p1: discord.Member,
        c1: str,
        p2: discord.Member,
        c2: str,
        winner: discord.Member | None,
    ) -> discord.Embed:
        result_str = "🤝 *Tie!*" if winner is None else f"`{E_SUCCESS}` **{winner.display_name} wins the round!**"
        e = discord.Embed(description=f"> {result_str}", color=get_color())
        e.add_field(
            name="`🎮` Picks",
            value=f"```{p1.display_name}: {RPS_EMOJI.get(c1, c1)}  ·  {p2.display_name}: {RPS_EMOJI.get(c2, c2)}```",
            inline=False,
        )
        return e

    @staticmethod
    def arcade_ttt_board(
        view: "TicTacToeView",
        result: str | None,
        game_num: int = 1,
        total_games: int = 3,
    ) -> discord.Embed:
        if result is None:
            sym    = "❌" if view.current_symbol == "X" else "⭕"
            status = f"`{sym}` *{view.current_player.display_name}'s turn*"
        elif result == "draw":
            status = "`🤝` *Draw!*"
        elif result == "timeout":
            status = f"`{E_COOLDOWN}` *{view.current_player.display_name} timed out!*"
        else:
            sym   = "❌" if result == "X" else "⭕"
            gamer = view.p1 if result == "X" else view.p2
            status = f"`{sym}` **{gamer.display_name} wins this game!**"

        e = discord.Embed(
            description=f"> `❌` *Tic Tac Toe — Game {game_num}/{total_games}*\n> {status}",
            color=get_color(),
        )
        e.add_field(
            name="`👥` Players",
            value=f"```{view.p1.display_name} ❌  ·  {view.p2.display_name} ⭕```",
            inline=False,
        )
        return e

    @staticmethod
    def arcade_reaction_waiting(
        rnd: int,
        total: int,
        scores: dict[int, int],
        p1: discord.Member,
        p2: discord.Member,
    ) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_REACTION}` *Reaction Race — Round {rnd}/{total}*\n> Get ready…",
            color=get_color(),
        )
        e.add_field(
            name="`📊` Score",
            value=f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
            inline=False,
        )
        e.set_footer(text="Click ⚡ the instant it appears — watch for fake-outs!")
        return e


# ── Backwards compat alias so no cog breaks before the rename sweep ───────────
Embeds = UI

# ── Paginator ─────────────────────────────────────────────────────────────────

class PaginatorView(discord.ui.View):
    """
    Generic paginator.
    Buttons: ◀  ✖  ↺  ▶
    Owner-locked — only the invoking user can interact.
    """

    def __init__(
        self,
        pages: list[discord.Embed],
        owner_id: int,
        timeout: int = 120,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages    = pages
        self.owner_id = owner_id
        self.index    = 0
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.btn_prev.disabled = self.index == 0
        self.btn_next.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=UI.error("Only the command author can use these controls."),
                ephemeral=True,
            )
            return False
        return True

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def _rebuild_pages(self) -> list[discord.Embed]:
        return self.pages

    @discord.ui.button(label=E_PREV, style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index -= 1
        await self._edit(interaction)

    @discord.ui.button(label=E_CLOSE, style=discord.ButtonStyle.secondary, row=0)
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label=E_REFRESH, style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pages = await self._rebuild_pages()
        self.index = min(self.index, len(self.pages) - 1)
        await self._edit(interaction)

    @discord.ui.button(label=E_NEXT, style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index += 1
        await self._edit(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


# ── Confirm ───────────────────────────────────────────────────────────────────

class ConfirmView(discord.ui.View):
    """
    Simple two-button confirmation dialog.
    Usage:
        view = ConfirmView(owner_id)
        await ctx.reply(..., view=view)
        await view.wait()
        if view.confirmed: ...
    """

    def __init__(self, owner_id: int, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        self.owner_id  = owner_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji=E_CONFIRM, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        await interaction.response.edit_message(
            embed=UI.info("Confirmed — processing…"), view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=E_CANCEL, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        await interaction.response.edit_message(
            embed=UI.info("Cancelled."), view=None
        )
        self.stop()

# INPUT CONVERTERS & PARSERS

def parse_amount(raw: str, wallet: int) -> int | None:
    """
    Parse a bet/amount string.
    Accepts: integer, 'all', '1.5k', '2m', comma-formatted numbers.
    Returns None on invalid input.
    """
    cleaned    = raw.strip().replace(",", "").replace("_", "")
    multiplier = 1

    if cleaned.lower() == "all":
        return wallet

    if cleaned.lower().endswith("k"):
        multiplier = 1_000
        cleaned    = cleaned[:-1]
    elif cleaned.lower().endswith("m"):
        multiplier = 1_000_000
        cleaned    = cleaned[:-1]

    try:
        value = round(float(cleaned) * multiplier)
        return value if value != 0 else None
    except ValueError:
        return None


def format_remaining(delta) -> str:  # accepts timedelta
    """Format a timedelta as '2h 30m 15s'."""
    total    = int(delta.total_seconds())
    h, rem   = divmod(total, 3600)
    m, s     = divmod(rem, 60)
    parts: list[str] = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


class UserIDConverter(_commands.Converter):
    """Accept a raw user ID or a <@mention> and return an int."""

    async def convert(self, ctx: Any, argument: str) -> int:
        stripped = argument.strip().lstrip("<@!").rstrip(">")
        try:
            return int(stripped)
        except ValueError:
            raise _commands.BadArgument(
                f"`{argument}` is not a valid user ID or mention."
            )


class AmountConverter(_commands.Converter):
    """Accept integers, decimals, k/m shorthands, comma-formatted numbers."""

    async def convert(self, ctx: Any, argument: str) -> int:
        result = parse_amount(argument, wallet=0)  # wallet=0 — 'all' resolves to 0 here
        if result is None or result == 0:
            raise _commands.BadArgument(
                f"`{argument}` is not a valid amount. Examples: `500`, `1.5k`, `2m`, `-100`"
            )
        return result