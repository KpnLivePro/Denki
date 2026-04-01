from __future__ import annotations

import logging
import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from ui import UI, parse_amount

logger = logging.getLogger("denki.gambling")

# ── House edge ────────────────────────────────────────────────────────────────

COINFLIP_WIN_CHANCE = 0.49

# ── Slots ─────────────────────────────────────────────────────────────────────

SLOT_SYMBOLS: list[str] = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "⚡"]
SLOT_WEIGHTS: list[int] = [30,   25,   20,   15,    6,    3,    1]

SLOT_PAYOUTS: dict[str, float] = {
    "⚡":  10.0,
    "7️⃣":  8.0,
    "💎":   5.0,
    "🍇":   3.0,
    "🍊":   2.5,
    "🍋":   2.0,
    "🍒":   1.5,
    "two":  1.2,
}

# ── Blackjack ─────────────────────────────────────────────────────────────────

CARD_VALUES: dict[str, int] = {
    "A": 11, "2": 2, "3": 3, "4": 4,  "5": 5,
    "6":  6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10,
}
CARD_SUITS:       list[str] = ["♠", "♥", "♦", "♣"]
BLACKJACK_PAYOUT: float     = 1.5
DEALER_STAND:     int       = 17

# ── Guess ─────────────────────────────────────────────────────────────────────

GUESS_MODES: dict[str, dict[str, Any]] = {
    "number_easy": {"label": "Number (1–10)",  "multiplier": 8,  "range": (1, 10)},
    "number_hard": {"label": "Number (1–50)",  "multiplier": 30, "range": (1, 50)},
    "letter":      {"label": "Letter (A–Z)",   "multiplier": 20, "range": None},
}

MIN_BET = 10

# ── Shared helpers ────────────────────────────────────────────────────────────

async def _respond(
    ctx_or_interaction: Any,
    embed: discord.Embed,
    is_slash: bool,
    ephemeral: bool = False,
    view: discord.ui.View | None = None,
) -> None:
    kwargs: dict[str, Any] = {"embed": embed}
    if view:
        kwargs["view"] = view
    if is_slash:
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(**kwargs, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(**kwargs, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.reply(**kwargs)


async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)


async def _maybe_record_cashback(guild_id: int | None, user_id: int, amount: int) -> None:
    """
    Record a gambling loss for cashback if the guild has the feature enabled.
    Silently ignores errors — cashback must never crash the gambling flow.
    """
    if not guild_id or amount <= 0:
        return
    try:
        if await db.get_guild_cashback(guild_id):
            await db.record_loss_for_cashback(user_id, guild_id, amount)
    except Exception as exc:
        logger.warning("_maybe_record_cashback(%d, %d, %d): %s", guild_id, user_id, amount, exc)


# ── Blackjack helpers ─────────────────────────────────────────────────────────

def _new_deck() -> list[str]:
    cards = [f"{v}{s}" for v in CARD_VALUES for s in CARD_SUITS]
    random.shuffle(cards)
    return cards


def _card_value(card: str) -> int:
    return CARD_VALUES.get(card[:-1], 0)


def _hand_total(hand: list[str]) -> int:
    total = sum(_card_value(c) for c in hand)
    aces  = sum(1 for c in hand if c.startswith("A"))
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return total


def _is_blackjack(hand: list[str]) -> bool:
    return len(hand) == 2 and _hand_total(hand) == 21


def _spin_slots() -> list[str]:
    return random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)


def _slot_result(reels: list[str]) -> tuple[bool, float]:
    if reels[0] == reels[1] == reels[2]:
        return True, SLOT_PAYOUTS.get(reels[0], 1.5)
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return True, SLOT_PAYOUTS["two"]
    return False, 0.0


# ── Blackjack view ────────────────────────────────────────────────────────────

