from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.tea")

# ── APIs ──────────────────────────────────────────────────────────────────────

DATAMUSE_API   = "https://api.datamuse.com/words?sp={pattern}&max=100"
DICTIONARY_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"

WORD_LENGTHS = [4, 5, 6, 7]

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_PLAYERS        = 24
MIN_PLAYERS        = 2
LOBBY_TIMEOUT      = 300
MAX_LIVES          = 3
GREEN_ROUNDS       = 10
MAX_ROUNDS         = 50          # safety cap — prevents runaway games
MAX_FETCH_FAILURES = 3           # consecutive word-fetch failures before abort

GREEN_POINTS_FIRST  = 10
GREEN_POINTS_SECOND = 7
GREEN_POINTS_THIRD  = 5
GREEN_POINTS_REST   = 2

TEA_META = {
    "black": {"emoji": "🍵", "color": "Black", "desc": "Contain all given letters in your word — last standing wins"},
    "green": {"emoji": "🍃", "color": "Green", "desc": "Fastest valid answer each round scores points — top 3 win"},
    "white": {"emoji": "🤍", "color": "White", "desc": "Fill in the missing letters — last standing wins"},
    "red":   {"emoji": "🔴", "color": "Red",   "desc": "Unscramble the letters into any valid word — last standing wins"},
    "blue":  {"emoji": "💙", "color": "Blue",  "desc": "Guess the word from an example sentence — last standing wins"},
}

_active_games: dict[int, "TeaGame"] = {}
_active_users: dict[int, int] = {}


# ── API helpers ───────────────────────────────────────────────────────────────

async def fetch_random_word(length: int | None = None) -> str | None:
    lengths_to_try = [length] if length else random.sample(WORD_LENGTHS, len(WORD_LENGTHS))
    for l in lengths_to_try:
        try:
            pattern = "?" * l
            url = DATAMUSE_API.format(pattern=pattern)
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        words = [
                            item["word"].lower().strip()
                            for item in data
                            if isinstance(item, dict)
                            and item.get("word")
                            and item["word"].isalpha()
                            and len(item["word"]) == l
                        ]
                        if words:
                            return random.choice(words)
        except Exception as e:
            logger.error("fetch_random_word(length=%d): %s", l, e)
    return None


async def fetch_word_data(word: str) -> dict | None:
    try:
        url = DICTIONARY_API.format(word=word.lower())
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                if r.status == 200:
                    data = await r.json()
                    if isinstance(data, list) and data:
                        return dict(data[0])
    except Exception as e:
        logger.error("fetch_word_data(%s): %s", word, e)
    return None


async def validate_word(word: str) -> bool:
    return (await fetch_word_data(word)) is not None


def get_example(word_data: dict, word: str) -> str | None:
    for meaning in word_data.get("meanings", []):
        for defn in meaning.get("definitions", []):
            ex = defn.get("example", "")
            if ex and word.lower() in ex.lower():
                return ex.replace(word, "___").replace(word.capitalize(), "___")
    return None


def scramble(word: str) -> str:
    letters = list(word.upper())
    for _ in range(10):
        random.shuffle(letters)
        if "".join(letters).lower() != word:
            break
    return "  ".join(letters)


