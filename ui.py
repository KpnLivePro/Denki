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
    E_ALIAS,
    E_ANNOUNCE,
    E_BANNED,
    E_BANK,
    E_BELL,
    E_BOT,
    E_BOOK,
    E_BUY,
    E_CALENDAR,
    E_CARDS,
    E_CLOSE,
    E_COIN,
    E_CONFIRM,
    E_COOLDOWN,
    E_CRITICAL,
    E_CPU,
    E_DAILY,
    E_DB,
    E_DICE,
    E_DONE,
    E_ENDS,
    E_ERROR,
    E_EXAMPLE,
    E_EXPLOSION,
    E_GEAR,
    E_GLOBAL,
    E_GUILD,
    E_INFO,
    E_INVEST,
    E_INVESTED,
    E_INVENTORY,
    E_ITEM,
    E_MATH,
    E_MEDAL_1,
    E_MEDAL_2,
    E_MEDAL_3,
    E_MEMORY,
    E_NEXT,
    E_NOTE,
    E_OFFLINE,
    E_ONLINE,
    E_PAY,
    E_PING,
    E_POT,
    E_PREV,
    E_PYTHON,
    E_REACTION,
    E_REFRESH,
    E_REPORT,
    E_RESTART,
    E_ROB,
    E_ROLE_ITEM,
    E_RPS,
    E_SEASON,
    E_SEASON_END,
    E_SHOP,
    E_SKULL,
    E_SKIP,
    E_SLOTS,
    E_START,
    E_STATS,
    E_STREAK,
    E_SUCCESS,
    E_TIER_DOWN,
    E_TIER_UP,
    E_TROPHY,
    E_TTT,
    E_TTT_O,
    E_USAGE,
    E_USER,
    E_VAULT,
    E_VOTE,
    E_WARN,
    E_WALLET,
    E_WORK,
    E_YEN,
    E_TEA_AI,
    E_CANCEL,
    E_BOMB,
    E_EXPLOSION as _EXP,
    E_QUESTION,
    E_NUMBERS,
    E_RELIEVED,
    E_HANDSHAKE,
    E_GAMEPAD,
    E_PEOPLE,
    E_LIGHTNING,
    MEDALS,
    RPS_EMOJI,
    TIER_EMOJI,
)

if TYPE_CHECKING:
    from cogs.arcade import ArcadeChallenge, TicTacToeView

# ── Color cache ───────────────────────────────────────────────────────────────

import logging as _logging

_log = _logging.getLogger("denki.ui")

DEFAULT_COLOR = 0xCD7F32
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
    if streak >= 30:
        return f"{E_STREAK} **30-day streak!**  `2x bonus`"
    if streak >= 14:
        return f"{E_STREAK} **14-day streak!**  `1.5x bonus`"
    if streak >= 7:
        return f"{E_STREAK} **7-day streak!**   `1.25x bonus`"
    if streak >= 3:
        return f"{E_STREAK} **3-day streak!**   `1.1x bonus`"
    return ""


def _next_milestone(streak: int) -> str:
    if streak < 3:
        return f"`{3  - streak}` more for **1.1x**"
    if streak < 7:
        return f"`{7  - streak}` more for **1.25x**"
    if streak < 14:
        return f"`{14 - streak}` more for **1.5x**"
    if streak < 30:
        return f"`{30 - streak}` more for **2x**"
    return f"Max streak bonus! {E_SUCCESS}"


# ── EMBED ─────────────────────────────────────────────────────────────────────


