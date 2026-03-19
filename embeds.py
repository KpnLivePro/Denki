from __future__ import annotations

import math
import traceback
from datetime import datetime, timezone
from typing import Optional

import discord

import db

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
    except Exception:
        _cached_color = DEFAULT_COLOR


def get_color() -> int:
    return _cached_color


def set_color(hex_str: str) -> None:
    global _cached_color
    try:
        _cached_color = int(hex_str.strip().lstrip("#"), 16)
    except ValueError:
        _cached_color = DEFAULT_COLOR


# ── Streak helpers ────────────────────────────────────────────────────────────

def _streak_label(streak: int) -> str:
    """Return a milestone label for display, or empty string if no milestone."""
    if streak >= 30:
        return "🔥 **30-day streak!**  `2x bonus`"
    if streak >= 14:
        return "🔥 **14-day streak!**  `1.5x bonus`"
    if streak >= 7:
        return "🔥 **7-day streak!**   `1.25x bonus`"
    if streak >= 3:
        return "🔥 **3-day streak!**   `1.1x bonus`"
    return ""


def _next_milestone(streak: int) -> str:
    """Return a hint about the next streak milestone."""
    if streak < 3:
        return f"`{3 - streak}` more vote(s) for a **1.1x bonus**"
    if streak < 7:
        return f"`{7 - streak}` more vote(s) for a **1.25x bonus**"
    if streak < 14:
        return f"`{14 - streak}` more vote(s) for a **1.5x bonus**"
    if streak < 30:
        return f"`{30 - streak}` more vote(s) for a **2x bonus**"
    return "You're at the max streak bonus! 🎉"