class BlackjackView(discord.ui.View):
    """Interactive Hit / Stand buttons for a live blackjack game."""

    def __init__(
        self,
        player_id: int,
        guild_id: int | None,
        deck: list[str],
        player_hand: list[str],
        dealer_hand: list[str],
        amount: int,
        ctx_or_interaction: Any,
        is_slash: bool,
    ) -> None:
        super().__init__(timeout=60)
        self.player_id          = player_id
        self.guild_id           = guild_id
        self.deck               = deck
        self.player_hand        = player_hand
        self.dealer_hand        = dealer_hand
        self.amount             = amount
        self.ctx_or_interaction = ctx_or_interaction
        self.is_slash           = is_slash
        self.finished           = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                embed=UI.error("This isn't your game."), ephemeral=True
            )
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, result: str, payout: int) -> None:
        self.finished = True
        self.stop()

        net = self.amount + payout
        if net > 0:
            wallet_data = await db.update_wallet(self.player_id, net)
        else:
            wallet_data = await db.get_or_create_user(self.player_id)

        await db.log_transaction(
            0 if payout >= 0 else self.player_id,
            self.player_id if payout >= 0 else 0,
            abs(payout) if payout != 0 else self.amount,
            "gamble_win" if payout > 0 else ("gamble_loss" if payout < 0 else "gamble_push"),
        )

        if payout < 0:
            await _maybe_record_cashback(self.guild_id, self.player_id, self.amount)

        await interaction.response.edit_message(
            embed=UI.blackjack_end(
                player_hand=self.player_hand,
                dealer_hand=self.dealer_hand,
                player_total=_hand_total(self.player_hand),
                dealer_total=_hand_total(self.dealer_hand),
                result=result,
                amount=self.amount,
                payout=max(0, payout),
                wallet=int(wallet_data["wallet"]),
            ),
            view=None,
        )

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.player_hand.append(self.deck.pop())
        total = _hand_total(self.player_hand)

        if total > 21:
            return await self._finish(interaction, "Bust — you lose!", -self.amount)

        if total == 21:
            return await self._stand_logic(interaction)

        await interaction.response.edit_message(
            embed=UI.blackjack_start(
                player_hand=self.player_hand,
                dealer_card=self.dealer_hand[0],
                player_total=total,
                amount=self.amount,
            ),
            view=self,
        )

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🤚")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._stand_logic(interaction)

    async def _stand_logic(self, interaction: discord.Interaction) -> None:
        while _hand_total(self.dealer_hand) < DEALER_STAND:
            self.dealer_hand.append(self.deck.pop())

        player_total = _hand_total(self.player_hand)
        dealer_total = _hand_total(self.dealer_hand)

        if dealer_total > 21:
            result, payout = "Dealer busts — you win!", self.amount
        elif player_total > dealer_total:
            result, payout = "You win!", self.amount
        elif player_total == dealer_total:
            result, payout = "Push — tie!", 0
        else:
            result, payout = "Dealer wins!", -self.amount

        await self._finish(interaction, result, payout)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        try:
            while _hand_total(self.dealer_hand) < DEALER_STAND:
                self.dealer_hand.append(self.deck.pop())

            player_total = _hand_total(self.player_hand)
            dealer_total = _hand_total(self.dealer_hand)

            if dealer_total > 21:
                result, payout = "Dealer busts — you win! (auto-stand)", self.amount
            elif player_total > dealer_total:
                result, payout = "You win! (auto-stand)", self.amount
            elif player_total == dealer_total:
                result, payout = "Push — tie! (auto-stand)", 0
            else:
                result, payout = "Dealer wins! (timed out)", -self.amount

            self.finished   = True
            wallet_data     = await db.update_wallet(self.player_id, self.amount + payout)
            await db.log_transaction(
                0 if payout >= 0 else self.player_id,
                self.player_id if payout >= 0 else 0,
                abs(payout),
                "gamble_win" if payout > 0 else "gamble_loss",
            )

            if payout < 0:
                await _maybe_record_cashback(self.guild_id, self.player_id, self.amount)

            channel = self.ctx_or_interaction.channel
            if channel:
                await channel.send(
                    embed=UI.blackjack_end(
                        player_hand=self.player_hand,
                        dealer_hand=self.dealer_hand,
                        player_total=player_total,
                        dealer_total=dealer_total,
                        result=result,
                        amount=self.amount,
                        payout=max(0, payout),
                        wallet=int(wallet_data["wallet"]),
                    )
                )
        except Exception:
            pass


