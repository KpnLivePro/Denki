from __future__ import annotations

import logging
import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.gambling")

# House edge
COINFLIP_WIN_CHANCE = 0.49

# Slots config
SLOT_SYMBOLS: list[str] = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "⚡"]
SLOT_WEIGHTS: list[int] = [30, 25, 20, 15, 6, 3, 1]   # lower = rarer

SLOT_PAYOUTS: dict[str, float] = {
    "⚡": 10.0,   # three lightning — jackpot
    "7️⃣": 8.0,   # three sevens
    "💎": 5.0,   # three diamonds
    "🍇": 3.0,   # three grapes
    "🍊": 2.5,   # three oranges
    "🍋": 2.0,   # three lemons
    "🍒": 1.5,   # three cherries
    "two": 1.2,  # any two matching
}

# Blackjack config
CARD_VALUES: dict[str, int] = {
    "A": 11, "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6,  "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10,
}
CARD_SUITS: list[str] = ["♠", "♥", "♦", "♣"]
BLACKJACK_PAYOUT = 1.5
DEALER_STAND     = 17

# Guess config
GUESS_MODES: dict[str, dict[str, Any]] = {
    "number_easy": {"label": "Number (1–10)",  "multiplier": 8,  "range": (1, 10)},
    "number_hard": {"label": "Number (1–50)",  "multiplier": 30, "range": (1, 50)},
    "letter":      {"label": "Letter (A–Z)",   "multiplier": 20, "range": None},
}

# Minimum bet
MIN_BET = 10


def _parse_amount(raw: str, wallet: int) -> int | None:
    """Parse 'all' or int string. Returns None if invalid."""
    if raw.lower() == "all":
        return wallet
    try:
        return int(raw)
    except ValueError:
        return None


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


# Blackjack helpers

def _new_deck() -> list[str]:
    cards = [f"{v}{s}" for v in CARD_VALUES for s in CARD_SUITS]
    random.shuffle(cards)
    return cards


def _card_value(card: str) -> int:
    rank = card[:-1]  # strip suit
    return CARD_VALUES.get(rank, 0)


def _hand_total(hand: list[str]) -> int:
    total = sum(_card_value(c) for c in hand)
    aces = sum(1 for c in hand if c.startswith("A"))
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _is_blackjack(hand: list[str]) -> bool:
    return len(hand) == 2 and _hand_total(hand) == 21


def _spin_slots() -> list[str]:
    return random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)


def _slot_result(reels: list[str]) -> tuple[bool, float]:
    """Returns (won, multiplier)."""
    if reels[0] == reels[1] == reels[2]:
        mult = SLOT_PAYOUTS.get(reels[0], 1.5)
        return True, mult
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return True, SLOT_PAYOUTS["two"]
    return False, 0.0