class UI:
    """
    Central embed factory for Denki.
    All methods are static — call as UI.balance(...) etc.
    Cogs import UI instead of the old Embeds class.
    """

    @staticmethod
    def embed(
        emoji: str, user: discord.User | discord.Member, response: str, **kwargs
    ) -> discord.Embed:
        """
        Unified embed factory following the pattern:
        > {emoji} {user.mention} - *{response}*
        """
        e = discord.Embed(
            description=f"> {emoji} {user.mention} - *{response}*",
            color=get_color(),
        )

        # Add optional fields
        if "fields" in kwargs:
            for field in kwargs["fields"]:
                e.add_field(**field)

        # Add optional footer
        if "footer" in kwargs:
            e.set_footer(text=kwargs["footer"])

        # Add optional thumbnail
        if "thumbnail" in kwargs:
            e.set_thumbnail(url=kwargs["thumbnail"])

        return e

    # ── Base / feedback ───────────────────────────────────────────────────────

    @staticmethod
    def base(description: str, footer: Optional[str] = None) -> discord.Embed:
        e = discord.Embed(description=description, color=get_color())
        if footer:
            e.set_footer(text=footer)
        return e

    @staticmethod
    def error(user: discord.User | discord.Member, message: str) -> discord.Embed:
        return UI.embed(E_ERROR, user, message)

    @staticmethod
    def success(user: discord.User | discord.Member, message: str) -> discord.Embed:
        return UI.embed(E_SUCCESS, user, message)

    @staticmethod
    def info(user: discord.User | discord.Member, message: str) -> discord.Embed:
        return UI.embed(E_INFO, user, message)

    @staticmethod
    def warn(user: discord.User | discord.Member, message: str) -> discord.Embed:
        return UI.embed(E_WARN, user, message)

    @staticmethod
    def critical(
        user: discord.User | discord.Member, error: BaseException | str
    ) -> discord.Embed:
        tb = (
            "".join(traceback.format_exception(type(error), error, error.__traceback__))
            if isinstance(error, BaseException)
            else str(error)
        )
        return discord.Embed(
            description=f"> {E_CRITICAL} {user.mention} - *Critical error:*\n```\n{tb[:1800]}\n```",
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
            description=f"> {E_USER} {user.mention} - *{user.display_name}'s balance*",
            color=get_color(),
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(
            name=f"`{E_WALLET}` Pocket", value=f"```¥{wallet:,}```", inline=True
        )
        e.add_field(
            name=f"`{E_BANK}` Server bank",
            value=f"```¥{bank_balance:,}```",
            inline=True,
        )
        e.add_field(
            name=f"`{E_INVEST}` Invested",
            value=f"```¥{bank_invested:,}```",
            inline=True,
        )
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
        return UI.embed(
            E_DAILY,
            user,
            f"Daily reward claimed!{tier_note}*",
            fields=[
                {
                    "name": f"`{E_YEN}` Earned",
                    "value": f"```¥{amount:,}```",
                    "inline": True,
                },
                {
                    "name": f"`{E_WALLET}` New balance",
                    "value": f"```¥{wallet:,}```",
                    "inline": True,
                },
            ],
        )

    @staticmethod
    def work(
        user: discord.User | discord.Member,
        job: str,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        return UI.embed(
            E_WORK,
            user,
            f"You worked as a **{job}**!*",
            fields=[
                {
                    "name": f"`{E_YEN}` Earned",
                    "value": f"```¥{amount:,}```",
                    "inline": True,
                },
                {
                    "name": f"`{E_WALLET}` New balance",
                    "value": f"```¥{wallet:,}```",
                    "inline": True,
                },
            ],
        )

    @staticmethod
    def rob_success(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        stolen: int,
    ) -> discord.Embed:
        return UI.embed(
            E_ROB,
            robber,
            f"{robber.display_name} robbed {victim.display_name}! Snatched `¥{stolen:,}` from their pocket.",
        )

    @staticmethod
    def rob_fail(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        fine: int,
    ) -> discord.Embed:
        return UI.embed(
            E_ROB,
            robber,
            f"{robber.display_name} got caught trying to rob {victim.display_name}! Paid a fine of `¥{fine:,}`.",
        )

    @staticmethod
    def pay(
        sender: discord.User | discord.Member,
        receiver: discord.User | discord.Member,
        amount: int,
    ) -> discord.Embed:
        return UI.embed(
            E_PAY,
            sender,
            f"Payment sent! {sender.mention} → {receiver.mention}  ·  `¥{amount:,}`",
        )

    @staticmethod
    def cooldown(
        user: discord.User | discord.Member, command: str, remaining: str
    ) -> discord.Embed:
        return UI.embed(
            E_COOLDOWN,
            user,
            f"`/{command}` is on cooldown. Try again in `{remaining}`.",
        )

    # ── Vote ──────────────────────────────────────────────────────────────────

    @staticmethod
    def vote_prompt(
        user: discord.User | discord.Member, vote_url: str, current_streak: int = 0
    ) -> discord.Embed:
        streak_line = (
            f"> {E_STREAK} Streak: `{current_streak}` day(s)  ·  {_next_milestone(current_streak)}\n"
            if current_streak > 0
            else ""
        )
        return UI.embed(
            E_VOTE,
            user,
            f"You haven't voted yet! [**Vote for Denki on top.gg**]({vote_url}) then run `/vote` again to claim your reward.\n\n{streak_line}> Base `¥2,000`  ·  Weekend `¥4,000`  ·  Streak bonuses apply\n> Cooldown: **12 hours**",
        )

    @staticmethod
    def vote_cooldown(
        user: discord.User | discord.Member, remaining: str, vote_url: str
    ) -> discord.Embed:
        return UI.embed(
            E_COOLDOWN,
            user,
            f"Vote reward already claimed. Next claim in `{remaining}`\n[Vote early]({vote_url}) — reward waits until cooldown expires.",
        )

    @staticmethod
    def vote_reward(
        user: discord.User | discord.Member,
        amount: int,
        wallet: int,
        streak: int,
        is_weekend: bool,
    ) -> discord.Embed:
        weekend = f"  ·  `2x weekend!` {E_SUCCESS}" if is_weekend else ""
        milestone = _streak_label(streak)
        desc = f"Thanks for voting!{weekend}*"
        if milestone:
            desc += f"\n> {milestone}"

        e = UI.embed(E_VOTE, user, desc, thumbnail=user.display_avatar.url)
        e.add_field(name=f"`{E_YEN}` Reward", value=f"```¥{amount:,}```", inline=True)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
        e.add_field(
            name=f"`{E_STREAK}` Streak", value=f"```{streak} day(s)```", inline=True
        )
        e.set_footer(text=f"{_next_milestone(streak)}  ·  Vote again in 12h")
        return e

    # ── Gambling ──────────────────────────────────────────────────────────────

    @staticmethod
    def coinflip(
        user: discord.User | discord.Member,
        choice: str,
        result: str,
        won: bool,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"You won!" if won else f"You lost!"
        e = UI.embed(
            E_COIN,
            user,
            f"Coinflip — {outcome}*",
        )
        e.add_field(name=f"`{E_DICE}` Your call", value=f"```{choice}```", inline=True)
        e.add_field(name=f"`{E_COIN}` Result", value=f"```{result}```", inline=True)
        e.add_field(name=f"`{E_YEN}` Bet", value=f"```¥{amount:,}```", inline=True)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
        _pad(e, 2)
        return e

    @staticmethod
    def slots(
        user: discord.User | discord.Member,
        reels: list[str],
        won: bool,
        multiplier: float,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"You won `¥{payout:,}`!" if won else f"No match — lost!"
        e = UI.embed(
            E_SLOTS,
            user,
            f"Slots — {outcome}*",
        )
        e.add_field(
            name=f"`{E_SLOTS}` Reels", value=f"```{'  '.join(reels)}```", inline=False
        )
        e.add_field(name=f"`{E_YEN}` Bet", value=f"```¥{amount:,}```", inline=True)
        if won:
            e.add_field(
                name="`✖️` Multiplier", value=f"```{multiplier}x```", inline=True
            )
        else:
            _pad(e)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
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
            name=f"`{E_USER}` Your hand  ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        e.add_field(
            name=f"`{E_BOT}` Dealer shows",
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
            name=f"`{E_USER}` Your hand  ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        e.add_field(
            name=f"`{E_BOT}` Dealer  ({dealer_total})",
            value=f"```{'  '.join(dealer_hand)}```",
            inline=False,
        )
        e.add_field(name=f"`{E_YEN}` Bet", value=f"```¥{amount:,}```", inline=True)
        e.add_field(name=f"`{E_POT}` Payout", value=f"```¥{payout:,}```", inline=True)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
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
            if won
            else f"`{E_ERROR}` *Wrong — answer was `{answer}`*"
        )
        e = discord.Embed(
            description=f"> `{E_DICE}` *Guess ({mode}) — {outcome}*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_YEN}` Bet", value=f"```¥{amount:,}```", inline=True)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
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
        e.add_field(name=f"`{E_YEN}` Invested", value=f"```¥{amount:,}```", inline=True)
        e.add_field(
            name=f"`{E_STATS}` Your total",
            value=f"```¥{total_invested:,}```",
            inline=True,
        )
        e.add_field(
            name=f"`{E_VAULT}` Vault total",
            value=f"```¥{vault_total:,}```",
            inline=True,
        )
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
        e.add_field(
            name=f"`{E_POT}` Total pooled", value=f"```¥{vault_total:,}```", inline=True
        )
        e.add_field(
            name=f"`{E_CALENDAR}` Days left",
            value=f"```{days_remaining}```",
            inline=True,
        )
        _pad(e)
        lines = []
        for i, row in enumerate(top_investors):
            medal = MEDALS[i] if i < len(MEDALS) else f"`#{i+1}`"
            lines.append(f"{medal} <@{row['user_id']}> — `¥{int(row['invested']):,}`")
        if lines:
            e.add_field(
                name=f"`{E_TROPHY}` Top investors", value="\n".join(lines), inline=False
            )
        e.set_footer(text=f"Season: {season_name}")
        return e

    # ── Season ────────────────────────────────────────────────────────────────

    @staticmethod
    def season_info(season: dict, vault_total: int) -> discord.Embed:
        end = datetime.fromisoformat(season["end"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = max(
            0, math.ceil((end - datetime.now(timezone.utc)).total_seconds() / 86400)
        )
        e = discord.Embed(
            description=f"> `{E_SEASON}` *Season: **{season['name']}***",
            color=get_color(),
        )
        e.add_field(
            name=f"`{E_CALENDAR}` Days left", value=f"```{days_left}```", inline=True
        )
        e.add_field(
            name=f"`{E_VAULT}` Vault total",
            value=f"```¥{vault_total:,}```",
            inline=True,
        )
        e.add_field(
            name=f"`{E_ENDS}` Ends", value=f"<t:{int(end.timestamp())}:F>", inline=True
        )
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
        e.add_field(
            name=f"`{E_ENDS}` Ends",
            value=f"<t:{int(end_raw.timestamp())}:F>",
            inline=True,
        )
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
            uid = int(row["user_id"])
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
            e.add_field(
                name=f"`{E_TROPHY}` Top 3 investors",
                value="\n".join(lines),
                inline=False,
            )
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
            desc = item.get("description") or "No description"
            itype = item.get("type", "")
            icon = E_ROLE_ITEM if itype == "role" else E_ITEM
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
            e.add_field(
                name="Empty", value="> *No items available right now.*", inline=False
            )

        e.set_footer(text="Use /buy <item_id> to purchase")
        return e

    @staticmethod
    def purchase(item_name: str, price: int, wallet: int) -> discord.Embed:
        e = discord.Embed(
            description=f"> `{E_BUY}` *Purchase successful!*",
            color=get_color(),
        )
        e.add_field(name=f"`{E_ITEM}` Item", value=f"```{item_name}```", inline=True)
        e.add_field(name=f"`{E_PAY}` Paid", value=f"```¥{price:,}```", inline=True)
        e.add_field(
            name=f"`{E_WALLET}` New balance", value=f"```¥{wallet:,}```", inline=True
        )
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
                shop = item.get("shopitems") or {}
                itype = shop.get("type", "")
                icon = E_ROLE_ITEM if itype == "role" else E_ITEM
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
            uid = int(row["user_id"])
            name = name_map.get(uid, f"User {uid}")
            val = int(row.get(value_key, 0))
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
            medal = MEDALS[i] if i < len(MEDALS) else f"`#{i+1}`"
            name = row.get("guild_name", f"Server {row['guild_id']}")
            invite = row.get("invite_url")
            display = f"[{name}]({invite})" if invite else f"**{name}**"
            tier = int(row.get("tier", 1))
            tier_badge = TIER_EMOJI.get(tier, "")
            lines.append(
                f"{medal} {display} {tier_badge} — `¥{int(row['wallet_total']):,}`"
            )
        e = discord.Embed(
            description=f"> `{E_GLOBAL}` *Global Leaderboard — Top Servers*\n\n"
            + "\n".join(lines),
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
        e.add_field(name=f"`{E_REPORT}` Reason", value=f"```{reason}```", inline=False)
        e.add_field(
            name=f"`{E_NUMBERS}` Count", value=f"```{warn_count} / 3```", inline=True
        )
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
        e.add_field(name=f"`{E_REPORT}` Reason", value=f"```{reason}```", inline=False)
        e.add_field(
            name=f"`{E_NUMBERS}` Warnings", value=f"```{warn_count} / 3```", inline=True
        )
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
        e.add_field(
            name=f"`{E_USER}` Reported",
            value=f"```{reported} ({reported.id})```",
            inline=False,
        )
        e.add_field(
            name=f"`{E_GUILD}` Server", value=f"```{guild_name}```", inline=True
        )
        e.add_field(
            name=f"`{E_REPORT}` Reporter",
            value=f"```{reporter} ({reporter.id})```",
            inline=True,
        )
        _pad(e)
        e.add_field(name=f"`{E_REPORT}` Reason", value=f"```{reason}```", inline=False)
        e.add_field(
            name=f"`{E_WALLET}` Wallet snap",
            value=f"```¥{wallet_snap:,}```",
            inline=True,
        )
        e.set_footer(
            text=f"!d warn {reported.id} <reason>  or  !d ban {reported.id} <reason>"
        )
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
    def help_home(user: discord.User | discord.Member) -> discord.Embed:
        modules = [
            (E_WALLET, "economy", "balance · daily · work · rob · pay · vote"),
            (E_COIN, "gambling", "coinflip · slots · blackjack · guess"),
            (E_INVEST, "investing", "invest · vault"),
            (E_SEASON, "season", "season info"),
            (E_SHOP, "shop", "shop · buy · inventory · additem"),
            (E_TROPHY, "leaderboard", "server · investors · global"),
            (E_GEAR, "admin", "config · earnsettings · init"),
            (E_TEA_AI, "tea", "black · green · white · red · blue"),
        ]
        lines = "\n".join(f"> `{e}` **{mod}** — *{desc}*" for e, mod, desc in modules)
        return UI.embed(
            E_BOT,
            user,
            f"Welcome to **Denki** — the global Discord economy bot.*\n\n"
            f"> Your **¥ Yen wallet** is global — one balance across every server.\n"
            f"> Each server runs a **30-day season** — invest to win bonuses.\n\n"
            f"> Use `/help [module]` or `/help [command]` for details.\n\n{lines}",
            footer="Prefix: !d  ·  Slash: /  ·  Both supported",
        )

    @staticmethod
    def help_module(
        user: discord.User | discord.Member, module: str, commands: list[dict]
    ) -> discord.Embed:
        lines = []
        for cmd in commands:
            aliases = "  ".join(f"`{a}`" for a in cmd.get("aliases", []))
            line = f"**{cmd['name']}** `{cmd['usage']}`"
            if aliases:
                line += f"  ·  {aliases}"
            line += f"\n> *{cmd['description']}*"
            lines.append(line)
        e = UI.embed(
            E_BOOK,
            user,
            f"Module: **{module}***\n\n" + "\n\n".join(lines),
        )
        e.set_footer(text="<required>  [optional]  ·  Prefix: !d  ·  Slash: /")
        return e

    @staticmethod
    def help_command(
        user: discord.User | discord.Member,
        name: str,
        aliases: list[str],
        usage: str,
        description: str,
        examples: list[str],
        notes: Optional[str] = None,
    ) -> discord.Embed:
        e = UI.embed(
            E_BOOK,
            user,
            f"Command: **{name}***\n> *{description}*",
        )
        e.add_field(name=f"`{E_USAGE}` Usage", value=f"```{usage}```", inline=False)
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
        return UI.embed(
            challenge.game_emoji,
            challenge.challenger,
            f"{challenge.challenger.display_name} challenged {challenge.opponent.display_name}!*\n\n> *{challenge.game_desc}*\n\n> Bet: `¥{challenge.bet:,}` each  ·  Winner takes `¥{challenge.bet * 2:,}`",
        )

    @staticmethod
    def arcade_challenge_accepted(challenge: "ArcadeChallenge") -> discord.Embed:
        return UI.embed(
            E_SUCCESS,
            challenge.challenger,
            f"{challenge.opponent.display_name} accepted! {challenge.game_emoji} **{challenge.game_name}** is starting…*",
        )

    @staticmethod
    def arcade_challenge_declined(challenge: "ArcadeChallenge") -> discord.Embed:
        return UI.embed(
            E_CANCEL,
            challenge.challenger,
            f"{challenge.opponent.display_name} declined. Bet `¥{challenge.bet:,}` refunded.*",
        )

    @staticmethod
    def arcade_challenge_expired(challenge: "ArcadeChallenge") -> discord.Embed:
        return UI.embed(
            E_COOLDOWN,
            challenge.challenger,
            f"Challenge expired — {challenge.opponent.display_name} didn't respond. Bet `¥{challenge.bet:,}` refunded.*",
        )

    @staticmethod
    def arcade_game_start(challenge: "ArcadeChallenge", rules: str) -> discord.Embed:
        return UI.embed(
            challenge.game_emoji,
            challenge.challenger,
            f"**{challenge.game_name}**\n{challenge.challenger.mention}  vs  {challenge.opponent.mention}\nPot: `¥{challenge.bet * 2:,}`*",
            fields=[{"name": f"`{E_REPORT}` Rules", "value": rules, "inline": False}],
        )

    @staticmethod
    def arcade_game_over(
        winner: discord.Member,
        bet: int,
        scores: dict[int, int],
        p1: discord.Member,
        p2: discord.Member,
    ) -> discord.Embed:
        loser = p2 if winner.id == p1.id else p1
        return UI.embed(
            E_TROPHY,
            winner,
            f"{winner.display_name} wins!*",
            fields=[
                {
                    "name": f"`{E_STATS}` Score",
                    "value": f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
                    "inline": False,
                },
                {
                    "name": f"`{E_POT}` Prize",
                    "value": f"```¥{bet * 2:,}```",
                    "inline": True,
                },
                {
                    "name": f"`{E_PAY}` Paid by",
                    "value": f"```{loser.display_name}```",
                    "inline": True,
                },
            ],
        )

    @staticmethod
    def arcade_tie(challenge: "ArcadeChallenge") -> discord.Embed:
        return UI.embed(
            E_HANDSHAKE,
            challenge.challenger,
            f"It's a tie! Both players receive their `¥{challenge.bet:,}` back.*",
        )

    @staticmethod
    def arcade_timeout(player: discord.Member) -> discord.Embed:
        return UI.embed(
            E_COOLDOWN,
            player,
            f"{player.display_name} took too long — round forfeited.*",
        )

    @staticmethod
    def arcade_round_result(
        winner: discord.Member | None,
        answer: str,
        timed_out: bool,
    ) -> discord.Embed:
        if timed_out:
            desc = f"Nobody answered in time!  ·  Answer: `{answer}`"
        elif winner:
            desc = f"**{winner.display_name}** got it!  ·  `{answer}`"
        else:
            desc = f"Nobody got it right.  ·  Answer: `{answer}`"
        emoji = E_COOLDOWN if timed_out else (E_SUCCESS if winner else E_CANCEL)
        user = winner if winner else None  # This will need to be fixed - we need a user
        # For now, return a basic embed since we don't have a user
        return discord.Embed(
            description=f"> `{emoji}` *{desc}*",
            color=get_color(),
        )

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
        e.add_field(
            name=f"`{E_QUESTION}` Equation", value=f"```{equation} = ?```", inline=False
        )
        e.add_field(
            name=f"`{E_STATS}` Score",
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
        e.add_field(
            name=f"`{E_NUMBERS}` Available", value=f"```{remaining}```", inline=False
        )
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
        return UI.embed(
            E_RELIEVED, player, f"{player.display_name} picked `{chosen}` — safe!*"
        )

    @staticmethod
    def arcade_numberbomb_explosion(
        loser: discord.Member,
        chosen: int,
        winner: discord.Member,
        bet: int,
    ) -> discord.Embed:
        return UI.embed(
            E_EXPLOSION,
            winner,
            f"**BOOM!** {loser.display_name} picked `{chosen}` — that was the bomb!*\n\n> `{E_TROPHY}` *{winner.display_name} wins!*",
            fields=[
                {
                    "name": f"`{E_POT}` Prize",
                    "value": f"```¥{bet * 2:,}```",
                    "inline": True,
                }
            ],
        )

    @staticmethod
    def arcade_rps_dm(player: discord.Member) -> discord.Embed:
        return UI.embed(
            E_RPS,
            player,
            f"Rock Paper Scissors*\n\n> {player.display_name}, pick your move!\n> *Your opponent won't see this until both picks are in.*",
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
            name=f"`{E_STATS}` Score",
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
        result_str = (
            f"{E_HANDSHAKE} *Tie!*"
            if winner is None
            else f"`{E_SUCCESS}` **{winner.display_name} wins the round!**"
        )
        e = discord.Embed(description=f"> {result_str}", color=get_color())
        e.add_field(
            name=f"`{E_GAMEPAD}` Picks",
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
            sym = E_TTT if view.current_symbol == "X" else E_TTT_O
            status = f"`{sym}` *{view.current_player.display_name}'s turn*"
        elif result == "draw":
            status = f"`{E_HANDSHAKE}` *Draw!*"
        elif result == "timeout":
            status = f"`{E_COOLDOWN}` *{view.current_player.display_name} timed out!*"
        else:
            sym = E_TTT if result == "X" else E_TTT_O
            gamer = view.p1 if result == "X" else view.p2
            status = f"`{sym}` **{gamer.display_name} wins this game!**"

        e = discord.Embed(
            description=f"> `{E_TTT}` *Tic Tac Toe — Game {game_num}/{total_games}*\n> {status}",
            color=get_color(),
        )
        e.add_field(
            name=f"`{E_PEOPLE}` Players",
            value=f"```{view.p1.display_name} {E_TTT}  ·  {view.p2.display_name} {E_TTT_O}```",
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
            name=f"`{E_STATS}` Score",
            value=f"```{p1.display_name}: {scores[p1.id]}  ·  {p2.display_name}: {scores[p2.id]}```",
            inline=False,
        )
        e.set_footer(
            text=f"Click {E_LIGHTNING} the instant it appears — watch for fake-outs!"
        )
        return e


# ── CREATE COMPONENT V2 ──────────────────────────────────────────────────────


class HelpView(discord.ui.LayoutView):
    """
    Components V2 help system — replaces static COMMAND_MAP with interactive UI.
    Owner-locked — only the invoking user can interact.
    """

    def __init__(self, user: discord.User | discord.Member):
        super().__init__(timeout=300)
        self.user = user
        self.current_module: str | None = None
        self._build_initial_view()

    def _build_initial_view(self) -> None:
        """Build the initial help home view."""
        self.clear_items()

        # Module buttons in action row — max 5 per row
        modules = [
            ("Economy", E_WALLET, "balance · daily · work · rob · pay · vote"),
            ("Gambling", E_COIN, "coinflip · slots · blackjack · guess"),
            ("Investing", E_INVEST, "invest · vault"),
            ("Season", E_SEASON, "season info"),
            ("Shop", E_SHOP, "shop · buy · inventory"),
        ]

        row1 = discord.ui.ActionRow()
        for name, emoji, desc in modules[:5]:
            button = discord.ui.Button(
                label=f"{emoji} {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"help_mod_{name.lower()}",
            )
            row1.add_item(button)
        self.add_item(row1)

        # Additional modules
        modules_2 = [
            ("Leaderboard", E_TROPHY, "server · investors · global"),
            ("Admin", E_GEAR, "config · earnsettings · init"),
            ("Tea", E_TEA_AI, "black · green · white · red · blue"),
        ]

        row2 = discord.ui.ActionRow()
        for name, emoji, desc in modules_2:
            button = discord.ui.Button(
                label=f"{emoji} {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"help_mod_{name.lower()}",
            )
            row2.add_item(button)
        self.add_item(row2)

        # Footer row
        footer_row = discord.ui.ActionRow()
        footer_button = discord.ui.Button(
            label=f"{E_BOOK} Back",
            style=discord.ButtonStyle.secondary,
            custom_id="help_home",
        )
        footer_row.add_item(footer_button)
        self.add_item(footer_row)

    async def _show_module(
        self, interaction: discord.Interaction, module_name: str, emoji: str, desc: str
    ) -> None:
        """Show commands for a specific module."""
        self.clear_items()
        self.current_module = module_name

        # Get commands for this module
        commands = self._get_module_commands(module_name)

        # Command list is included in the embed (not in view items)

        # Back button
        back_row = discord.ui.ActionRow()
        back_button = discord.ui.Button(
            label="← Back", style=discord.ButtonStyle.secondary, custom_id="help_back"
        )
        back_row.add_item(back_button)
        self.add_item(back_row)

        await interaction.response.edit_message(view=self)

    def _get_module_commands(self, module_name: str) -> list[dict]:
        """Get command data for a module (stub for introspection)."""
        command_map = {
            "economy": [
                {"name": "/balance", "description": "Check wallet, bank, investments"},
                {"name": "/daily", "description": "Claim daily reward"},
                {"name": "/work", "description": "Pick a random job"},
                {"name": "/rob", "description": "Rob another player"},
                {"name": "/pay", "description": "Send Yen to someone"},
                {"name": "/vote", "description": "Vote on top.gg"},
            ],
            "gambling": [
                {"name": "/coinflip", "description": "Flip a coin for Yen"},
                {"name": "/slots", "description": "Spin for rewards"},
                {"name": "/blackjack", "description": "Play blackjack"},
            ],
            "investing": [
                {"name": "/invest", "description": "Invest Yen in the vault"},
                {"name": "/vault", "description": "Check vault status"},
            ],
            "season": [
                {"name": "/season", "description": "View season info"},
            ],
            "shop": [
                {"name": "/shop", "description": "View items for sale"},
                {"name": "/buy", "description": "Purchase an item"},
                {"name": "/inventory", "description": "View your items"},
            ],
            "leaderboard": [
                {"name": "/leaderboard", "description": "Global wealth ranking"},
            ],
            "admin": [
                {"name": "/config", "description": "Configure server settings"},
            ],
            "tea": [
                {"name": "/tea", "description": "Play tea brewing game"},
            ],
        }
        return command_map.get(module_name, [])

    async def _back_to_home(self, interaction: discord.Interaction) -> None:
        """Go back to home view."""
        self._build_initial_view()
        await interaction.response.edit_message(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the invoking user to interact."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=UI.error(interaction.user, "You can't use this help menu."),
                ephemeral=True,
            )
            return False

        # Route button clicks if data is available
        if interaction.data:
            custom_id = interaction.data.get("custom_id", "")

            if custom_id.startswith("help_mod_"):
                module = custom_id.replace("help_mod_", "").lower()
                emoji_map = {
                    "economy": E_WALLET,
                    "gambling": E_COIN,
                    "investing": E_INVEST,
                    "season": E_SEASON,
                    "shop": E_SHOP,
                    "leaderboard": E_TROPHY,
                    "admin": E_GEAR,
                    "tea": E_TEA_AI,
                }
                emoji = emoji_map.get(module, E_INFO)
                await self._show_module(interaction, module, emoji, "")
                return False

            elif custom_id == "help_back":
                await self._back_to_home(interaction)
                return False

        return True

        return True


# ── PARSE ────────────────────────────────────────────────────────────────────


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
        self.pages = pages
        self.owner_id = owner_id
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.btn_prev.disabled = self.index == 0
        self.btn_next.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=UI.error(
                    interaction.user, "Only the command author can use these controls."
                ),
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
    async def btn_prev(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.index -= 1
        await self._edit(interaction)

    @discord.ui.button(label=E_CLOSE, style=discord.ButtonStyle.secondary, row=0)
    async def btn_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(
            embed=UI.base("*Closed.*"),
            view=None,
        )

    @discord.ui.button(label=E_REFRESH, style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.pages = await self._rebuild_pages()
        self.index = min(self.index, len(self.pages) - 1)
        await self._edit(interaction)

    @discord.ui.button(label=E_NEXT, style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
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
        self.owner_id = owner_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(
        label="Confirm", style=discord.ButtonStyle.danger, emoji=E_CONFIRM, row=0
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        await interaction.response.edit_message(
            embed=UI.info(interaction.user, "Confirmed — processing…"), view=None
        )
        self.stop()

    @discord.ui.button(
        label="Cancel", style=discord.ButtonStyle.secondary, emoji=E_CANCEL, row=0
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = False
        await interaction.response.edit_message(
            embed=UI.info(interaction.user, "Cancelled."), view=None
        )
        self.stop()


# INPUT CONVERTERS & PARSERS


def parse_amount(raw: str, wallet: int) -> int | None:
    """
    Parse a bet/amount string.
    Accepts: integer, 'all', '1.5k', '2m', comma-formatted numbers.
    Returns None on invalid input.
    """
    cleaned = raw.strip().replace(",", "").replace("_", "")
    multiplier = 1

    if cleaned.lower() == "all":
        return wallet

    if cleaned.lower().endswith("k"):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    elif cleaned.lower().endswith("m"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]

    try:
        value = round(float(cleaned) * multiplier)
        return value if value != 0 else None
    except ValueError:
        return None


def format_remaining(delta) -> str:  # accepts timedelta
    """Format a timedelta as '2h 30m 15s'."""
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
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