class Embeds:
    """Central embed factory for Denki."""

    # ── Base ──────────────────────────────────────────────────────────────────

    @staticmethod
    def base(description: str, footer: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(description=description, color=get_color())
        if footer:
            embed.set_footer(text=footer)
        return embed

    # ── Feedback ──────────────────────────────────────────────────────────────

    @staticmethod
    def error(message: str) -> discord.Embed:
        return discord.Embed(description=f"> `❗` *{message}*", color=get_color())

    @staticmethod
    def success(message: str) -> discord.Embed:
        return discord.Embed(description=f"> `✅` *{message}*", color=get_color())

    @staticmethod
    def info(message: str) -> discord.Embed:
        return discord.Embed(description=f"> `ℹ️` *{message}*", color=get_color())

    @staticmethod
    def warn_msg(message: str) -> discord.Embed:
        return discord.Embed(description=f"> `⚠️` *{message}*", color=get_color())

    @staticmethod
    def critical(error: BaseException | str) -> discord.Embed:
        if isinstance(error, BaseException):
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            tb = str(error)
        return discord.Embed(
            description=f"> `‼️` *Critical error:*\n```\n{tb[:1800]}\n```",
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
        embed = discord.Embed(
            description=f"> `👤` *{user.display_name}'s wallet*",
            color=get_color(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="`💴` Pocket",      value=f"```¥{wallet:,}```",        inline=True)
        embed.add_field(name="`🏦` Server bank", value=f"```¥{bank_balance:,}```",  inline=True)
        embed.add_field(name="`📈` Invested",    value=f"```¥{bank_invested:,}```", inline=True)
        embed.set_footer(text=f"Season: {season_name}")
        return embed

    @staticmethod
    def daily(
        user: discord.User | discord.Member,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        embed = discord.Embed(description="> `📅` *Daily reward claimed!*", color=get_color())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="`💴` Earned",      value=f"```¥{amount:,}```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    @staticmethod
    def work(
        user: discord.User | discord.Member,
        job: str,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `💼` *You worked as a **{job}**!*",
            color=get_color(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="`💴` Earned",      value=f"```¥{amount:,}```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    @staticmethod
    def rob_success(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        stolen: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `🦹` *{robber.display_name} robbed {victim.display_name}!*",
            color=get_color(),
        )
        embed.add_field(name="`💴` Stolen", value=f"```¥{stolen:,}```", inline=True)
        return embed

    @staticmethod
    def rob_fail(
        robber: discord.User | discord.Member,
        victim: discord.User | discord.Member,
        fine: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `🚨` *{robber.display_name} was caught trying to rob {victim.display_name}!*",
            color=get_color(),
        )
        embed.add_field(name="`💸` Fine paid", value=f"```¥{fine:,}```", inline=True)
        return embed

    @staticmethod
    def pay(
        sender: discord.User | discord.Member,
        receiver: discord.User | discord.Member,
        amount: int,
    ) -> discord.Embed:
        return discord.Embed(
            description=f"> `💸` *{sender.display_name} sent ¥{amount:,} to {receiver.display_name}!*",
            color=get_color(),
        )

    @staticmethod
    def cooldown(command: str, remaining: str) -> discord.Embed:
        return discord.Embed(
            description=f"> `⏳` *{command} is on cooldown — try again in `{remaining}`.*",
            color=get_color(),
        )

    # ── Vote ──────────────────────────────────────────────────────────────────

    @staticmethod
    def vote_prompt(vote_url: str, current_streak: int = 0) -> discord.Embed:
        if current_streak > 0:
            streak_line = f"> 🔥 Current streak: `{current_streak}` day(s)  ·  {_next_milestone(current_streak)}\n"
        else:
            streak_line = ""
        return discord.Embed(
            description=(
                f"> `🗳️` *You haven't voted yet!*\n\n"
                f"> [**Click here to vote for Denki**]({vote_url})\n"
                f"> Then run `/vote` again to claim your reward.\n\n"
                f"{streak_line}"
                f"> Base: `¥2,000`  ·  Weekend: `¥4,000`  ·  Streak bonuses apply\n"
                f"> Cooldown: **12 hours**"
            ),
            color=get_color(),
        )

    @staticmethod
    def vote_cooldown(remaining: str, vote_url: str) -> discord.Embed:
        return discord.Embed(
            description=(
                f"> `⏳` *You already claimed your vote reward.*\n\n"
                f"> Next claim available in `{remaining}`\n"
                f"> [Vote again early]({vote_url}) — reward waits until your cooldown expires."
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
        weekend_note = "  ·  `2x weekend bonus!` 🎉" if is_weekend else ""
        milestone    = _streak_label(streak)
        next_hint    = _next_milestone(streak)

        desc = f"> `🗳️` *Thanks for voting!{weekend_note}*"
        if milestone:
            desc += f"\n> {milestone}"

        embed = discord.Embed(description=desc, color=get_color())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="`💴` Reward",      value=f"```¥{amount:,}```",     inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```",     inline=True)
        embed.add_field(name="`🔥` Vote streak", value=f"```{streak} day(s)```", inline=True)
        embed.set_footer(text=f"{next_hint}  ·  Vote again in 12h")
        return embed

    # ── Gambling ──────────────────────────────────────────────────────────────

    @staticmethod
    def coinflip(
        choice: str,
        result: str,
        won: bool,
        amount: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = "`✅` *You won!*" if won else "`❗` *You lost!*"
        embed   = discord.Embed(
            description=f"> `🪙` *Coinflip — {outcome}*",
            color=get_color(),
        )
        embed.add_field(name="`🎯` Your call",   value=f"```{choice}```",    inline=True)
        embed.add_field(name="`🪙` Result",      value=f"```{result}```",    inline=True)
        embed.add_field(name="`💴` Bet",         value=f"```¥{amount:,}```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    @staticmethod
    def slots(
        reels: list[str],
        won: bool,
        multiplier: float,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"`✅` *You won ¥{payout:,}!*" if won else "`❗` *No match — you lost!*"
        embed   = discord.Embed(
            description=f"> `🎰` *Slots — {outcome}*",
            color=get_color(),
        )
        embed.add_field(name="`🎰` Reels", value=f"```{'  '.join(reels)}```", inline=False)
        embed.add_field(name="`💴` Bet",   value=f"```¥{amount:,}```",        inline=True)
        if won:
            embed.add_field(name="`✖️` Multiplier", value=f"```{multiplier}x```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    @staticmethod
    def blackjack_start(
        player_hand: list[str],
        dealer_card: str,
        player_total: int,
        amount: int,
    ) -> discord.Embed:
        embed = discord.Embed(description="> `🃏` *Blackjack — your turn*", color=get_color())
        embed.add_field(
            name=f"`🧑` Your hand ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        embed.add_field(name="`🤖` Dealer shows", value=f"```{dealer_card}  🂠```", inline=False)
        embed.add_field(name="`💴` Bet",           value=f"```¥{amount:,}```",      inline=True)
        embed.set_footer(text="Use the buttons to Hit or Stand")
        return embed

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
        embed = discord.Embed(
            description=f"> `🃏` *Blackjack — `{result}`*",
            color=get_color(),
        )
        embed.add_field(
            name=f"`🧑` Your hand ({player_total})",
            value=f"```{'  '.join(player_hand)}```",
            inline=False,
        )
        embed.add_field(
            name=f"`🤖` Dealer hand ({dealer_total})",
            value=f"```{'  '.join(dealer_hand)}```",
            inline=False,
        )
        embed.add_field(name="`💴` Bet",         value=f"```¥{amount:,}```", inline=True)
        embed.add_field(name="`💰` Payout",      value=f"```¥{payout:,}```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    @staticmethod
    def guess(
        mode: str,
        answer: str,
        won: bool,
        amount: int,
        payout: int,
        wallet: int,
    ) -> discord.Embed:
        outcome = f"`✅` *Correct — you won ¥{payout:,}!*" if won else f"`❗` *Wrong — the answer was `{answer}`!*"
        embed   = discord.Embed(
            description=f"> `🎲` *Guess ({mode}) — {outcome}*",
            color=get_color(),
        )
        embed.add_field(name="`💴` Bet",         value=f"```¥{amount:,}```", inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```", inline=True)
        return embed

    # ── Investing ─────────────────────────────────────────────────────────────

    @staticmethod
    def invest(
        user: discord.User | discord.Member,
        amount: int,
        total_invested: int,
        vault_total: int,
        season_name: str,
    ) -> discord.Embed:
        embed = discord.Embed(description="> `📈` *Investment placed!*", color=get_color())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="`💴` Invested",    value=f"```¥{amount:,}```",         inline=True)
        embed.add_field(name="`📊` Your total",  value=f"```¥{total_invested:,}```", inline=True)
        embed.add_field(name="`🏛️` Vault total", value=f"```¥{vault_total:,}```",    inline=True)
        embed.set_footer(text=f"Season: {season_name}")
        return embed

    @staticmethod
    def vault(
        guild_name: str,
        season_name: str,
        days_remaining: int,
        vault_total: int,
        top_investors: list[dict],
    ) -> discord.Embed:
        embed  = discord.Embed(
            description=f"> `🏛️` *{guild_name} — Season Vault*",
            color=get_color(),
        )
        embed.add_field(name="`💰` Total pooled",   value=f"```¥{vault_total:,}```", inline=True)
        embed.add_field(name="`📅` Days remaining", value=f"```{days_remaining}```",  inline=True)
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
        lines: list[str] = []
        for i, row in enumerate(top_investors):
            medal = medals[i] if i < len(medals) else f"`#{i + 1}`"
            lines.append(f"{medal} <@{row['user_id']}> — `¥{int(row['invested']):,}`")
        if lines:
            embed.add_field(name="`🏆` Top investors", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Season: {season_name}")
        return embed

    # ── Season ────────────────────────────────────────────────────────────────

    @staticmethod
    def season_info(season: dict, vault_total: int) -> discord.Embed:
        end = datetime.fromisoformat(season["end"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = max(0, math.ceil((end - datetime.now(timezone.utc)).total_seconds() / 86400))
        embed = discord.Embed(
            description=f"> `🌸` *Season: **{season['name']}***",
            color=get_color(),
        )
        embed.add_field(name="`📅` Days left",   value=f"```{days_left}```",            inline=True)
        embed.add_field(name="`🏛️` Vault total", value=f"```¥{vault_total:,}```",       inline=True)
        embed.add_field(name="`🗓️` Ends",        value=f"<t:{int(end.timestamp())}:F>", inline=False)
        return embed

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
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
        lines: list[str] = []
        for i, row in enumerate(rows):
            medal = medals[i] if i < len(medals) else f"`#{i + 1}`"
            uid   = int(row["user_id"])
            name  = name_map.get(uid, f"User {uid}")
            val   = int(row.get(value_key, 0))
            lines.append(f"{medal} **{name}** — `{value_prefix}{val:,}`")
        body  = "\n".join(lines) if lines else "*No data yet.*"
        embed = discord.Embed(
            description=f"> `🏆` *{title}*\n\n{body}",
            color=get_color(),
        )
        if season_name:
            embed.set_footer(text=f"Season: {season_name}")
        return embed

    # ── Shop ──────────────────────────────────────────────────────────────────

    @staticmethod
    def shop(
        guild_name: str,
        server_items: list[dict],
        global_items: list[dict],
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `🏪` *{guild_name} Shop*",
            color=get_color(),
        )
        if server_items:
            lines: list[str] = []
            for item in server_items:
                desc = item.get("description") or "No description"
                lines.append(f"`{item['item_id']}` **{item['name']}** — `¥{item['price']:,}`\n> *{desc}*")
            embed.add_field(name="`🏠` Server items", value="\n".join(lines), inline=False)
        if global_items:
            lines = []
            for item in global_items:
                desc = item.get("description") or "No description"
                lines.append(f"`{item['item_id']}` **{item['name']}** — `¥{item['price']:,}`\n> *{desc}*")
            embed.add_field(name="`🌐` Global items", value="\n".join(lines), inline=False)
        if not server_items and not global_items:
            embed.add_field(name="Empty", value="> *No items available.*", inline=False)
        return embed

    @staticmethod
    def purchase(item_name: str, price: int, wallet: int) -> discord.Embed:
        embed = discord.Embed(description="> `🛍️` *Purchase successful!*", color=get_color())
        embed.add_field(name="`📦` Item",        value=f"```{item_name}```",  inline=True)
        embed.add_field(name="`💸` Paid",        value=f"```¥{price:,}```",   inline=True)
        embed.add_field(name="`👛` New balance", value=f"```¥{wallet:,}```",  inline=True)
        return embed

    @staticmethod
    def inventory(
        user: discord.User | discord.Member,
        items: list[dict],
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `🎒` *{user.display_name}'s inventory*",
            color=get_color(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        if not items:
            embed.add_field(name="Empty", value="> *No items yet.*", inline=False)
        else:
            for item in items:
                shop = item.get("shopitems") or {}
                embed.add_field(
                    name=f"`📦` {shop.get('name', 'Unknown')}",
                    value=f"> *{shop.get('description') or 'No description'}*\n> Type: `{shop.get('type', '?')}`",
                    inline=False,
                )
        return embed

    # ── Moderation ────────────────────────────────────────────────────────────

    @staticmethod
    def warn_issued(
        user: discord.User | discord.Member,
        reason: str,
        warn_count: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `⚠️` *Warning issued to **{user.display_name}***",
            color=get_color(),
        )
        embed.add_field(name="`📋` Reason",     value=f"```{reason}```",         inline=False)
        embed.add_field(name="`🔢` Warn count", value=f"```{warn_count} / 3```", inline=True)
        if warn_count >= 3:
            embed.add_field(
                name="`🔨` Status",
                value="> *3 warnings reached — user has been auto-banned.*",
                inline=False,
            )
        return embed

    @staticmethod
    def warn_dm(reason: str, warn_count: int) -> discord.Embed:
        embed = discord.Embed(
            description="> `⚠️` *You have received a Denki warning.*",
            color=get_color(),
        )
        embed.add_field(name="`📋` Reason",   value=f"```{reason}```",         inline=False)
        embed.add_field(name="`🔢` Warnings", value=f"```{warn_count} / 3```", inline=True)
        embed.set_footer(text="Three warnings results in a permanent ban from Denki.")
        return embed

    @staticmethod
    def ban_dm(reason: str) -> discord.Embed:
        return discord.Embed(
            description=(
                "> `🔨` *You have been permanently banned from Denki.*\n"
                f"> `📋` Reason: `{reason}`\n"
                "> *If you believe this is a mistake, contact the bot owner.*"
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
        embed = discord.Embed(description="> `📋` *New report filed*", color=get_color())
        embed.add_field(name="`👤` Reported",       value=f"```{reported} ({reported.id})```", inline=False)
        embed.add_field(name="`🏠` Server",         value=f"```{guild_name}```",               inline=True)
        embed.add_field(name="`👮` Reporter",       value=f"```{reporter} ({reporter.id})```", inline=True)
        embed.add_field(name="`📋` Reason",         value=f"```{reason}```",                   inline=False)
        embed.add_field(name="`👛` Wallet at time", value=f"```¥{wallet_snap:,}```",           inline=True)
        embed.set_footer(text=f"Use  !d warn {reported.id} <reason>  or  !d ban {reported.id} <reason>")
        return embed

    # ── Notifications ─────────────────────────────────────────────────────────

    @staticmethod
    def season_start(season: dict) -> discord.Embed:
        end_ts_raw = datetime.fromisoformat(season["end"])
        if end_ts_raw.tzinfo is None:
            end_ts_raw = end_ts_raw.replace(tzinfo=timezone.utc)
        embed = discord.Embed(
            description=f"> `🌸` *A new season has begun — **{season['name']}***",
            color=get_color(),
        )
        embed.add_field(name="`🗓️` Ends", value=f"<t:{int(end_ts_raw.timestamp())}:F>", inline=True)
        embed.set_footer(text="Invest in the vault to compete for season bonuses.")
        return embed

    @staticmethod
    def season_end(
        season: dict,
        top_investors: list[dict],
        name_map: dict[int, str],
        bonuses: dict[int, int],
    ) -> discord.Embed:
        medals = ["🥇", "🥈", "🥉"]
        lines: list[str] = []
        for i, row in enumerate(top_investors[:3]):
            uid   = int(row["user_id"])
            name  = name_map.get(uid, f"User {uid}")
            bonus = bonuses.get(uid, 0)
            medal = medals[i] if i < len(medals) else f"`#{i + 1}`"
            lines.append(
                f"{medal} **{name}** — invested `¥{int(row['invested']):,}` — bonus `¥{bonus:,}`"
            )
        embed = discord.Embed(
            description=f"> `🏁` *Season **{season['name']}** has ended!*",
            color=get_color(),
        )
        if lines:
            embed.add_field(name="`🏆` Top 3 investors", value="\n".join(lines), inline=False)
        embed.set_footer(text="Season bonuses have been paid to wallets. A new season begins shortly.")
        return embed

    # ── Help ──────────────────────────────────────────────────────────────────

    @staticmethod
    def help_home() -> discord.Embed:
        embed = discord.Embed(
            description=(
                "> `⚡` *Welcome to **Denki** — the global Discord economy bot.*\n\n"
                "> Earn, gamble, invest and compete using **¥ Yen** across every server.\n"
                "> Your wallet is **global** — one balance, all servers.\n"
                "> Every server runs a **30-day season** where you invest to win bonuses.\n\n"
                "> `ℹ️` *Use `/help [module]` to view all commands in a module.*\n"
                "> `ℹ️` *Use `/help [command]` to look up a specific command.*\n\n"
                "> **Modules**\n"
                "> `economy`  `gambling`  `investing`  `season`\n"
                "> `shop`  `leaderboard`  `admin`  `tea`"
            ),
            color=get_color(),
        )
        embed.set_footer(text="Prefix: !d  ·  Slash: /  ·  Hybrid commands support both")
        return embed

    @staticmethod
    def help_module(module: str, commands: list[dict]) -> discord.Embed:
        lines: list[str] = []
        for cmd in commands:
            aliases = "  ".join(f"`{a}`" for a in cmd.get("aliases", []))
            line    = f"**{cmd['name']}** `{cmd['usage']}`"
            if aliases:
                line += f"  ·  aliases: {aliases}"
            line += f"\n> *{cmd['description']}*"
            lines.append(line)
        embed = discord.Embed(
            description=f"> `📖` *Module: **{module}***\n\n" + "\n\n".join(lines),
            color=get_color(),
        )
        embed.set_footer(text="<required>  [optional]  ·  Prefix: !d  ·  Slash: /")
        return embed

    @staticmethod
    def help_command(
        name: str,
        aliases: list[str],
        usage: str,
        description: str,
        examples: list[str],
        notes: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            description=f"> `📖` *Command: **{name}***\n> *{description}*",
            color=get_color(),
        )
        embed.add_field(name="`📝` Usage", value=f"```{usage}```", inline=False)
        if aliases:
            embed.add_field(
                name="`🔀` Aliases",
                value="  ".join(f"`{a}`" for a in aliases),
                inline=False,
            )
        if examples:
            embed.add_field(
                name="`💡` Examples",
                value="\n".join(f"> `{e}`" for e in examples),
                inline=False,
            )
        if notes:
            embed.add_field(name="`ℹ️` Notes", value=f"> *{notes}*", inline=False)
        embed.set_footer(text="<required>  [optional]  ·  Prefix: !d  ·  Slash: /")
        return embed


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginatorView(discord.ui.View):
    """Generic reusable paginator. Buttons: «  ✕  ↺  »"""

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
                embed=Embeds.error("Only the command author can use these controls."),
                ephemeral=True,
            )
            return False
        return True

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def _rebuild_pages(self) -> list[discord.Embed]:
        return self.pages

    @discord.ui.button(label="«", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index -= 1
        await self._edit(interaction)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.secondary)
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="↺", style=discord.ButtonStyle.secondary)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pages = await self._rebuild_pages()
        self.index = min(self.index, len(self.pages) - 1)
        await self._edit(interaction)

    @discord.ui.button(label="»", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index += 1
        await self._edit(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True