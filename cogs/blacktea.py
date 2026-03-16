from __future__ import annotations

import asyncio
import logging
import random
import string
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.blacktea")

DICTIONARY_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
WORD_FETCH_API  = "https://random-word-api.herokuapp.com/word?number=1&length={length}"

MAX_PLAYERS     = 24
MIN_PLAYERS     = 2
LOBBY_TIMEOUT   = 300   # 5 minutes
MAX_LIVES       = 3

# Word lengths to fetch per mode
WORD_LENGTHS    = [4, 5, 6, 7]

# Active games: channel_id -> BlackteaGame
_active_games: dict[int, "BlackteaGame"] = {}
# Active users: user_id -> channel_id
_active_users: dict[int, int] = {}


# ── Dictionary API helpers ────────────────────────────────────────────────────

async def fetch_random_word(length: int | None = None) -> str | None:
    """Fetch a random English word."""
    try:
        l = length or random.choice(WORD_LENGTHS)
        url = WORD_FETCH_API.format(length=l)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list):
                        return data[0].lower()
    except Exception as e:
        logger.error(f"fetch_random_word: {e}")
    return None


async def fetch_word_data(word: str) -> dict | None:
    """Fetch definition and example for a word from Free Dictionary API."""
    try:
        url = DICTIONARY_API.format(word=word.lower())
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list):
                        return data[0]
    except Exception as e:
        logger.error(f"fetch_word_data({word}): {e}")
    return None


async def validate_word(word: str) -> bool:
    """Check if a word exists in the dictionary."""
    data = await fetch_word_data(word)
    return data is not None


def scramble_letters(word: str) -> str:
    """Scramble word letters, ensuring result differs from original."""
    letters = list(word.upper())
    for _ in range(10):
        random.shuffle(letters)
        if "".join(letters).lower() != word.lower():
            break
    return "  ".join(letters)


