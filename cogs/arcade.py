from __future__ import annotations

"""
cogs/arcade.py

Five 1v1 betting minigames:
  /mathduel      — solve equations fastest, best of 5
  /numberbomb    — pick a number, one explodes
  /rps           — rock paper scissors, best of 5
  /tictactoe     — 3x3 grid, best of 3
  /reactionrace  — click the button first, best of 5

All games share a common challenge/accept flow.
Embed factories live in embeds.py — see Embeds.arcade_*.
"""

import asyncio
import logging
import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.arcade")

# ── Constants ─────────────────────────────────────────────────────────────────

CHALLENGE_TIMEOUT = 60
ROUND_TIMEOUT     = 20
MIN_BET           = 10

# Active players — user_id → channel_id (prevents double-joining)
_active_players: dict[int, int] = {}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _record_result(winner_id: int, loser_id: int, bet: int, game: str) -> None:
    """Pay winner, log transactions, update arcade_stats for both players."""
    await db.update_wallet(winner_id, bet * 2)
    await db.log_transaction(loser_id, winner_id, bet, f"{game}_win")
    await _upsert_stat(winner_id, game, won=True,  yen_delta=bet)
    await _upsert_stat(loser_id,  game, won=False, yen_delta=bet)


async def _refund_both(p1_id: int, p2_id: int, bet: int) -> None:
    await db.update_wallet(p1_id, bet)
    await db.update_wallet(p2_id, bet)


async def _upsert_stat(user_id: int, game: str, won: bool, yen_delta: int) -> None:
    try:
        res = db.supabase.table("arcade_stats").select("*").eq("user_id", user_id).eq("game", game).execute()
        if res.data:
            row: dict[str, Any] = dict(res.data[0])  # type: ignore[arg-type]
            db.supabase.table("arcade_stats").update({
                "wins":       int(row["wins"])     + (1 if won else 0),
                "losses":     int(row["losses"])   + (0 if won else 1),
                "yen_won":    int(row["yen_won"])  + (yen_delta if won else 0),
                "yen_lost":   int(row["yen_lost"]) + (0 if won else yen_delta),
                "updated_at": "now()",
            }).eq("stat_id", int(row["stat_id"])).execute()
        else:
            db.supabase.table("arcade_stats").insert({
                "user_id":  user_id,
                "game":     game,
                "wins":     1 if won else 0,
                "losses":   0 if won else 1,
                "yen_won":  yen_delta if won else 0,
                "yen_lost": 0 if won else yen_delta,
            }).execute()
    except Exception as e:
        logger.error("_upsert_stat(%d, %s): %s", user_id, game, e)


# ── Shared challenge flow ─────────────────────────────────────────────────────

class ArcadeChallenge:
    """Holds state for a pending 1v1 challenge."""

    def __init__(
        self,
        channel: discord.TextChannel,
        challenger: discord.Member,
        opponent: discord.Member,
        bet: int,
        game_name: str,
        game_emoji: str,
        game_desc: str,
    ) -> None:
        self.channel    = channel
        self.challenger = challenger
        self.opponent   = opponent
        self.bet        = bet
        self.game_name  = game_name
        self.game_emoji = game_emoji
        self.game_desc  = game_desc
        self.accepted   = False
        self.declined   = False


