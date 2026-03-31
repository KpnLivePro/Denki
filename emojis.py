"""
emojis.py — Denki
Single source of truth for every emoji used across the UI.

Rules:
  • One emoji per semantic concept — never two icons for the same idea.
  • Categories mirror ui.py sections so cross-referencing is instant.
  • All constants are plain str — no wrapping, no classes.
"""
from __future__ import annotations

# ── Feedback ──────────────────────────────────────────────────────────────────
E_SUCCESS   = "✅"
E_ERROR     = "❗"
E_INFO      = "ℹ️"
E_WARN      = "⚠️"
E_CRITICAL  = "‼️"
E_CANCEL    = "❌"
E_CONFIRM   = "✔️"

# ── Time / cooldown ───────────────────────────────────────────────────────────
E_COOLDOWN  = "⏳"
E_CLOCK     = "🕐"
E_CALENDAR  = "📅"

# ── Economy ───────────────────────────────────────────────────────────────────
E_WALLET    = "👛"
E_YEN       = "💴"
E_BANK      = "🏦"
E_INVESTED  = "📈"
E_PAY       = "💸"
E_WORK      = "💼"
E_DAILY     = "📅"       # intentionally same as calendar — daily IS calendar-bound
E_ROB       = "🦹"       # both success and caught: one icon, outcome in text
E_VOTE      = "🗳️"
E_STREAK    = "🔥"

# ── Gambling ──────────────────────────────────────────────────────────────────
E_COIN      = "🪙"
E_SLOTS     = "🎰"
E_CARDS     = "🃏"
E_DICE      = "🎲"

# ── Investing / vault ─────────────────────────────────────────────────────────
E_INVEST    = "📊"
E_VAULT     = "🏛️"
E_POT       = "💰"

# ── Season ────────────────────────────────────────────────────────────────────
E_SEASON    = "🌸"
E_SEASON_END = "🏁"
E_ENDS      = "🗓️"

# ── Shop / inventory ──────────────────────────────────────────────────────────
E_SHOP      = "🏪"
E_BUY       = "🛍️"
E_INVENTORY = "🎒"
E_ITEM      = "📦"
E_ROLE_ITEM = "🎭"
E_BADGE     = "🏅"

# ── Leaderboard ───────────────────────────────────────────────────────────────
E_TROPHY    = "🏆"
E_GLOBAL    = "🌐"
E_MEDAL_1   = "🥇"
E_MEDAL_2   = "🥈"
E_MEDAL_3   = "🥉"
MEDALS      = [E_MEDAL_1, E_MEDAL_2, E_MEDAL_3, "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

# ── Moderation ────────────────────────────────────────────────────────────────
E_WARNING   = "⚠️"       # issued warning (visible to user)
E_BANNED    = "🔨"
E_REPORT    = "📋"
E_SKULL     = "💀"       # elimination in games

# ── Notifications ─────────────────────────────────────────────────────────────
E_ANNOUNCE  = "📢"
E_BELL      = "🔔"
E_TIER_UP   = "🏅"
E_TIER_DOWN = "📉"

# ── Bot / system ──────────────────────────────────────────────────────────────
E_BOT       = "⚡"       # Denki's brand emoji
E_GEAR      = "⚙️"
E_STATS     = "📊"
E_USER      = "👤"
E_GUILD     = "🏠"
E_PING      = "📡"
E_MEMORY    = "🧠"
E_CPU       = "⚙️"
E_PYTHON    = "🐍"
E_ONLINE    = "🟢"
E_OFFLINE   = "🔴"
E_RESTART   = "🔁"
E_DB        = "🗄️"

# ── Navigation / pagination ───────────────────────────────────────────────────
E_PREV      = "◀"
E_NEXT      = "▶"
E_CLOSE     = "✖"
E_REFRESH   = "↺"
E_SKIP      = "⏭️"
E_START     = "▶️"
E_DONE      = "✅"

# ── Help ──────────────────────────────────────────────────────────────────────
E_BOOK      = "📖"
E_USAGE     = "📝"
E_ALIAS     = "🔀"
E_EXAMPLE   = "💡"
E_NOTE      = "ℹ️"

# ── Tea game ──────────────────────────────────────────────────────────────────
E_TEA_BLACK  = "🍵"
E_TEA_GREEN  = "🍃"
E_TEA_WHITE  = "🤍"
E_TEA_RED    = "🔴"
E_TEA_BLUE   = "💙"
E_TEA_AI     = "✨"
E_BOMB       = "💣"
E_EXPLOSION  = "💥"

# ── Arcade ────────────────────────────────────────────────────────────────────
E_MATH       = "🧮"
E_RPS        = "✂️"
E_TTT        = "❌"
E_TTT_O      = "⭕"
E_REACTION   = "⚡"
E_FAKEOUT    = "😂"

RPS_EMOJI: dict[str, str] = {
    "rock":     "🪨",
    "scissors": "✂️",
    "paper":    "📄",
}

# ── Tier badges ───────────────────────────────────────────────────────────────
TIER_EMOJI: dict[int, str] = {
    1: "🥉",
    2: "🥈",
    3: "🥇",
    4: "💎",
    5: "👑",
}