def make_fill(word: str) -> str:
    indices = list(range(len(word)))
    # Hide at least half but always reveal at least 1 letter
    n_hidden = max(1, min(len(word) - 1, len(word) // 2))
    hidden = set(random.sample(indices, n_hidden))
    return "  ".join("_" if i in hidden else c.upper() for i, c in enumerate(word))


# ── Player ────────────────────────────────────────────────────────────────────

@dataclass
class TeaPlayer:
    member:      discord.Member
    bet:         int
    lives:       int   = MAX_LIVES
    points:      int   = 0
    answered:    bool  = False
    answer:      str   = ""
    valid:       bool  = False
    answer_time: float = 0.0

    @property
    def alive(self) -> bool:
        return self.lives > 0

    @property
    def hearts(self) -> str:
        return "❤️" * self.lives + "🖤" * (MAX_LIVES - self.lives)

    def lose_life(self) -> None:
        if self.lives > 0:
            self.lives -= 1


# ── Game ──────────────────────────────────────────────────────────────────────

class TeaGame:
    def __init__(
        self,
        channel: discord.TextChannel,
        host: discord.Member,
        tea_type: str,
        min_bet: int,
        max_players: int,
        time_limit: int,
    ) -> None:
        self.channel     = channel
        self.host        = host
        self.tea_type    = tea_type
        self.min_bet     = min_bet
        self.max_players = max_players
        self.time_limit  = time_limit
        self.players:    list[TeaPlayer] = []
        self.used_words: set[str]        = set()
        self.round       = 0
        self.lobby_msg:  discord.Message | None = None
        self.current_word             = ""
        self.current_challenge_letters: list[str] = []  # FIX: stored per-round
        self.started     = False
        self.finished    = False
        self._fetch_failures = 0

    @property
    def pot(self) -> int:
        return sum(p.bet for p in self.players)

    @property
    def alive_players(self) -> list[TeaPlayer]:
        return [p for p in self.players if p.alive]

    def get_player(self, uid: int) -> TeaPlayer | None:
        return next((p for p in self.players if p.member.id == uid), None)

    def meta(self) -> dict:
        return TEA_META[self.tea_type]

    def lobby_embed(self) -> discord.Embed:
        m = self.meta()
        player_lines = (
            "\n".join(f"> {p.member.display_name} — `¥{p.bet:,}`" for p in self.players)
            if self.players else "> *No players yet — be the first to join!*"
        )
        embed = Embeds.base(
            f"> `{m['emoji']}` *{m['color']} Tea — {m['desc']}*\n\n"
            f"> Min bet: `¥{self.min_bet:,}`  •  Players: `{len(self.players)}/{self.max_players}`"
            f"  •  `{self.time_limit}s` per round\n\n"
            + player_lines
        )
        embed.set_footer(text=f"Host: {self.host.display_name}  •  Starts when host clicks Start or {self.max_players} players join")
        return embed

    def round_embed(self, challenge: str, hint: str) -> discord.Embed:
        m = self.meta()
        is_green = self.tea_type == "green"
        lines = []
        for p in (self.players if is_green else self.alive_players):
            status = "⌛" if not p.answered else ("✅" if p.valid else "❌")
            suffix = f"  {p.hearts}" if not is_green else f"  `{p.points}pts`"
            lines.append(f"> {status} {p.member.display_name}{suffix}")
        embed = Embeds.base(
            f"> `{m['emoji']}` *{m['color']} Tea — Round {self.round}*\n\n"
            f"> **{challenge}**\n"
            f"> *{hint}*\n\n"
            + "\n".join(lines)
        )
        embed.set_footer(text=f"Type your answer here  •  {self.time_limit}s  •  Pot: ¥{self.pot:,}")
        return embed

    def results_embed(self, results: list[tuple[TeaPlayer, bool, str]]) -> discord.Embed:
        m = self.meta()
        lines = []
        for p, valid, ans in results:
            icon   = "✅" if valid else "❌"
            shown  = f"`{ans}`" if ans else "*no answer*"
            suffix = p.hearts if self.tea_type != "green" else f"`{p.points}pts`"
            lines.append(f"> {icon} {p.member.display_name} — {shown}  {suffix}")
        embed = Embeds.base(
            f"> `{m['emoji']}` *Round {self.round} Results*\n\n"
            + "\n".join(lines)
            + f"\n\n> Answer: `{self.current_word}`"
        )
        embed.set_footer(text=f"Pot: ¥{self.pot:,}")
        return embed


# ── Lobby UI ──────────────────────────────────────────────────────────────────

class LobbyView(discord.ui.View):
    def __init__(self, game: TeaGame, bot: commands.Bot) -> None:
        super().__init__(timeout=LOBBY_TIMEOUT)
        self.game = game
        self.bot  = bot

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success, emoji="🍵")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        g = self.game
        if g.started:
            return await interaction.response.send_message(embed=Embeds.error("Game already started."), ephemeral=True)
        if len(g.players) >= g.max_players:
            return await interaction.response.send_message(embed=Embeds.error("Game is full."), ephemeral=True)
        if g.get_player(interaction.user.id):
            return await interaction.response.send_message(embed=Embeds.error("You already joined."), ephemeral=True)
        if interaction.user.id in _active_users:
            return await interaction.response.send_message(embed=Embeds.error("You're already in an active game."), ephemeral=True)
        await interaction.response.send_modal(JoinModal(game=g, lobby_view=self))

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.host.id:
            return await interaction.response.send_message(embed=Embeds.error("Only the host can start."), ephemeral=True)
        if len(self.game.players) < MIN_PLAYERS:
            return await interaction.response.send_message(embed=Embeds.error(f"Need at least {MIN_PLAYERS} players."), ephemeral=True)
        await interaction.response.defer()
        self.stop()
        asyncio.create_task(run_game(self.game, self.bot))

    async def on_timeout(self) -> None:
        if not self.game.started:
            await _cancel_game(self.game, "Lobby timed out.")


class JoinModal(discord.ui.Modal, title="Join Tea Game"):
    bet_input = discord.ui.TextInput(label="Your bet (¥)", placeholder="e.g. 500", min_length=1, max_length=10)

    def __init__(self, game: TeaGame, lobby_view: LobbyView) -> None:
        super().__init__()
        self.game       = game
        self.lobby_view = lobby_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            bet = int(self.bet_input.value.strip().replace(",", "").replace("¥", ""))
        except ValueError:
            return await interaction.response.send_message(embed=Embeds.error("Invalid amount."), ephemeral=True)

        if bet < self.game.min_bet:
            return await interaction.response.send_message(embed=Embeds.error(f"Minimum bet is ¥{self.game.min_bet:,}."), ephemeral=True)

        user_data = await db.get_or_create_user(interaction.user.id)
        if int(user_data["wallet"]) < bet:
            return await interaction.response.send_message(embed=Embeds.error(f"Insufficient funds. Wallet: ¥{int(user_data['wallet']):,}."), ephemeral=True)

        await db.update_wallet(interaction.user.id, -bet)

        guild  = interaction.guild
        member = (guild.get_member(interaction.user.id) if guild else None) or interaction.user  # type: ignore[arg-type]
        self.game.players.append(TeaPlayer(member=member, bet=bet))  # type: ignore[arg-type]
        _active_users[interaction.user.id] = self.game.channel.id

        if self.game.lobby_msg:
            try:
                await self.game.lobby_msg.edit(embed=self.game.lobby_embed(), view=self.lobby_view)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(embed=Embeds.success(f"Joined with bet ¥{bet:,}!"), ephemeral=True)

        if len(self.game.players) >= self.game.max_players:
            self.lobby_view.stop()
            asyncio.create_task(run_game(self.game, self.lobby_view.bot))


# ── Game runner ───────────────────────────────────────────────────────────────

async def run_game(game: TeaGame, bot: commands.Bot) -> None:
    game.started = True
    if game.lobby_msg:
        try:
            await game.lobby_msg.edit(
                embed=Embeds.base(f"> `{game.meta()['emoji']}` *{game.meta()['color']} Tea starting with {len(game.players)} players!*"),
                view=None,
            )
        except discord.HTTPException:
            pass

    await asyncio.sleep(2)

    is_green = game.tea_type == "green"

    while game.round < MAX_ROUNDS:
        # End conditions
        if is_green and game.round >= GREEN_ROUNDS:
            break
        if not is_green and len(game.alive_players) <= 1:
            break

        game.round += 1

        # Fetch word — up to 3 attempts per round
        word = None
        for _ in range(3):
            word = await _fetch_word(game)
            if word:
                break
            await asyncio.sleep(1)

        if not word:
            game._fetch_failures += 1
            logger.error("tea: word fetch failed (consecutive=%d) game=%d type=%s",
                         game._fetch_failures, game.channel.id, game.tea_type)
            if game._fetch_failures >= MAX_FETCH_FAILURES:
                await _cancel_game(game, "Word API unavailable — couldn't fetch words for 3 rounds in a row.")
                return
            try:
                await game.channel.send(embed=Embeds.error(
                    f"Couldn't fetch a word — skipping round. "
                    f"({game._fetch_failures}/{MAX_FETCH_FAILURES} before auto-cancel)"
                ))
            except discord.HTTPException:
                pass
            await asyncio.sleep(2)
            continue

        game._fetch_failures = 0
        game.current_word = word
        game.used_words.add(word)

        # Reset answers
        for p in (game.players if is_green else game.alive_players):
            p.answered    = False
            p.answer      = ""
            p.valid       = False
            p.answer_time = 0.0

        # Build challenge — also stores challenge letters on game object
        challenge, hint = await _build_challenge(game, word)

        try:
            round_msg = await game.channel.send(embed=game.round_embed(challenge, hint))
        except discord.Forbidden:
            await _cancel_game(game, "Lost send permissions.")
            return
        except discord.HTTPException as e:
            logger.error("tea: round embed send failed: %s", e)
            await _cancel_game(game, "Network error — bets refunded.")
            return

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        await _collect_answers(game, bot, start_time)

        results = await _score_round(game, word, is_green)

        try:
            await round_msg.edit(embed=game.round_embed(challenge, hint))
        except discord.HTTPException:
            pass

        try:
            await game.channel.send(embed=game.results_embed(results))
        except discord.HTTPException:
            pass

        if not is_green:
            eliminated = [p for p in game.alive_players if p.lives == 0]
            if eliminated:
                names = ", ".join(p.member.display_name for p in eliminated)
                try:
                    await game.channel.send(embed=Embeds.base(
                        f"> `💀` *{names} {'has' if len(eliminated) == 1 else 'have'} been eliminated!*"
                    ))
                except discord.HTTPException:
                    pass

        await asyncio.sleep(3)

    await _end_game(game, is_green)


async def _fetch_word(game: TeaGame) -> str | None:
    for _ in range(5):
        word = await fetch_random_word()
        if not word or word in game.used_words:
            continue
        if game.tea_type == "blue":
            data = await fetch_word_data(word)
            if not data or not get_example(data, word):
                continue
        return word
    return None


async def _build_challenge(game: TeaGame, word: str) -> tuple[str, str]:
    """
    Build the round challenge and store the revealed letters on game.current_challenge_letters
    so _score_round can validate against what players were actually shown.
    """
    if game.tea_type in ("black", "green"):
        letters = random.sample(list(set(word.upper())), min(3, len(set(word))))
        game.current_challenge_letters = [l.lower() for l in letters]
        challenge = "  ".join(letters)
        if game.tea_type == "black":
            hint = f"Form any valid English word containing all these letters  •  {len(word)} letter target"
        else:
            hint = "Form any valid English word containing all these letters — fastest wins points!"
        return challenge, hint

    elif game.tea_type == "white":
        game.current_challenge_letters = []
        challenge = make_fill(word)
        hint = "Fill in the missing letters"
        return challenge, hint

    elif game.tea_type == "red":
        game.current_challenge_letters = []
        challenge = scramble(word)
        hint = f"Unscramble these letters into any valid word  •  {len(word)} letters"
        return challenge, hint

    else:  # blue
        game.current_challenge_letters = []
        data = await fetch_word_data(word)
        if data:
            ex = get_example(data, word)
            if ex:
                return ex, f"Guess the missing word  •  {len(word)} letters"
        # Fallback: skip this round rather than showing an unplayable prompt
        return f"*___ ({len(word)} letters)*", "Guess the word"


async def _collect_answers(game: TeaGame, bot: commands.Bot, start_time: float) -> None:
    is_green   = game.tea_type == "green"
    target_set = {p.member.id for p in (game.players if is_green else game.alive_players)}
    pending    = set(target_set)

    def check(msg: discord.Message) -> bool:
        return msg.channel.id == game.channel.id and msg.author.id in target_set and not msg.author.bot

    loop     = asyncio.get_running_loop()
    deadline = start_time + game.time_limit

    while pending and loop.time() < deadline:
        remaining = deadline - loop.time()
        try:
            msg = await bot.wait_for("message", check=check, timeout=max(0.1, remaining))
            player = game.get_player(msg.author.id)
            if player and not player.answered:
                player.answered    = True
                player.answer      = msg.content.strip().lower()
                player.answer_time = loop.time() - start_time
                pending.discard(msg.author.id)
                try:
                    await msg.add_reaction("📝")
                except Exception:
                    pass
        except asyncio.TimeoutError:
            break


async def _score_round(
    game: TeaGame,
    word: str,
    is_green: bool,
) -> list[tuple[TeaPlayer, bool, str]]:
    results: list[tuple[TeaPlayer, bool, str]] = []
    pool = game.players if is_green else game.alive_players

    for player in pool:
        answer = player.answer.strip().lower()

        if not answer:
            player.valid = False
            if not is_green:
                player.lose_life()
            results.append((player, False, ""))
            continue

        if game.tea_type in ("black", "green"):
            # Validate against the letters that were SHOWN, not all letters in the word
            shown_letters = game.current_challenge_letters
            contains_all  = all(l in answer for l in shown_letters)
            valid = contains_all and len(answer) >= 3 and await validate_word(answer)

        elif game.tea_type in ("white", "blue"):
            valid = answer == word.lower()

        else:  # red
            valid = sorted(answer) == sorted(word.lower()) and await validate_word(answer)

        player.valid = valid
        if not valid and not is_green:
            player.lose_life()

        results.append((player, valid, answer))

    # Green tea: award points by speed rank
    if is_green:
        winners = sorted(
            [r for r in results if r[1]],
            key=lambda r: r[0].answer_time,
        )
        point_map = [GREEN_POINTS_FIRST, GREEN_POINTS_SECOND, GREEN_POINTS_THIRD]
        for i, (player, _, _) in enumerate(winners):
            player.points += point_map[i] if i < 3 else GREEN_POINTS_REST

    return results


async def _end_game(game: TeaGame, is_green: bool) -> None:
    pot = game.pot
    m   = game.meta()

    if is_green:
        ranked = sorted(game.players, key=lambda p: p.points, reverse=True)
        if not ranked:
            await _refund_all(game)
            return

        winner = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        third  = ranked[2] if len(ranked) > 2 else None

        refunded: set[int] = set()
        if second:
            await db.update_wallet(second.member.id, second.bet)
            await db.log_transaction(0, second.member.id, second.bet, "greentea_refund")
            refunded.add(second.member.id)
        if third:
            await db.update_wallet(third.member.id, third.bet)
            await db.log_transaction(0, third.member.id, third.bet, "greentea_refund")
            refunded.add(third.member.id)

        await db.update_wallet(winner.member.id, pot)
        await db.log_transaction(0, winner.member.id, pot, "greentea_win")
        for p in game.players:
            if p.member.id != winner.member.id and p.member.id not in refunded:
                await db.log_transaction(p.member.id, 0, p.bet, "greentea_loss")

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, p in enumerate(ranked[:3]):
            note = f"wins `¥{pot:,}`" if i == 0 else f"bet refunded `¥{p.bet:,}`"
            lines.append(f"> {medals[i]} **{p.member.display_name}** — `{p.points}pts`  •  {note}")

        embed = Embeds.base(f"> `{m['emoji']}` *Green Tea — Game Over!*\n\n" + "\n".join(lines))

    else:
        alive = game.alive_players
        if not alive:
            await _refund_all(game)
            return

        if len(alive) == 1:
            winner = alive[0]
            await db.update_wallet(winner.member.id, pot)
            await db.log_transaction(0, winner.member.id, pot, "tea_win")
            for p in game.players:
                if p.member.id != winner.member.id:
                    await db.log_transaction(p.member.id, 0, p.bet, "tea_loss")
            embed = Embeds.base(
                f"> `{m['emoji']}` *{m['color']} Tea — {winner.member.display_name} wins!*\n\n"
                f"> Prize: `¥{pot:,}`  •  Rounds: `{game.round}`"
            )
        else:
            # Tie — split proportionally by bet
            total_bets = sum(p.bet for p in alive)
            lines = []
            for p in alive:
                share = int(pot * p.bet / total_bets)
                await db.update_wallet(p.member.id, share)
                await db.log_transaction(0, p.member.id, share, "tea_win")
                lines.append(f"> 🏆 {p.member.display_name} — `¥{share:,}`")
            embed = Embeds.base(
                f"> `{m['emoji']}` *{m['color']} Tea ends in a tie!*\n\n" + "\n".join(lines)
            )

    game.finished = True
    try:
        await game.channel.send(embed=embed)
    except discord.HTTPException:
        pass
    await _cleanup(game)


async def _refund_all(game: TeaGame) -> None:
    for p in game.players:
        await db.update_wallet(p.member.id, p.bet)
    try:
        await game.channel.send(embed=Embeds.base(
            f"> `{game.meta()['emoji']}` *Everyone was eliminated — all bets refunded.*"
        ))
    except discord.HTTPException:
        pass
    await _cleanup(game)


async def _cancel_game(game: TeaGame, reason: str) -> None:
    for p in game.players:
        await db.update_wallet(p.member.id, p.bet)
    try:
        await game.channel.send(embed=Embeds.base(
            f"> `❌` *Tea cancelled — {reason} All bets refunded.*"
        ))
    except discord.HTTPException:
        pass
    await _cleanup(game)


async def _cleanup(game: TeaGame) -> None:
    _active_games.pop(game.channel.id, None)
    for p in game.players:
        _active_users.pop(p.member.id, None)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Tea(commands.Cog):
    """Tea word games — black, green, white, red, blue."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tea", description="Start a Tea word game in this channel.")
    @app_commands.describe(
        tea_type="Choose your tea — each type has different rules",
        min_bet="Minimum bet to join (¥ — minimum ¥10)",
        max_players="Maximum players (2–24)",
        time_limit="Seconds per round (10–60)",
    )
    @app_commands.choices(tea_type=[
        app_commands.Choice(name="🍵 Black Tea  — contain all letters, last standing wins",    value="black"),
        app_commands.Choice(name="🍃 Green Tea  — fastest answer wins points, top 3 rewarded", value="green"),
        app_commands.Choice(name="🤍 White Tea  — fill in the blanks, last standing wins",     value="white"),
        app_commands.Choice(name="🔴 Red Tea    — unscramble letters, last standing wins",     value="red"),
        app_commands.Choice(name="💙 Blue Tea   — guess from example, last standing wins",     value="blue"),
    ])
    async def tea_slash(
        self,
        interaction: discord.Interaction,
        tea_type: str,
        min_bet: int,
        max_players: int,
        time_limit: int,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        if min_bet < 10:
            return await interaction.response.send_message(embed=Embeds.error("Minimum bet must be at least ¥10."), ephemeral=True)
        if not (MIN_PLAYERS <= max_players <= MAX_PLAYERS):
            return await interaction.response.send_message(embed=Embeds.error(f"Max players must be {MIN_PLAYERS}–{MAX_PLAYERS}."), ephemeral=True)
        if not (10 <= time_limit <= 60):
            return await interaction.response.send_message(embed=Embeds.error("Time limit must be 10–60 seconds."), ephemeral=True)

        if interaction.channel.id in _active_games:
            return await interaction.response.send_message(embed=Embeds.error("There's already an active Tea game in this channel."), ephemeral=True)
        if interaction.user.id in _active_users:
            return await interaction.response.send_message(embed=Embeds.error("You're already in an active game."), ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        bot_member = interaction.guild.get_member(interaction.client.user.id) if interaction.client.user else None
        if bot_member:
            perms = interaction.channel.permissions_for(bot_member)
            if not perms.send_messages or not perms.embed_links:
                return await interaction.response.send_message(
                    embed=Embeds.error("I need **Send Messages** and **Embed Links** permission in this channel."),
                    ephemeral=True,
                )

        game = TeaGame(
            channel=interaction.channel,
            host=member,
            tea_type=tea_type,
            min_bet=min_bet,
            max_players=max_players,
            time_limit=time_limit,
        )
        _active_games[interaction.channel.id] = game

        view = LobbyView(game=game, bot=self.bot)
        await interaction.response.send_message(embed=game.lobby_embed(), view=view)
        game.lobby_msg = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tea(bot))