class ChallengeView(discord.ui.View):
    """Accept / Decline buttons shown on the challenge embed."""

    children: list[discord.ui.Button]

    def __init__(
        self,
        challenge: ArcadeChallenge,
        on_accept: Any,
        on_decline: Any,
    ) -> None:
        super().__init__(timeout=CHALLENGE_TIMEOUT)
        self.challenge  = challenge
        self.on_accept  = on_accept
        self.on_decline = on_decline

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.challenge.opponent.id:
            await interaction.response.send_message(
                embed=Embeds.error("This challenge isn't for you."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.challenge.accepted = True
        self.stop()
        await interaction.response.edit_message(
            embed=Embeds.arcade_challenge_accepted(self.challenge),
            view=None,
        )
        await self.on_accept()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.challenge.declined = True
        self.stop()
        await interaction.response.edit_message(
            embed=Embeds.arcade_challenge_declined(self.challenge),
            view=None,
        )
        await self.on_decline()

    async def on_timeout(self) -> None:
        if not self.challenge.accepted and not self.challenge.declined:
            try:
                await self.challenge.channel.send(
                    embed=Embeds.arcade_challenge_expired(self.challenge)
                )
            except discord.HTTPException:
                pass
            await self.on_decline()


async def _setup_challenge(
    interaction: discord.Interaction,
    opponent: discord.Member,
    bet: int,
    game_name: str,
    game_emoji: str,
    game_desc: str,
) -> ArcadeChallenge | None:
    """Validate, deduct challenger bet, register as active. Returns None on failure."""
    author  = interaction.user
    guild   = interaction.guild
    channel = interaction.channel

    if not guild or not isinstance(channel, discord.TextChannel):
        await interaction.followup.send(embed=Embeds.error("Use this in a server text channel."), ephemeral=True)
        return None
    if opponent.id == author.id:
        await interaction.followup.send(embed=Embeds.error("You can't challenge yourself."), ephemeral=True)
        return None
    if opponent.bot:
        await interaction.followup.send(embed=Embeds.error("You can't challenge a bot."), ephemeral=True)
        return None
    if bet < MIN_BET:
        await interaction.followup.send(embed=Embeds.error(f"Minimum bet is ¥{MIN_BET:,}."), ephemeral=True)
        return None
    if author.id in _active_players:
        await interaction.followup.send(embed=Embeds.error("You're already in an active game."), ephemeral=True)
        return None
    if opponent.id in _active_players:
        await interaction.followup.send(
            embed=Embeds.error(f"{opponent.display_name} is already in an active game."), ephemeral=True
        )
        return None

    challenger_data = await db.get_or_create_user(author.id)
    if int(challenger_data["wallet"]) < bet:
        await interaction.followup.send(
            embed=Embeds.error(f"Insufficient funds. Wallet: ¥{int(challenger_data['wallet']):,}."),
            ephemeral=True,
        )
        return None

    await db.update_wallet(author.id, -bet)
    # guild.get_member() can theoretically return None if the member left between
    # the slash command firing and here, but guild is confirmed non-None above and
    # the user just sent an interaction so they must be present. The assert
    # satisfies the type checker without introducing a User fallback.
    challenger_member = guild.get_member(author.id)
    assert challenger_member is not None
    challenge = ArcadeChallenge(
        channel=channel,
        challenger=challenger_member,
        opponent=opponent,
        bet=bet,
        game_name=game_name,
        game_emoji=game_emoji,
        game_desc=game_desc,
    )
    _active_players[author.id] = channel.id
    return challenge


def _cleanup(challenge: ArcadeChallenge) -> None:
    _active_players.pop(challenge.challenger.id, None)
    _active_players.pop(challenge.opponent.id, None)


async def _accept_bet(challenge: ArcadeChallenge) -> bool:
    """Deduct opponent bet on accept. Returns False + refunds challenger if broke."""
    opp_data = await db.get_or_create_user(challenge.opponent.id)
    if int(opp_data["wallet"]) < challenge.bet:
        await challenge.channel.send(embed=Embeds.error(
            f"{challenge.opponent.display_name} doesn't have enough ¥ to match — bets refunded."
        ))
        await db.update_wallet(challenge.challenger.id, challenge.bet)
        _cleanup(challenge)
        return False
    await db.update_wallet(challenge.opponent.id, -challenge.bet)
    _active_players[challenge.opponent.id] = challenge.channel.id
    return True


# ── Math Duel ─────────────────────────────────────────────────────────────────

def _make_equation(round_num: int) -> tuple[str, int]:
    if round_num <= 2:
        a, b = random.randint(1, 20), random.randint(1, 20)
        op   = random.choice(["+", "-"])
        return f"{a} {op} {b}", a + b if op == "+" else a - b
    elif round_num <= 4:
        a, b = random.randint(2, 12), random.randint(2, 12)
        return f"{a} × {b}", a * b
    else:
        a, b, c = random.randint(2, 10), random.randint(2, 10), random.randint(1, 10)
        if random.choice([True, False]):
            return f"{a} + {b} × {c}", a + b * c
        return f"{a} - {b} × {c}", a - b * c


async def _run_mathduel(challenge: ArcadeChallenge, bot: commands.Bot) -> None:
    ch, p1, p2, bet = challenge.channel, challenge.challenger, challenge.opponent, challenge.bet
    scores: dict[int, int] = {p1.id: 0, p2.id: 0}
    ROUNDS, TARGET = 5, 3

    await ch.send(embed=Embeds.arcade_game_start(challenge, f"First to `{TARGET}` correct answers wins!"))
    await asyncio.sleep(2)

    target_ids = {p1.id, p2.id}

    def check(msg: discord.Message) -> bool:
        return msg.channel.id == ch.id and msg.author.id in target_ids

    for rnd in range(1, ROUNDS + 1):
        equation, answer = _make_equation(rnd)
        await ch.send(embed=Embeds.arcade_mathduel_round(rnd, ROUNDS, equation, scores, p1, p2))

        winner_this_round: discord.Member | None = None
        deadline = asyncio.get_running_loop().time() + ROUND_TIMEOUT

        while asyncio.get_running_loop().time() < deadline:
            remaining = deadline - asyncio.get_running_loop().time()
            try:
                msg = await bot.wait_for("message", check=check, timeout=max(0.1, remaining))
                try:
                    guess = int(msg.content.strip().replace(" ", ""))
                except ValueError:
                    continue
                if guess == answer:
                    winner_this_round = p1 if msg.author.id == p1.id else p2
                    scores[msg.author.id] += 1
                    await msg.add_reaction("✅")
                    break
                else:
                    await msg.add_reaction("❌")
            except asyncio.TimeoutError:
                break

        await ch.send(embed=Embeds.arcade_round_result(winner_this_round, str(answer), winner_this_round is None))

        for pid, wins in scores.items():
            if wins >= TARGET:
                game_winner = p1 if p1.id == pid else p2
                game_loser  = p2 if game_winner.id == p1.id else p1
                await ch.send(embed=Embeds.arcade_game_over(game_winner, bet, scores, p1, p2))
                await _record_result(game_winner.id, game_loser.id, bet, "mathduel")
                _cleanup(challenge)
                return

        await asyncio.sleep(2)

    if scores[p1.id] != scores[p2.id]:
        winner = p1 if scores[p1.id] > scores[p2.id] else p2
        loser  = p2 if winner.id == p1.id else p1
        await ch.send(embed=Embeds.arcade_game_over(winner, bet, scores, p1, p2))
        await _record_result(winner.id, loser.id, bet, "mathduel")
    else:
        await ch.send(embed=Embeds.arcade_tie(challenge))
        await _refund_both(p1.id, p2.id, bet)
    _cleanup(challenge)


# ── Number Bomb ───────────────────────────────────────────────────────────────

class NumberBombButton(discord.ui.Button["NumberBombView"]):
    def __init__(self, number: int) -> None:
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.secondary,
            custom_id=f"bomb_{number}",
        )
        self.number = number

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        view: NumberBombView = self.view
        if interaction.user.id != view.current_player.id:
            await interaction.response.send_message(
                embed=Embeds.error("It's not your turn!"), ephemeral=True
            )
            return
        view.chosen = self.number
        view.stop()
        await interaction.response.defer()


class NumberBombView(discord.ui.View):
    children: list[NumberBombButton]

    def __init__(self, current_player: discord.Member, available: list[int]) -> None:
        super().__init__(timeout=30)
        self.current_player = current_player
        self.chosen: int | None = None
        for n in available:
            self.add_item(NumberBombButton(n))


async def _run_numberbomb(challenge: ArcadeChallenge, bot: commands.Bot) -> None:
    ch, p1, p2, bet = challenge.channel, challenge.challenger, challenge.opponent, challenge.bet
    bomb             = random.randint(1, 10)
    turn, other      = p1, p2
    picked: set[int] = set()

    await ch.send(embed=Embeds.arcade_game_start(
        challenge,
        f"Pick numbers `1–10` one at a time.\n"
        f"> Whoever picks the bomb 💥 loses `¥{bet * 2:,}`!\n"
        f"> **{p1.display_name}** goes first."
    ))
    await asyncio.sleep(2)

    while True:
        available = [i for i in range(1, 11) if i not in picked]
        if not available:
            await ch.send(embed=Embeds.arcade_tie(challenge))
            await _refund_both(p1.id, p2.id, bet)
            _cleanup(challenge)
            return

        view = NumberBombView(current_player=turn, available=available)
        msg  = await ch.send(
            embed=Embeds.arcade_numberbomb_turn(turn, available, picked),
            view=view,
        )
        await view.wait()

        try:
            await msg.edit(view=None)
        except discord.HTTPException:
            pass

        if view.chosen is None:
            await ch.send(embed=Embeds.arcade_timeout(turn))
            await _refund_both(p1.id, p2.id, bet)
            _cleanup(challenge)
            return

        chosen = view.chosen
        picked.add(chosen)

        if chosen == bomb:
            winner = other
            loser  = turn
            await ch.send(embed=Embeds.arcade_numberbomb_explosion(loser, chosen, winner, bet))
            await _record_result(winner.id, loser.id, bet, "numberbomb")
            _cleanup(challenge)
            return

        await ch.send(embed=Embeds.arcade_numberbomb_safe(turn, chosen))
        await asyncio.sleep(1)
        turn, other = other, turn


# ── RPS ───────────────────────────────────────────────────────────────────────

RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
RPS_EMOJI  = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}