def make_fill(word: str) -> str:
    """Hide ~half the letters in a word showing blanks."""
    indices = list(range(len(word)))
    hide_count = max(1, len(word) // 2)
    hidden = random.sample(indices, hide_count)
    result = []
    for i, ch in enumerate(word.upper()):
        result.append("_" if i in hidden else ch)
    return "  ".join(result)


def get_example_sentence(word_data: dict, word: str) -> str | None:
    """Extract an example sentence from word data, blanking the word."""
    try:
        meanings = word_data.get("meanings", [])
        for meaning in meanings:
            for defn in meaning.get("definitions", []):
                example = defn.get("example", "")
                if example:
                    blanked = example.replace(word, "___").replace(word.capitalize(), "___")
                    return blanked
    except Exception:
        pass
    return None


# ── Player state ──────────────────────────────────────────────────────────────

class BlackteaPlayer:
    def __init__(self, member: discord.Member, bet: int) -> None:
        self.member   = member
        self.bet      = bet
        self.lives    = MAX_LIVES
        self.answered = False
        self.answer   = ""
        self.valid    = False

    @property
    def alive(self) -> bool:
        return self.lives > 0

    @property
    def lives_display(self) -> str:
        return "❤️" * self.lives + "🖤" * (MAX_LIVES - self.lives)

    def lose_life(self) -> None:
        if self.lives > 0:
            self.lives -= 1


# ── Game state ────────────────────────────────────────────────────────────────

class BlackteaGame:
    def __init__(
        self,
        channel: discord.TextChannel,
        host: discord.Member,
        mode: str,
        min_bet: int,
        max_players: int,
        time_limit: int,
    ) -> None:
        self.channel     = channel
        self.host        = host
        self.mode        = mode
        self.min_bet     = min_bet
        self.max_players = max_players
        self.time_limit  = time_limit
        self.players: list[BlackteaPlayer] = []
        self.used_words: set[str]          = set()
        self.round                         = 0
        self.lobby_msg: discord.Message | None  = None
        self.round_msg: discord.Message | None  = None
        self.current_word: str             = ""
        self.started                       = False
        self.finished                      = False

    @property
    def pot(self) -> int:
        return sum(p.bet for p in self.players)

    @property
    def alive_players(self) -> list[BlackteaPlayer]:
        return [p for p in self.players if p.alive]

    def get_player(self, user_id: int) -> BlackteaPlayer | None:
        return next((p for p in self.players if p.member.id == user_id), None)

    def lobby_embed(self) -> discord.Embed:
        mode_label = {"scramble": "🔀 Scramble", "fill": "✏️ Fill", "guess": "💭 Guess"}[self.mode]
        embed = Embeds.base(
            f"> `🍵` *Blacktea — {mode_label}*\n\n"
            f"> Min bet: `¥{self.min_bet:,}`  •  Players: `{len(self.players)}/{self.max_players}`  •  Time per round: `{self.time_limit}s`\n\n"
            + (
                "\n".join(f"> {p.member.display_name} — `¥{p.bet:,}`" for p in self.players)
                if self.players else "> *No players yet — be the first to join!*"
            )
        )
        embed.set_footer(text=f"Host: {self.host.display_name}  •  Game starts when host clicks Start or {self.max_players} players join")
        return embed

    def round_embed(self, challenge: str, hint: str = "") -> discord.Embed:
        mode_label = {"scramble": "🔀 Scramble", "fill": "✏️ Fill", "guess": "💭 Guess"}[self.mode]
        alive = self.alive_players
        player_lines = "\n".join(
            f"> {'⌛' if not p.answered else '✅' if p.valid else '❌'} {p.member.display_name} {p.lives_display}"
            for p in alive
        )
        embed = Embeds.base(
            f"> `🍵` *Blacktea — Round {self.round}  •  {mode_label}*\n\n"
            f"> **{challenge}**\n"
            + (f"> *{hint}*\n\n" if hint else "\n")
            + player_lines
        )
        embed.set_footer(text=f"Type your answer in this channel  •  {self.time_limit}s remaining  •  Pot: ¥{self.pot:,}")
        return embed

    def results_embed(self, results: list[tuple[BlackteaPlayer, bool, str]]) -> discord.Embed:
        lines = []
        for player, valid, answer in results:
            icon = "✅" if valid else "❌"
            ans_display = f"`{answer}`" if answer else "*no answer*"
            lines.append(f"> {icon} {player.member.display_name} — {ans_display}  {player.lives_display}")
        embed = Embeds.base(
            f"> `🍵` *Round {self.round} Results*\n\n"
            + "\n".join(lines)
            + f"\n\n> Correct answer: `{self.current_word}`"
        )
        embed.set_footer(text=f"Pot: ¥{self.pot:,}  •  Players remaining: {len(self.alive_players)}")
        return embed


# ── Lobby View ────────────────────────────────────────────────────────────────

class LobbyView(discord.ui.View):
    def __init__(self, game: BlackteaGame, bot: commands.Bot) -> None:
        super().__init__(timeout=LOBBY_TIMEOUT)
        self.game = game
        self.bot  = bot

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success, emoji="🍵")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        game = self.game

        if game.started:
            return await interaction.response.send_message(
                embed=Embeds.error("This game has already started."), ephemeral=True
            )
        if len(game.players) >= game.max_players:
            return await interaction.response.send_message(
                embed=Embeds.error("This game is full."), ephemeral=True
            )
        if game.get_player(interaction.user.id):
            return await interaction.response.send_message(
                embed=Embeds.error("You've already joined this game."), ephemeral=True
            )
        if interaction.user.id in _active_users:
            return await interaction.response.send_message(
                embed=Embeds.error("You're already in an active game."), ephemeral=True
            )

        modal = JoinModal(game=game, bot=self.bot, lobby_view=self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.host.id:
            return await interaction.response.send_message(
                embed=Embeds.error("Only the host can start the game."), ephemeral=True
            )
        if len(self.game.players) < MIN_PLAYERS:
            return await interaction.response.send_message(
                embed=Embeds.error(f"Need at least {MIN_PLAYERS} players to start."), ephemeral=True
            )

        await interaction.response.defer()
        self.stop()
        asyncio.create_task(run_game(self.game, self.bot))

    async def on_timeout(self) -> None:
        if not self.game.started:
            await _cancel_game(self.game, reason="Lobby timed out — game cancelled.")


class JoinModal(discord.ui.Modal, title="Join Blacktea"):
    bet_input = discord.ui.TextInput(
        label="Your bet amount",
        placeholder="Enter ¥ amount",
        min_length=1,
        max_length=10,
    )

    def __init__(self, game: BlackteaGame, bot: commands.Bot, lobby_view: LobbyView) -> None:
        super().__init__()
        self.game        = game
        self.bot         = bot
        self.lobby_view  = lobby_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            bet = int(self.bet_input.value.strip().replace(",", "").replace("¥", ""))
        except ValueError:
            return await interaction.response.send_message(
                embed=Embeds.error("Invalid bet amount."), ephemeral=True
            )

        if bet < self.game.min_bet:
            return await interaction.response.send_message(
                embed=Embeds.error(f"Minimum bet is ¥{self.game.min_bet:,}."), ephemeral=True
            )

        user_data = await db.get_or_create_user(interaction.user.id)
        if int(user_data["wallet"]) < bet:
            return await interaction.response.send_message(
                embed=Embeds.error(f"Insufficient funds. Wallet: ¥{int(user_data['wallet']):,}."), ephemeral=True
            )

        # Deduct bet immediately
        await db.update_wallet(interaction.user.id, -bet)

        member = interaction.guild.get_member(interaction.user.id) or interaction.user
        player = BlackteaPlayer(member=member, bet=bet)  # type: ignore[arg-type]
        self.game.players.append(player)
        _active_users[interaction.user.id] = self.game.channel.id

        # Update lobby embed
        if self.game.lobby_msg:
            await self.game.lobby_msg.edit(
                embed=self.game.lobby_embed(),
                view=self.lobby_view,
            )

        await interaction.response.send_message(
            embed=Embeds.success(f"You joined Blacktea with a bet of ¥{bet:,}!"),
            ephemeral=True,
        )

        # Auto-start if max players reached
        if len(self.game.players) >= self.game.max_players:
            self.lobby_view.stop()
            asyncio.create_task(run_game(self.game, self.bot))


# ── Game runner ───────────────────────────────────────────────────────────────

async def run_game(game: BlackteaGame, bot: commands.Bot) -> None:
    """Main game loop."""
    game.started = True

    # Update lobby to show game starting
    if game.lobby_msg:
        await game.lobby_msg.edit(
            embed=Embeds.base(f"> `🍵` *Blacktea is starting with {len(game.players)} players!*"),
            view=None,
        )

    await asyncio.sleep(2)

    while len(game.alive_players) > 1:
        game.round += 1

        # Fetch word for this round
        word = await _fetch_round_word(game)
        if not word:
            await game.channel.send(embed=Embeds.error("Failed to fetch a word — skipping round."))
            continue

        game.current_word = word
        game.used_words.add(word)

        # Reset player answers
        for p in game.alive_players:
            p.answered = False
            p.answer   = ""
            p.valid    = False

        # Build challenge display
        challenge, hint = _build_challenge(game.mode, word)

        # Post round embed
        round_embed = game.round_embed(challenge, hint)
        game.round_msg = await game.channel.send(embed=round_embed)

        # Listen for answers
        await _collect_answers(game, bot, word)

        # Score the round
        results = await _score_round(game, word)

        # Show results
        await game.channel.send(embed=game.results_embed(results))

        # Check eliminations
        eliminated = [p for p in game.alive_players if p.lives == 0]
        if eliminated:
            names = ", ".join(p.member.display_name for p in eliminated)
            await game.channel.send(
                embed=Embeds.base(f"> `💀` *{names} {'has' if len(eliminated) == 1 else 'have'} been eliminated!*")
            )

        await asyncio.sleep(3)

    # Game over
    await _end_game(game)


async def _fetch_round_word(game: BlackteaGame) -> str | None:
    """Fetch a word not used this game, with a definition/example for fill/guess."""
    for _ in range(5):
        length = random.choice(WORD_LENGTHS)
        word = await fetch_random_word(length)
        if not word or word in game.used_words:
            continue

        if game.mode in ("fill", "guess"):
            data = await fetch_word_data(word)
            if not data:
                continue
            if game.mode == "guess" and not get_example_sentence(data, word):
                continue

        return word
    return None


def _build_challenge(mode: str, word: str) -> tuple[str, str]:
    """Build the challenge string and hint for a given mode and word."""
    if mode == "scramble":
        challenge = scramble_letters(word)
        hint = f"Unscramble these letters to form a valid English word  •  {len(word)} letters"
        return challenge, hint

    elif mode == "fill":
        challenge = make_fill(word)
        hint = "Fill in the missing letters"
        return challenge, hint

    else:  # guess
        # We'll use a sync placeholder here — actual example fetched in run_game
        challenge = "Loading example..."
        hint = f"{len(word)} letters"
        return challenge, hint


async def _build_guess_challenge(word: str) -> tuple[str, str]:
    """Async version for guess mode — fetches example sentence."""
    data = await fetch_word_data(word)
    if data:
        example = get_example_sentence(data, word)
        if example:
            return example, f"{len(word)} letters"
    return f"*Definition not available*", f"{len(word)} letters"


async def _collect_answers(game: BlackteaGame, bot: commands.Bot, word: str) -> None:
    """Listen to channel messages for player answers within time_limit."""
    alive_ids = {p.member.id for p in game.alive_players}

    def check(msg: discord.Message) -> bool:
        return (
            msg.channel.id == game.channel.id
            and msg.author.id in alive_ids
            and not msg.author.bot
        )

    deadline = asyncio.get_event_loop().time() + game.time_limit
    pending_ids = set(alive_ids)

    while pending_ids and asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            msg = await bot.wait_for("message", check=check, timeout=remaining)
            player = game.get_player(msg.author.id)
            if player and not player.answered:
                player.answered = True
                player.answer   = msg.content.strip().lower()
                pending_ids.discard(msg.author.id)
                try:
                    await msg.add_reaction("📝")
                except Exception:
                    pass
        except asyncio.TimeoutError:
            break


async def _score_round(
    game: BlackteaGame,
    word: str,
) -> list[tuple[BlackteaPlayer, bool, str]]:
    """Score all alive players for this round."""
    results = []

    for player in game.alive_players:
        answer = player.answer.strip().lower()

        if not answer:
            # No answer — lose a life
            player.valid = False
            player.lose_life()
            results.append((player, False, ""))
            continue

        # Validate based on mode
        if game.mode == "scramble":
            # Word must exist in dictionary AND contain all letters of target
            target_letters = sorted(word.lower())
            answer_letters = sorted(answer.lower())
            letters_ok = all(l in answer_letters for l in target_letters)
            if letters_ok and len(answer) >= 3:
                valid = await validate_word(answer)
            else:
                valid = False

        elif game.mode == "fill":
            # Must match the exact word
            valid = answer == word.lower()

        else:  # guess
            valid = answer == word.lower()

        player.valid = valid
        if not valid:
            player.lose_life()

        results.append((player, valid, answer))

    return results


async def _end_game(game: BlackteaGame) -> None:
    """Handle game end — pay out winners, clean up."""
    alive = game.alive_players
    pot   = game.pot

    if not alive:
        # Everyone eliminated simultaneously — refund all
        for p in game.players:
            await db.update_wallet(p.member.id, p.bet)
        await game.channel.send(embed=Embeds.base(
            "> `🍵` *Everyone was eliminated! All bets have been refunded.*"
        ))
    elif len(alive) == 1:
        winner = alive[0]
        await db.update_wallet(winner.member.id, pot)
        await db.log_transaction(0, winner.member.id, pot, "blacktea_win")
        for loser in game.players:
            if loser.member.id != winner.member.id:
                await db.log_transaction(loser.member.id, 0, loser.bet, "blacktea_loss")

        embed = Embeds.base(
            f"> `🏆` *{winner.member.display_name} wins Blacktea!*\n\n"
            f"> Prize: `¥{pot:,}`\n"
            f"> Rounds played: `{game.round}`"
        )
        await game.channel.send(embed=embed)
    else:
        # Multiple survivors — split pot proportionally
        total_bets = sum(p.bet for p in alive)
        embed_lines = []
        for p in alive:
            share = int(pot * (p.bet / total_bets))
            await db.update_wallet(p.member.id, share)
            await db.log_transaction(0, p.member.id, share, "blacktea_win")
            embed_lines.append(f"> 🏆 {p.member.display_name} — `¥{share:,}`")

        embed = Embeds.base(
            f"> `🤝` *Blacktea ends in a tie!*\n\n"
            + "\n".join(embed_lines)
        )
        await game.channel.send(embed=embed)

    game.finished = True
    await _cleanup_game(game)


async def _cancel_game(game: BlackteaGame, reason: str) -> None:
    """Cancel game and refund all bets."""
    for p in game.players:
        await db.update_wallet(p.member.id, p.bet)

    await game.channel.send(embed=Embeds.base(
        f"> `❌` *Blacktea cancelled — {reason}*\n"
        f"> All bets have been refunded."
    ))
    await _cleanup_game(game)


async def _cleanup_game(game: BlackteaGame) -> None:
    """Remove game from active tracking."""
    _active_games.pop(game.channel.id, None)
    for p in game.players:
        _active_users.pop(p.member.id, None)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Blacktea(commands.Cog):
    """Blacktea word game — scramble, fill, guess."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="blacktea", description="Start a Blacktea word game in this channel.")
    @app_commands.describe(
        mode="Game mode — scramble, fill, or guess",
        min_bet="Minimum bet to join (¥)",
        max_players="Max players (2–24)",
        time_limit="Seconds per round (10–60)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="🔀 Scramble — unscramble letters into a valid word", value="scramble"),
        app_commands.Choice(name="✏️ Fill — fill in the missing letters",              value="fill"),
        app_commands.Choice(name="💭 Guess — guess the word from an example sentence", value="guess"),
    ])
    async def blacktea_slash(
        self,
        interaction: discord.Interaction,
        mode: str,
        min_bet: int,
        max_players: int,
        time_limit: int,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        # Validate inputs
        if min_bet < 10:
            return await interaction.response.send_message(
                embed=Embeds.error("Minimum bet must be at least ¥10."), ephemeral=True
            )
        if not (MIN_PLAYERS <= max_players <= MAX_PLAYERS):
            return await interaction.response.send_message(
                embed=Embeds.error(f"Max players must be between {MIN_PLAYERS} and {MAX_PLAYERS}."), ephemeral=True
            )
        if not (10 <= time_limit <= 60):
            return await interaction.response.send_message(
                embed=Embeds.error("Time limit must be between 10 and 60 seconds."), ephemeral=True
            )

        # Check channel lock
        if interaction.channel.id in _active_games:
            return await interaction.response.send_message(
                embed=Embeds.error("There's already an active Blacktea game in this channel."), ephemeral=True
            )

        # Check user lock
        if interaction.user.id in _active_users:
            return await interaction.response.send_message(
                embed=Embeds.error("You're already in an active game."), ephemeral=True
            )

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        game = BlackteaGame(
            channel=interaction.channel,
            host=member,
            mode=mode,
            min_bet=min_bet,
            max_players=max_players,
            time_limit=time_limit,
        )
        _active_games[interaction.channel.id] = game

        view = LobbyView(game=game, bot=self.bot)

        await interaction.response.send_message(
            embed=game.lobby_embed(),
            view=view,
        )
        msg = await interaction.original_response()
        game.lobby_msg = msg


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Blacktea(bot))