class BlackjackView(discord.ui.View):
    """Interactive Hit / Stand buttons for blackjack."""

    def __init__(
        self,
        player_id: int,
        deck: list[str],
        player_hand: list[str],
        dealer_hand: list[str],
        amount: int,
        ctx_or_interaction: Any,
        is_slash: bool,
    ) -> None:
        super().__init__(timeout=60)
        self.player_id       = player_id
        self.deck            = deck
        self.player_hand     = player_hand
        self.dealer_hand     = dealer_hand
        self.amount          = amount
        self.ctx_or_interaction = ctx_or_interaction
        self.is_slash        = is_slash
        self.finished        = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                embed=Embeds.error("This isn't your game."), ephemeral=True
            )
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, result: str, payout: int) -> None:
        self.finished = True
        self.stop()

        # payout > 0 means player won their bet back PLUS profit (so refund stake + winnings)
        # payout == 0 means push (refund stake only)
        # payout < 0 means loss (stake already deducted — no further change)
        net = self.amount + payout  # amount to return: stake back + profit (or 0 on loss)
        if net > 0:
            wallet_data = await db.update_wallet(self.player_id, net)
        else:
            # Loss: stake was already deducted on game start, nothing to return
            wallet_data = await db.get_or_create_user(self.player_id)

        await db.log_transaction(
            0 if payout >= 0 else self.player_id,
            self.player_id if payout >= 0 else 0,
            abs(payout) if payout != 0 else self.amount,
            "gamble_win" if payout > 0 else ("gamble_loss" if payout < 0 else "gamble_push"),
        )

        embed = Embeds.blackjack_end(
            player_hand=self.player_hand,
            dealer_hand=self.dealer_hand,
            player_total=_hand_total(self.player_hand),
            dealer_total=_hand_total(self.dealer_hand),
            result=result,
            amount=self.amount,
            payout=max(0, payout),
            wallet=int(wallet_data["wallet"]),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.player_hand.append(self.deck.pop())
        total = _hand_total(self.player_hand)

        if total > 21:
            await self._finish(interaction, "Bust — you lose!", -self.amount)
            return

        if total == 21:
            await self._stand_logic(interaction)
            return

        # Update embed to show new hand
        embed = Embeds.blackjack_start(
            player_hand=self.player_hand,
            dealer_card=self.dealer_hand[0],
            player_total=total,
            amount=self.amount,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🤚")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._stand_logic(interaction)

    async def _stand_logic(self, interaction: discord.Interaction) -> None:
        # Dealer draws until 17+
        while _hand_total(self.dealer_hand) < DEALER_STAND:
            self.dealer_hand.append(self.deck.pop())

        player_total = _hand_total(self.player_hand)
        dealer_total = _hand_total(self.dealer_hand)

        if dealer_total > 21:
            result = "Dealer busts — you win!"
            payout = self.amount
        elif player_total > dealer_total:
            result = "You win!"
            payout = self.amount
        elif player_total == dealer_total:
            result = "Push — tie!"
            payout = 0
        else:
            result = "Dealer wins!"
            payout = -self.amount

        await self._finish(interaction, result, payout)

    async def on_timeout(self) -> None:
        if not self.finished:
            try:
                # Simulate a stand interaction to resolve the game cleanly
                while _hand_total(self.dealer_hand) < DEALER_STAND:
                    self.dealer_hand.append(self.deck.pop())

                player_total = _hand_total(self.player_hand)
                dealer_total = _hand_total(self.dealer_hand)

                if dealer_total > 21:
                    result = "Dealer busts — you win! (auto-stand)"
                    payout = self.amount
                elif player_total > dealer_total:
                    result = "You win! (auto-stand)"
                    payout = self.amount
                elif player_total == dealer_total:
                    result = "Push — tie! (auto-stand)"
                    payout = 0
                else:
                    result = "Dealer wins! (auto-stand — timed out)"
                    payout = -self.amount

                self.finished = True
                wallet_data = await db.update_wallet(self.player_id, self.amount + payout)
                await db.log_transaction(
                    0 if payout >= 0 else self.player_id,
                    self.player_id if payout >= 0 else 0,
                    abs(payout),
                    "gamble_win" if payout > 0 else "gamble_loss",
                )
                embed = Embeds.blackjack_end(
                    player_hand=self.player_hand,
                    dealer_hand=self.dealer_hand,
                    player_total=player_total,
                    dealer_total=dealer_total,
                    result=result,
                    amount=self.amount,
                    payout=max(0, payout),
                    wallet=int(wallet_data["wallet"]),
                )
                if self.is_slash:
                    channel = self.ctx_or_interaction.channel
                else:
                    channel = self.ctx_or_interaction.channel
                if channel:
                    await channel.send(embed=embed)
            except Exception:
                pass


class Gambling(commands.Cog):
    """Gambling commands — coinflip, slots, blackjack, guess."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # Coinflip

    @app_commands.command(name="coinflip", description="Bet on a coin flip. 49% chance to double your bet.")
    @app_commands.describe(choice="heads or tails", amount="Amount to bet — enter a number or 'all' for your full balance")
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

    async def _coinflip(self, ctx_or_interaction: Any, choice: str, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author

        if choice.lower() not in ("heads", "tails"):
            return await _respond(ctx_or_interaction, Embeds.error("Choose `heads` or `tails`."), is_slash)

        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])
        amount = _parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(ctx_or_interaction, Embeds.error("Invalid amount. Use a number or `all`."), is_slash)
        if amount < MIN_BET:
            return await _respond(ctx_or_interaction, Embeds.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash)
        if amount > wallet:
            return await _respond(ctx_or_interaction, Embeds.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash)

        won = random.random() < COINFLIP_WIN_CHANCE
        result = choice.lower() if won else ("tails" if choice.lower() == "heads" else "heads")

        payout = amount if won else -amount
        wallet_data = await db.update_wallet(author.id, payout)
        await db.log_transaction(
            0 if won else author.id,
            author.id if won else 0,
            amount,
            "gamble_win" if won else "gamble_loss",
        )

        embed = Embeds.coinflip(
            choice=choice.lower(),
            result=result,
            won=won,
            amount=amount,
            wallet=int(wallet_data["wallet"]),
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # Slots

    @app_commands.command(name="slots", description="Spin a 3-reel slot machine.")
    @app_commands.describe(amount="Amount to bet — enter a number or 'all' for your full balance")
    async def slots_slash(self, interaction: discord.Interaction, amount: str) -> None:
        await self._slots(interaction, amount_str=amount, is_slash=True)

    @commands.command(name="slots", aliases=["sl"])
    async def slots_prefix(self, ctx: commands.Context[Any], amount: str) -> None:
        await self._slots(ctx, amount_str=amount, is_slash=False)

    async def _slots(self, ctx_or_interaction: Any, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author

        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])
        amount = _parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(ctx_or_interaction, Embeds.error("Invalid amount. Use a number or `all`."), is_slash)
        if amount < MIN_BET:
            return await _respond(ctx_or_interaction, Embeds.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash)
        if amount > wallet:
            return await _respond(ctx_or_interaction, Embeds.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash)

        reels = _spin_slots()
        won, multiplier = _slot_result(reels)
        payout = int(amount * multiplier) if won else -amount

        wallet_data = await db.update_wallet(author.id, payout)
        await db.log_transaction(
            0 if won else author.id,
            author.id if won else 0,
            abs(payout),
            "gamble_win" if won else "gamble_loss",
        )

        embed = Embeds.slots(
            reels=reels,
            won=won,
            multiplier=multiplier,
            amount=amount,
            payout=payout if won else 0,
            wallet=int(wallet_data["wallet"]),
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # Blackjack

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer.")
    @app_commands.describe(amount="Amount to bet — enter a number or 'all' for your full balance")
    async def blackjack_slash(self, interaction: discord.Interaction, amount: str) -> None:
        await self._blackjack(interaction, amount_str=amount, is_slash=True)

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack_prefix(self, ctx: commands.Context[Any], amount: str) -> None:
        await self._blackjack(ctx, amount_str=amount, is_slash=False)

    async def _blackjack(self, ctx_or_interaction: Any, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author

        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])
        amount = _parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(ctx_or_interaction, Embeds.error("Invalid amount. Use a number or `all`."), is_slash)
        if amount < MIN_BET:
            return await _respond(ctx_or_interaction, Embeds.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash)
        if amount > wallet:
            return await _respond(ctx_or_interaction, Embeds.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash)

        # Deduct bet upfront — refunded or doubled on result
        await db.update_wallet(author.id, -amount)

        deck = _new_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        # Instant blackjack check
        if _is_blackjack(player_hand):
            while _hand_total(dealer_hand) < DEALER_STAND:
                dealer_hand.append(deck.pop())

            if _is_blackjack(dealer_hand):
                result = "Push — both blackjack!"
                payout = 0
            else:
                result = "Blackjack! You win!"
                payout = int(amount * BLACKJACK_PAYOUT)

            wallet_data = await db.update_wallet(author.id, amount + payout)
            await db.log_transaction(0, author.id, payout, "gamble_win" if payout > 0 else "gamble_loss")

            embed = Embeds.blackjack_end(
                player_hand=player_hand,
                dealer_hand=dealer_hand,
                player_total=_hand_total(player_hand),
                dealer_total=_hand_total(dealer_hand),
                result=result,
                amount=amount,
                payout=payout,
                wallet=int(wallet_data["wallet"]),
            )
            return await _respond(ctx_or_interaction, embed, is_slash)

        # Interactive game
        view = BlackjackView(
            player_id=author.id,
            deck=deck,
            player_hand=player_hand,
            dealer_hand=dealer_hand,
            amount=amount,
            ctx_or_interaction=ctx_or_interaction,
            is_slash=is_slash,
        )

        embed = Embeds.blackjack_start(
            player_hand=player_hand,
            dealer_card=dealer_hand[0],
            player_total=_hand_total(player_hand),
            amount=amount,
        )
        await _respond(ctx_or_interaction, embed, is_slash, view=view)

    # Guess

    @app_commands.command(name="guess", description="Guess a number or letter to win a multiplied payout.")
    @app_commands.describe(mode="Game mode", amount="Amount to bet — enter a number or 'all' for your full balance")
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

    async def _guess_start(self, ctx_or_interaction: Any, mode: str, amount_str: str, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author

        if mode not in GUESS_MODES:
            valid = ", ".join(f"`{k}`" for k in GUESS_MODES)
            return await _respond(ctx_or_interaction, Embeds.error(f"Invalid mode. Choose: {valid}"), is_slash)

        user_data = await db.get_or_create_user(author.id)
        wallet = int(user_data["wallet"])
        amount = _parse_amount(amount_str, wallet)

        if amount is None:
            return await _respond(ctx_or_interaction, Embeds.error("Invalid amount. Use a number or `all`."), is_slash)
        if amount < MIN_BET:
            return await _respond(ctx_or_interaction, Embeds.error(f"Minimum bet is ¥{MIN_BET:,}."), is_slash)
        if amount > wallet:
            return await _respond(ctx_or_interaction, Embeds.error(f"Insufficient funds. Wallet: ¥{wallet:,}."), is_slash)

        cfg = GUESS_MODES[mode]
        label: str = str(cfg["label"])
        multiplier: int = int(cfg["multiplier"])

        # Build the prompt and wait for user reply
        view = GuessView(
            player_id=author.id,
            mode=mode,
            amount=amount,
            multiplier=multiplier,
            ctx_or_interaction=ctx_or_interaction,
            is_slash=is_slash,
        )

        prompt = Embeds.info(
            f"**{label}** — bet ¥{amount:,}\n"
            f"> Multiplier: `{multiplier}x`\n"
            f"> Type your answer in the box below!"
        )
        await _respond(ctx_or_interaction, prompt, is_slash, view=view)


class GuessView(discord.ui.View):
    """Modal-based guess input."""

    def __init__(
        self,
        player_id: int,
        mode: str,
        amount: int,
        multiplier: int,
        ctx_or_interaction: Any,
        is_slash: bool,
    ) -> None:
        super().__init__(timeout=60)
        self.player_id          = player_id
        self.mode               = mode
        self.amount             = amount
        self.multiplier         = multiplier
        self.ctx_or_interaction = ctx_or_interaction
        self.is_slash           = is_slash

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                embed=Embeds.error("This isn't your game."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Enter your guess", style=discord.ButtonStyle.primary, emoji="🎲")
    async def enter_guess(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = GuessModal(
            player_id=self.player_id,
            mode=self.mode,
            amount=self.amount,
            multiplier=self.multiplier,
        )
        await interaction.response.send_modal(modal)
        self.stop()


class GuessModal(discord.ui.Modal, title="Enter your guess"):
    answer = discord.ui.TextInput(
        label="Your guess",
        placeholder="e.g. 7 or B",
        min_length=1,
        max_length=3,
    )

    def __init__(self, player_id: int, mode: str, amount: int, multiplier: int) -> None:
        super().__init__()
        self.player_id  = player_id
        self.mode       = mode
        self.amount     = amount
        self.multiplier = multiplier

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg = GUESS_MODES[self.mode]
        user_guess = self.answer.value.strip().upper()

        if self.mode == "letter":
            if len(user_guess) != 1 or not user_guess.isalpha():
                await interaction.response.send_message(
                    embed=Embeds.error("Please enter a single letter A–Z."), ephemeral=True
                )
                return
            correct = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            won = user_guess == correct
        else:
            rng: tuple[int, int] = cfg["range"]  # type: ignore[assignment]
            try:
                guess_int = int(user_guess)
            except ValueError:
                await interaction.response.send_message(
                    embed=Embeds.error("Please enter a valid number."), ephemeral=True
                )
                return
            correct_int = random.randint(rng[0], rng[1])
            correct = str(correct_int)
            won = guess_int == correct_int

        payout = int(self.amount * self.multiplier) if won else -self.amount
        wallet_data = await db.update_wallet(self.player_id, payout)
        await db.log_transaction(
            0 if won else self.player_id,
            self.player_id if won else 0,
            abs(payout),
            "gamble_win" if won else "gamble_loss",
        )

        embed = Embeds.guess(
            mode=str(cfg["label"]),
            answer=correct,
            won=won,
            amount=self.amount,
            payout=payout if won else 0,
            wallet=int(wallet_data["wallet"]),
        )
        await interaction.response.send_message(embed=embed)



async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    """Defer a slash interaction immediately to extend the 3-second response window."""
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gambling(bot))