class RPSView(discord.ui.View):
    children: list[discord.ui.Button]

    def __init__(self, player: discord.Member) -> None:
        super().__init__(timeout=ROUND_TIMEOUT)
        self.player = player
        self.choice: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.id

    @discord.ui.button(label="Rock",     style=discord.ButtonStyle.secondary, emoji="🪨")
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.choice = "rock"
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Paper",    style=discord.ButtonStyle.secondary, emoji="📄")
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.choice = "paper"
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Scissors", style=discord.ButtonStyle.secondary, emoji="✂️")
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.choice = "scissors"
        self.stop()
        await interaction.response.defer()


async def _run_rps(challenge: ArcadeChallenge, bot: commands.Bot) -> None:
    ch, p1, p2, bet = challenge.channel, challenge.challenger, challenge.opponent, challenge.bet
    scores: dict[int, int] = {p1.id: 0, p2.id: 0}
    ROUNDS, TARGET = 5, 3

    await ch.send(embed=Embeds.arcade_game_start(
        challenge,
        f"Best of `{ROUNDS}` — first to `{TARGET}` wins.\n"
        "> Both players submit their pick secretly via DM — no peeking!"
    ))
    await asyncio.sleep(2)

    async def get_choice(player: discord.Member) -> str | None:
        view = RPSView(player)
        try:
            dm = await player.send(embed=Embeds.arcade_rps_dm(player), view=view)
            await asyncio.wait_for(view.wait(), timeout=ROUND_TIMEOUT)
            try:
                await dm.edit(
                    embed=Embeds.base(
                        f"> `✅` *You picked {RPS_EMOJI.get(view.choice or '', '?')} — waiting for opponent...*"
                        if view.choice else "> `⏱️` *You didn't pick in time!*"
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass
            return view.choice
        except (discord.Forbidden, asyncio.TimeoutError):
            return None

    for rnd in range(1, ROUNDS + 1):
        await ch.send(embed=Embeds.arcade_rps_round(rnd, ROUNDS, scores, p1, p2))
        c1, c2 = await asyncio.gather(get_choice(p1), get_choice(p2))

        if not c1 or not c2:
            missing = p1.display_name if not c1 else p2.display_name
            await ch.send(embed=Embeds.base(f"> `⏱️` *{missing} didn't pick in time — round skipped.*"))
            continue

        if c1 == c2:
            round_winner = None
        elif RPS_BEATS[c1] == c2:
            round_winner = p1
            scores[p1.id] += 1
        else:
            round_winner = p2
            scores[p2.id] += 1

        await ch.send(embed=Embeds.arcade_rps_result(p1, c1, p2, c2, round_winner))

        for pid, wins in scores.items():
            if wins >= TARGET:
                game_winner = p1 if p1.id == pid else p2
                game_loser  = p2 if game_winner.id == p1.id else p1
                await ch.send(embed=Embeds.arcade_game_over(game_winner, bet, scores, p1, p2))
                await _record_result(game_winner.id, game_loser.id, bet, "rps")
                _cleanup(challenge)
                return

        await asyncio.sleep(2)

    if scores[p1.id] != scores[p2.id]:
        winner = p1 if scores[p1.id] > scores[p2.id] else p2
        loser  = p2 if winner.id == p1.id else p1
        await ch.send(embed=Embeds.arcade_game_over(winner, bet, scores, p1, p2))
        await _record_result(winner.id, loser.id, bet, "rps")
    else:
        await ch.send(embed=Embeds.arcade_tie(challenge))
        await _refund_both(p1.id, p2.id, bet)
    _cleanup(challenge)


# ── Tic Tac Toe ───────────────────────────────────────────────────────────────

class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    def __init__(self, index: int) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="\u200b",   # zero-width space — empty cell
            row=index // 3,
            custom_id=f"ttt_{index}",
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        view: TicTacToeView = self.view

        if interaction.user.id != view.current_player.id:
            await interaction.response.send_message(
                embed=Embeds.error("It's not your turn!"), ephemeral=True
            )
            return

        view.board[self.index] = view.current_symbol
        self.label    = view.current_symbol
        self.style    = discord.ButtonStyle.danger if view.current_symbol == "X" else discord.ButtonStyle.primary
        self.disabled = True

        result = view.check_winner()

        if result is not None:
            for child in view.children:
                child.disabled = True
            view.game_over   = True
            view.game_result = result
            view.stop()
            await interaction.response.edit_message(
                embed=Embeds.arcade_ttt_board(view, result),
                view=view,
            )
        else:
            view.current_player = view.p2 if view.current_player.id == view.p1.id else view.p1
            view.current_symbol = "O" if view.current_symbol == "X" else "X"
            await interaction.response.edit_message(
                embed=Embeds.arcade_ttt_board(view, None),
                view=view,
            )


class TicTacToeView(discord.ui.View):
    children: list[TicTacToeButton]

    def __init__(self, p1: discord.Member, p2: discord.Member) -> None:
        super().__init__(timeout=30)
        self.p1             = p1
        self.p2             = p2
        self.current_player = p1
        self.current_symbol = "X"
        self.board          = [" "] * 9
        self.game_over      = False
        self.game_result: str | None = None
        for i in range(9):
            self.add_item(TicTacToeButton(i))

    def check_winner(self) -> str | None:
        wins = [
            (0,1,2),(3,4,5),(6,7,8),
            (0,3,6),(1,4,7),(2,5,8),
            (0,4,8),(2,4,6),
        ]
        for a, b, c in wins:
            if self.board[a] == self.board[b] == self.board[c] and self.board[a] != " ":
                return self.board[a]
        if " " not in self.board:
            return "draw"
        return None

    async def on_timeout(self) -> None:
        self.game_over   = True
        self.game_result = "timeout"
        self.stop()


async def _run_tictactoe(challenge: ArcadeChallenge, bot: commands.Bot) -> None:
    ch, p1, p2, bet = challenge.channel, challenge.challenger, challenge.opponent, challenge.bet
    scores: dict[int, int] = {p1.id: 0, p2.id: 0}
    GAMES, TARGET = 3, 2

    await ch.send(embed=Embeds.arcade_game_start(
        challenge,
        f"Best of `{GAMES}` games — first to `{TARGET}` wins.\n"
        f"> {p1.mention} plays ❌  ·  {p2.mention} plays ⭕"
    ))
    await asyncio.sleep(2)

    for game_num in range(1, GAMES + 1):
        first  = p1 if game_num % 2 == 1 else p2
        second = p2 if game_num % 2 == 1 else p1

        view = TicTacToeView(p1=first, p2=second)
        msg  = await ch.send(
            embed=Embeds.arcade_ttt_board(view, None, game_num=game_num, total_games=GAMES),
            view=view,
        )
        await view.wait()

        try:
            await msg.edit(view=view)
        except discord.HTTPException:
            pass

        result = view.game_result

        if result == "timeout":
            timed_out   = view.current_player
            game_winner = view.p2 if timed_out.id == view.p1.id else view.p1
            await ch.send(embed=Embeds.arcade_timeout(timed_out))
            scores[game_winner.id] += 1
        elif result == "draw":
            await ch.send(embed=Embeds.base(f"> `🤝` *Game {game_num} — Draw! No point awarded.*"))
        elif result in ("X", "O"):
            game_winner = first if result == "X" else second
            scores[game_winner.id] += 1
            await ch.send(embed=Embeds.base(
                f"> `{'❌' if result == 'X' else '⭕'}` *{game_winner.display_name} wins game {game_num}!*\n"
                f"> Score: `{scores[p1.id]}` — `{scores[p2.id]}`"
            ))

        for pid, wins in scores.items():
            if wins >= TARGET:
                match_winner = p1 if p1.id == pid else p2
                match_loser  = p2 if match_winner.id == p1.id else p1
                await ch.send(embed=Embeds.arcade_game_over(match_winner, bet, scores, p1, p2))
                await _record_result(match_winner.id, match_loser.id, bet, "tictactoe")
                _cleanup(challenge)
                return

        await asyncio.sleep(2)

    if scores[p1.id] != scores[p2.id]:
        winner = p1 if scores[p1.id] > scores[p2.id] else p2
        loser  = p2 if winner.id == p1.id else p1
        await ch.send(embed=Embeds.arcade_game_over(winner, bet, scores, p1, p2))
        await _record_result(winner.id, loser.id, bet, "tictactoe")
    else:
        await ch.send(embed=Embeds.arcade_tie(challenge))
        await _refund_both(p1.id, p2.id, bet)
    _cleanup(challenge)


# ── Reaction Race ─────────────────────────────────────────────────────────────

class ReactionView(discord.ui.View):
    children: list[discord.ui.Button]

    def __init__(self, target_ids: set[int]) -> None:
        super().__init__(timeout=10)
        self.target_ids = target_ids
        self.winner_id: int | None = None

    @discord.ui.button(label="⚡ CLICK!", style=discord.ButtonStyle.success)
    async def click(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id not in self.target_ids:
            await interaction.response.send_message(
                embed=Embeds.error("You're not in this game."), ephemeral=True
            )
            return
        self.winner_id = interaction.user.id
        self.stop()
        await interaction.response.defer()


async def _run_reactionrace(challenge: ArcadeChallenge, bot: commands.Bot) -> None:
    ch, p1, p2, bet = challenge.channel, challenge.challenger, challenge.opponent, challenge.bet
    scores: dict[int, int] = {p1.id: 0, p2.id: 0}
    ROUNDS, TARGET = 5, 3
    target_ids = {p1.id, p2.id}

    await ch.send(embed=Embeds.arcade_game_start(
        challenge,
        f"First to `{TARGET}` clicks wins!\n"
        "> Click ⚡ CLICK! the instant it appears — watch for fake-outs!"
    ))
    await asyncio.sleep(3)

    for rnd in range(1, ROUNDS + 1):
        delay      = random.uniform(3.0, 8.0)
        is_fakeout = random.random() < 0.30

        await ch.send(embed=Embeds.arcade_reaction_waiting(rnd, ROUNDS, scores, p1, p2))
        await asyncio.sleep(delay)

        if is_fakeout:
            await ch.send(embed=Embeds.base("> `😂` *FAKE OUT! Nothing happened.*"))
            await asyncio.sleep(1.5)
            continue

        view     = ReactionView(target_ids=target_ids)
        race_msg = await ch.send(embed=Embeds.base("> # ⚡ NOW!"), view=view)
        await view.wait()

        try:
            await race_msg.edit(view=None)
        except discord.HTTPException:
            pass

        if view.winner_id is None:
            await ch.send(embed=Embeds.base("> `⏱️` *Nobody clicked in time!*"))
        else:
            round_winner = p1 if view.winner_id == p1.id else p2
            scores[round_winner.id] += 1
            await ch.send(embed=Embeds.base(f"> `⚡` *{round_winner.display_name} clicked first!*"))

            for pid, wins in scores.items():
                if wins >= TARGET:
                    game_winner = p1 if p1.id == pid else p2
                    game_loser  = p2 if game_winner.id == p1.id else p1
                    await ch.send(embed=Embeds.arcade_game_over(game_winner, bet, scores, p1, p2))
                    await _record_result(game_winner.id, game_loser.id, bet, "reactionrace")
                    _cleanup(challenge)
                    return

        await asyncio.sleep(2)

    if scores[p1.id] != scores[p2.id]:
        winner = p1 if scores[p1.id] > scores[p2.id] else p2
        loser  = p2 if winner.id == p1.id else p1
        await ch.send(embed=Embeds.arcade_game_over(winner, bet, scores, p1, p2))
        await _record_result(winner.id, loser.id, bet, "reactionrace")
    else:
        await ch.send(embed=Embeds.arcade_tie(challenge))
        await _refund_both(p1.id, p2.id, bet)
    _cleanup(challenge)


# ── Arcade Cog ────────────────────────────────────────────────────────────────

class Arcade(commands.Cog):
    """1v1 arcade betting games."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send_challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        bet: int,
        game_name: str,
        game_emoji: str,
        game_desc: str,
        runner: Any,
    ) -> None:
        challenge = await _setup_challenge(interaction, opponent, bet, game_name, game_emoji, game_desc)
        if not challenge:
            return

        async def on_accept() -> None:
            if not await _accept_bet(challenge):
                return
            asyncio.create_task(runner(challenge, self.bot))

        async def on_decline() -> None:
            await db.update_wallet(challenge.challenger.id, challenge.bet)
            _cleanup(challenge)

        view = ChallengeView(challenge, on_accept, on_decline)
        await interaction.followup.send(embed=Embeds.arcade_challenge(challenge), view=view)

    @app_commands.command(name="mathduel", description="Challenge someone to a math duel. Solve equations fastest!")
    @app_commands.describe(opponent="Who to challenge", bet="Amount to bet — winner takes double")
    async def mathduel(self, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        await interaction.response.defer()
        await self._send_challenge(interaction, opponent, bet, "Math Duel", "🧮",
            "Solve equations fastest — best of 5, first to 3 wins.", _run_mathduel)

    @app_commands.command(name="numberbomb", description="Challenge someone to Number Bomb — avoid the explosion!")
    @app_commands.describe(opponent="Who to challenge", bet="Amount to bet — winner takes double")
    async def numberbomb(self, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        await interaction.response.defer()
        await self._send_challenge(interaction, opponent, bet, "Number Bomb", "💣",
            "Pick numbers 1–10 one at a time. Whoever picks the bomb loses!", _run_numberbomb)

    @app_commands.command(name="rps", description="Challenge someone to Rock Paper Scissors — best of 5.")
    @app_commands.describe(opponent="Who to challenge", bet="Amount to bet — winner takes double")
    async def rps(self, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        await interaction.response.defer()
        await self._send_challenge(interaction, opponent, bet, "Rock Paper Scissors", "✂️",
            "Best of 5. Submit picks secretly via DM — no peeking!", _run_rps)

    @app_commands.command(name="tictactoe", description="Challenge someone to Tic Tac Toe — best of 3.")
    @app_commands.describe(opponent="Who to challenge", bet="Amount to bet — winner takes double")
    async def tictactoe(self, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        await interaction.response.defer()
        await self._send_challenge(interaction, opponent, bet, "Tic Tac Toe", "❌",
            "Classic 3×3 grid — best of 3 games.", _run_tictactoe)

    @app_commands.command(name="reactionrace", description="Challenge someone to a Reaction Race — click first!")
    @app_commands.describe(opponent="Who to challenge", bet="Amount to bet — winner takes double")
    async def reactionrace(self, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        await interaction.response.defer()
        await self._send_challenge(interaction, opponent, bet, "Reaction Race", "⚡",
            "Click ⚡ CLICK! the instant it appears. Best of 5 — watch for fake-outs!", _run_reactionrace)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Arcade(bot))