# ── Guess views ───────────────────────────────────────────────────────────────

class GuessView(discord.ui.View):
    """Launches the GuessModal when the player clicks the button."""

    def __init__(
        self,
        player_id: int,
        guild_id: int | None,
        mode: str,
        amount: int,
        multiplier: int,
    ) -> None:
        super().__init__(timeout=60)
        self.player_id  = player_id
        self.guild_id   = guild_id
        self.mode       = mode
        self.amount     = amount
        self.multiplier = multiplier

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                embed=UI.error("This isn't your game."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Guess", style=discord.ButtonStyle.primary, emoji="🎲")
    async def enter_guess(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            GuessModal(
                player_id=self.player_id,
                guild_id=self.guild_id,
                mode=self.mode,
                amount=self.amount,
                multiplier=self.multiplier,
            )
        )
        self.stop()


class GuessModal(discord.ui.Modal, title="Enter your guess"):
    answer = discord.ui.TextInput(
        label="Your answer",
        placeholder="e.g. 7 or B",
        min_length=1,
        max_length=3,
    )

    def __init__(
        self,
        player_id: int,
        guild_id: int | None,
        mode: str,
        amount: int,
        multiplier: int,
    ) -> None:
        super().__init__()
        self.player_id  = player_id
        self.guild_id   = guild_id
        self.mode       = mode
        self.amount     = amount
        self.multiplier = multiplier

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg        = GUESS_MODES[self.mode]
        user_guess = self.answer.value.strip().upper()

        if self.mode == "letter":
            if len(user_guess) != 1 or not user_guess.isalpha():
                return await interaction.response.send_message(
                    embed=UI.error("Please enter a single letter A–Z."), ephemeral=True
                )
            correct = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            won     = user_guess == correct
        else:
            rng: tuple[int, int] = cfg["range"] 
            try:
                guess_int = int(user_guess)
            except ValueError:
                return await interaction.response.send_message(
                    embed=UI.error("Please enter a valid number."), ephemeral=True
                )
            correct_int = random.randint(rng[0], rng[1])
            correct     = str(correct_int)
            won         = guess_int == correct_int

        payout      = int(self.amount * self.multiplier) if won else -self.amount
        wallet_data = await db.update_wallet(self.player_id, payout)
        await db.log_transaction(
            0 if won else self.player_id,
            self.player_id if won else 0,
            abs(payout),
            "gamble_win" if won else "gamble_loss",
        )

        if not won:
            await _maybe_record_cashback(self.guild_id, self.player_id, self.amount)

        await interaction.response.send_message(
            embed=UI.guess(
                mode=str(cfg["label"]),
                answer=correct,
                won=won,
                amount=self.amount,
                payout=payout if won else 0,
                wallet=int(wallet_data["wallet"]),
            )
        )


# ══════════════════════════════════════════════════════════════════════════════

class Gambling(commands.Cog):
    """Gambling commands — coinflip, slots, blackjack, guess."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /coinflip ─────────────────────────────────────────────────────────────

    @app_commands.command(name="coinflip", description="Bet on a coin flip. 49% chance to double your bet.")
    @app_commands.describe(
        choice="heads or tails",
        amount="Amount to bet — enter a number or 'all' for your full balance",
    )
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def coinflip_slash(
        self,
        interaction: discord.Interaction,
        choice: str,
        amount: str,
    ) -> None:
        await self._coinflip(interaction, choice=choice, amount_str=amount, is_slash=True)

    @commands.command(name="coinflip", aliases=["cf"])
    async def coinflip_prefix(
        self,
        ctx: commands.Context[Any],
        choice: str,
        amount: str,
    ) -> None:
        await self._coinflip(ctx, choice=choice, amount_str=amount, is_slash=False)

    async def _coinflip(
        self,
        ctx_or_interaction: Any,
        choice: str,
        amount_str: str,
        is_slash: bool,
    ) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author   = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None

        if choice.lower() not in ("heads", "tails"):
            return await _respond(
                ctx_or_interaction, UI.error("Choose `heads` or `tails`."), is_slash
            )

        user_data = await db.get_or_create_user(author.id)
        wallet    = int(user_data["wallet"])
        amount    = parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(
                ctx_or_interaction, UI.error("Invalid amount. Use a number or `all`."), is_slash
            )
        if amount < MIN_BET:
            return await _respond(
                ctx_or_interaction, UI.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash
            )
        if amount > wallet:
            return await _respond(
                ctx_or_interaction, UI.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash
            )

        won    = random.random() < COINFLIP_WIN_CHANCE
        result = choice.lower() if won else ("tails" if choice.lower() == "heads" else "heads")
        payout = amount if won else -amount

        wallet_data = await db.update_wallet(author.id, payout)
        await db.log_transaction(
            0 if won else author.id,
            author.id if won else 0,
            amount,
            "gamble_win" if won else "gamble_loss",
        )

        if not won:
            await _maybe_record_cashback(guild_id, author.id, amount)

        await _respond(
            ctx_or_interaction,
            UI.coinflip(
                choice=choice.lower(),
                result=result,
                won=won,
                amount=amount,
                wallet=int(wallet_data["wallet"]),
            ),
            is_slash,
        )

    # ── /slots ────────────────────────────────────────────────────────────────

    @app_commands.command(name="slots", description="Spin a 3-reel slot machine.")
    @app_commands.describe(amount="Amount to bet — enter a number or 'all' for your full balance")
    async def slots_slash(self, interaction: discord.Interaction, amount: str) -> None:
        await self._slots(interaction, amount_str=amount, is_slash=True)

    @commands.command(name="slots", aliases=["sl"])
    async def slots_prefix(self, ctx: commands.Context[Any], amount: str) -> None:
        await self._slots(ctx, amount_str=amount, is_slash=False)

    async def _slots(self, ctx_or_interaction: Any, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author   = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None

        user_data = await db.get_or_create_user(author.id)
        wallet    = int(user_data["wallet"])
        amount    = parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(
                ctx_or_interaction, UI.error("Invalid amount. Use a number or `all`."), is_slash
            )
        if amount < MIN_BET:
            return await _respond(
                ctx_or_interaction, UI.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash
            )
        if amount > wallet:
            return await _respond(
                ctx_or_interaction, UI.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash
            )

        reels           = _spin_slots()
        won, multiplier = _slot_result(reels)
        payout          = int(amount * multiplier) if won else -amount

        wallet_data = await db.update_wallet(author.id, payout)
        await db.log_transaction(
            0 if won else author.id,
            author.id if won else 0,
            abs(payout),
            "gamble_win" if won else "gamble_loss",
        )

        if not won:
            await _maybe_record_cashback(guild_id, author.id, amount)

        await _respond(
            ctx_or_interaction,
            UI.slots(
                reels=reels,
                won=won,
                multiplier=multiplier,
                amount=amount,
                payout=payout if won else 0,
                wallet=int(wallet_data["wallet"]),
            ),
            is_slash,
        )

    # ── /blackjack ────────────────────────────────────────────────────────────

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer.")
    @app_commands.describe(amount="Amount to bet — enter a number or 'all' for your full balance")
    async def blackjack_slash(self, interaction: discord.Interaction, amount: str) -> None:
        await self._blackjack(interaction, amount_str=amount, is_slash=True)

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack_prefix(self, ctx: commands.Context[Any], amount: str) -> None:
        await self._blackjack(ctx, amount_str=amount, is_slash=False)

    async def _blackjack(self, ctx_or_interaction: Any, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author   = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None

        user_data = await db.get_or_create_user(author.id)
        wallet    = int(user_data["wallet"])
        amount    = parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(
                ctx_or_interaction, UI.error("Invalid amount. Use a number or `all`."), is_slash
            )
        if amount < MIN_BET:
            return await _respond(
                ctx_or_interaction, UI.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash
            )
        if amount > wallet:
            return await _respond(
                ctx_or_interaction, UI.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash
            )

        # Deduct bet upfront — refunded or doubled on result
        await db.update_wallet(author.id, -amount)

        deck        = _new_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        # Instant blackjack
        if _is_blackjack(player_hand):
            while _hand_total(dealer_hand) < DEALER_STAND:
                dealer_hand.append(deck.pop())

            if _is_blackjack(dealer_hand):
                result, payout = "Push — both blackjack!", 0
            else:
                result, payout = "Blackjack! You win!", int(amount * BLACKJACK_PAYOUT)

            wallet_data = await db.update_wallet(author.id, amount + payout)
            await db.log_transaction(
                0 if payout >= 0 else author.id,
                author.id if payout >= 0 else 0,
                abs(payout) if payout != 0 else amount,
                "gamble_win" if payout > 0 else ("gamble_push" if payout == 0 else "gamble_loss"),
            )
            return await _respond(
                ctx_or_interaction,
                UI.blackjack_end(
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    player_total=_hand_total(player_hand),
                    dealer_total=_hand_total(dealer_hand),
                    result=result,
                    amount=amount,
                    payout=max(0, payout),
                    wallet=int(wallet_data["wallet"]),
                ),
                is_slash,
            )

        # Interactive game
        view = BlackjackView(
            player_id=author.id,
            guild_id=guild_id,
            deck=deck,
            player_hand=player_hand,
            dealer_hand=dealer_hand,
            amount=amount,
            ctx_or_interaction=ctx_or_interaction,
            is_slash=is_slash,
        )
        await _respond(
            ctx_or_interaction,
            UI.blackjack_start(
                player_hand=player_hand,
                dealer_card=dealer_hand[0],
                player_total=_hand_total(player_hand),
                amount=amount,
            ),
            is_slash,
            view=view,
        )

    # ── /guess ────────────────────────────────────────────────────────────────

    @app_commands.command(name="guess", description="Guess a number or letter to win a multiplied payout.")
    @app_commands.describe(
        mode="Game mode",
        amount="Amount to bet — enter a number or 'all' for your full balance",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Number (1–10)  •  8x",  value="number_easy"),
        app_commands.Choice(name="Number (1–50)  •  30x", value="number_hard"),
        app_commands.Choice(name="Letter (A–Z)   •  20x", value="letter"),
    ])
    async def guess_slash(
        self,
        interaction: discord.Interaction,
        mode: str,
        amount: str,
    ) -> None:
        await self._guess_start(interaction, mode=mode, amount_str=amount, is_slash=True)

    @commands.command(name="guess", aliases=["g"])
    async def guess_prefix(
        self,
        ctx: commands.Context[Any],
        mode: str,
        amount: str,
    ) -> None:
        await self._guess_start(ctx, mode=mode, amount_str=amount, is_slash=False)

    async def _guess_start(
        self,
        ctx_or_interaction: Any,
        mode: str,
        amount_str: str,
        is_slash: bool,
    ) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author   = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None

        if mode not in GUESS_MODES:
            valid = ", ".join(f"`{k}`" for k in GUESS_MODES)
            return await _respond(
                ctx_or_interaction, UI.error(f"Invalid mode. Choose: {valid}"), is_slash
            )

        user_data  = await db.get_or_create_user(author.id)
        wallet     = int(user_data["wallet"])
        amount     = parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(
                ctx_or_interaction, UI.error("Invalid amount. Use a number or `all`."), is_slash
            )
        if amount < MIN_BET:
            return await _respond(
                ctx_or_interaction, UI.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash
            )
        if amount > wallet:
            return await _respond(
                ctx_or_interaction, UI.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash
            )

        cfg        = GUESS_MODES[mode]
        multiplier = int(cfg["multiplier"])

        view = GuessView(
            player_id=author.id,
            guild_id=guild_id,
            mode=mode,
            amount=amount,
            multiplier=multiplier,
        )
        await _respond(
            ctx_or_interaction,
            UI.info(
                f"**{cfg['label']}** — bet `¥{amount:,}`\n"
                f"> Multiplier: `{multiplier}x`\n"
                f"> Press **Guess** and type your answer!"
            ),
            is_slash,
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gambling(bot))