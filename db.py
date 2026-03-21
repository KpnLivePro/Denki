from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logger = logging.getLogger("denki.db")

# ── Client ────────────────────────────────────────────────────────────────────

_url: str = os.getenv("SUPABASE_URL", "")
_key: str = os.getenv("SUPABASE_KEY", "")

if not _url or not _key:
    logger.warning("SUPABASE_URL or SUPABASE_KEY is not set — DB calls will fail.")

try:
    supabase: Client = create_client(_url, _key)
except Exception as e:
    logger.critical(f"Failed to create Supabase client: {e}")
    raise


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row(data: Any) -> dict[str, Any]:
    return dict(data)


def _rows(data: Any) -> list[dict[str, Any]]:
    if not data:
        return []
    return [dict(r) for r in data]


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_user({user_id}): {e}")
        raise


async def get_or_create_user(user_id: int) -> dict[str, Any]:
    try:
        user = await get_user(user_id)
        if user:
            return user
        res = supabase.table("users").insert({
            "user_id":      user_id,
            "wallet":       0,
            "vote_streak":  0,
            "last_vote_at": None,
        }).execute()
        logger.info(f"Created new user {user_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_user({user_id}): {e}")
        raise


async def update_wallet(user_id: int, amount: int) -> dict[str, Any]:
    """Add or subtract from users.wallet. Raises ValueError if balance would go below 0."""
    try:
        user        = await get_or_create_user(user_id)
        new_balance = int(user["wallet"]) + amount
        if new_balance < 0:
            raise ValueError(
                f"Insufficient funds. Wallet: ¥{user['wallet']:,} — tried to change by ¥{amount:,}."
            )
        res = supabase.table("users").update({"wallet": new_balance}).eq("user_id", user_id).execute()
        return _row(res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"update_wallet({user_id}, {amount}): {e}")
        raise


async def get_richest_user() -> Optional[dict[str, Any]]:
    try:
        res = (
            supabase.table("users")
            .select("user_id, wallet")
            .order("wallet", desc=True)
            .limit(1)
            .execute()
        )
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_richest_user(): {e}")
        raise


# ── Vote streak ───────────────────────────────────────────────────────────────

async def get_vote_streak(user_id: int) -> tuple[int, Optional[datetime]]:
    try:
        user   = await get_or_create_user(user_id)
        streak = int(user.get("vote_streak") or 0)
        raw    = user.get("last_vote_at")
        last   = datetime.fromisoformat(str(raw)) if raw else None
        return streak, last
    except Exception as e:
        logger.error(f"get_vote_streak({user_id}): {e}")
        raise


async def update_vote_streak(user_id: int) -> int:
    try:
        streak, last_vote_at = await get_vote_streak(user_id)
        now = datetime.now(timezone.utc)

        if last_vote_at is None:
            new_streak = 1
        else:
            if last_vote_at.tzinfo is None:
                last_vote_at = last_vote_at.replace(tzinfo=timezone.utc)
            hours_since = (now - last_vote_at).total_seconds() / 3600
            new_streak  = streak + 1 if hours_since <= 36 else 1

        supabase.table("users").update({
            "vote_streak":  new_streak,
            "last_vote_at": now.isoformat(),
        }).eq("user_id", user_id).execute()

        logger.info(f"Vote streak updated user={user_id} streak={new_streak}")
        return new_streak
    except Exception as e:
        logger.error(f"update_vote_streak({user_id}): {e}")
        raise


def calculate_streak_bonus(base: int, streak: int) -> int:
    if streak >= 30: return int(base * 2.0)
    if streak >= 14: return int(base * 1.5)
    if streak >= 7:  return int(base * 1.25)
    if streak >= 3:  return int(base * 1.10)
    return base


# ── Guilds ────────────────────────────────────────────────────────────────────

async def get_guild(guild_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("guilds").select("*").eq("guild_id", guild_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_guild({guild_id}): {e}")
        raise


async def get_or_create_guild(guild_id: int) -> dict[str, Any]:
    try:
        guild = await get_guild(guild_id)
        if guild:
            return guild
        res = supabase.table("guilds").insert({
            "guild_id": guild_id,
            "global":   False,
            "wins":     0,
            "tier":     1,
        }).execute()
        logger.info(f"Registered new guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_guild({guild_id}): {e}")
        raise


async def update_guild_meta(guild_id: int, name: str, icon_url: Optional[str]) -> None:
    try:
        await get_or_create_guild(guild_id)
        supabase.table("guilds").update({
            "guild_name": name,
            "icon_url":   icon_url,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Guild meta updated guild_id={guild_id} name={name!r}")
    except Exception as e:
        logger.error(f"update_guild_meta({guild_id}): {e}")
        raise


async def set_guild_global(guild_id: int, is_global: bool) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"global": is_global}).eq("guild_id", guild_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"set_guild_global({guild_id}, {is_global}): {e}")
        raise


async def increment_guild_wins(guild_id: int) -> dict[str, Any]:
    try:
        guild    = await get_or_create_guild(guild_id)
        new_wins = int(guild["wins"]) + 1
        new_tier = _calculate_tier(new_wins)
        res = supabase.table("guilds").update({
            "wins": new_wins,
            "tier": new_tier,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} wins: {new_wins}, tier: {new_tier}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"increment_guild_wins({guild_id}): {e}")
        raise


async def reset_guild_wins(guild_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"wins": 0, "tier": 1}).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} win streak reset")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"reset_guild_wins({guild_id}): {e}")
        raise


def _calculate_tier(wins: int) -> int:
    if wins >= 10: return 5
    if wins >= 7:  return 4
    if wins >= 4:  return 3
    if wins >= 2:  return 2
    return 1


# ── Guild config ──────────────────────────────────────────────────────────────

async def get_guild_config(guild_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("guildconfig").select("*").eq("guild_id", guild_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_guild_config({guild_id}): {e}")
        raise


async def get_or_create_guild_config(guild_id: int) -> dict[str, Any]:
    try:
        config = await get_guild_config(guild_id)
        if config:
            return config
        await get_or_create_guild(guild_id)
        res = supabase.table("guildconfig").insert({
            "guild_id":         guild_id,
            "daily_enabled":    True,
            "work_enabled":     True,
            "rob_enabled":      True,
            "notif_channel":    None,
            "notif_role":       None,
            "shop_enabled":     False,
            "tea_ai_enabled":            False,
            "tea_ai_seasons_remaining":  0,
            "tea_ai_purchased_season":   None,
            "cashback_enabled":          False,
        }).execute()
        logger.info(f"Created guildconfig for guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_guild_config({guild_id}): {e}")
        raise


async def update_guild_config(guild_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    try:
        config = await get_or_create_guild_config(guild_id)
        merged = {**config, **updates}
        earn_flags = [
            bool(merged.get("daily_enabled", True)),
            bool(merged.get("work_enabled",  True)),
            bool(merged.get("rob_enabled",   True)),
        ]
        if not any(earn_flags):
            raise ValueError("Cannot disable all three earning methods. At least one must remain active.")
        res = supabase.table("guildconfig").update(updates).eq("guild_id", guild_id).execute()
        return _row(res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"update_guild_config({guild_id}, {updates}): {e}")
        raise


# ── Server upgrades ───────────────────────────────────────────────────────────

TEA_AI_SEASONS = 3   # how many seasons Tea AI lasts per purchase


async def get_guild_tea_ai(guild_id: int) -> bool:
    """Returns True if this guild has Tea AI active (seasons_remaining > 0). Fails safe to False."""
    try:
        config = await get_guild_config(guild_id)
        if not config:
            return False
        return int(config.get("tea_ai_seasons_remaining", 0)) > 0
    except Exception as e:
        logger.error(f"get_guild_tea_ai({guild_id}): {e}")
        return False


async def get_guild_tea_ai_seasons_remaining(guild_id: int) -> int:
    """Returns how many seasons of Tea AI are left for this guild."""
    try:
        config = await get_guild_config(guild_id)
        return int(config.get("tea_ai_seasons_remaining", 0)) if config else 0
    except Exception as e:
        logger.error(f"get_guild_tea_ai_seasons_remaining({guild_id}): {e}")
        return 0


async def get_guild_cashback(guild_id: int) -> bool:
    """Returns True if this guild has Weekly Cashback enabled."""
    try:
        config = await get_guild_config(guild_id)
        return bool(config.get("cashback_enabled", False)) if config else False
    except Exception as e:
        logger.error(f"get_guild_cashback({guild_id}): {e}")
        return False


async def apply_server_upgrade(guild_id: int, effect: str, season_id: int | None = None) -> None:
    """
    Apply a server_upgrade shop item effect to a guild.
    Tea AI grants TEA_AI_SEASONS seasons — stacks if purchased again while active.
    """
    await get_or_create_guild_config(guild_id)

    if effect == "tea_ai":
        current = await get_guild_tea_ai_seasons_remaining(guild_id)
        new_remaining = current + TEA_AI_SEASONS
        supabase.table("guildconfig").update({
            "tea_ai_enabled":           True,
            "tea_ai_seasons_remaining": new_remaining,
            "tea_ai_purchased_season":  season_id,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Tea AI enabled for guild {guild_id} — {new_remaining} seasons remaining")

    elif effect == "cashback":
        supabase.table("guildconfig").update(
            {"cashback_enabled": True}
        ).eq("guild_id", guild_id).execute()
        logger.info(f"Weekly Cashback enabled for guild {guild_id}")

    else:
        raise ValueError(f"Unknown server upgrade effect: '{effect}'")


async def tick_tea_ai_seasons() -> list[int]:
    """
    Called at the end of every season by run_season_end.
    Decrements tea_ai_seasons_remaining by 1 for all active guilds.
    Disables tea_ai_enabled on any guild that reaches 0.
    Returns list of guild_ids whose Tea AI just expired.
    """
    try:
        res = (
            supabase.table("guildconfig")
            .select("config_id, guild_id, tea_ai_seasons_remaining")
            .gt("tea_ai_seasons_remaining", 0)
            .execute()
        )
        rows    = _rows(res.data)
        expired = []

        for row in rows:
            new_remaining = int(row["tea_ai_seasons_remaining"]) - 1
            update: dict[str, Any] = {"tea_ai_seasons_remaining": new_remaining}
            if new_remaining <= 0:
                update["tea_ai_enabled"] = False
                expired.append(int(row["guild_id"]))
            supabase.table("guildconfig").update(update).eq("config_id", row["config_id"]).execute()

        if expired:
            logger.info(f"Tea AI expired for guilds: {expired}")
        return expired
    except Exception as e:
        logger.error(f"tick_tea_ai_seasons(): {e}")
        return []


# ── Cashback ──────────────────────────────────────────────────────────────────

CASHBACK_RATE      = 0.15   # 15%
CASHBACK_LOSS_TYPES = {
    "gamble_loss", "tea_loss", "greentea_loss",
}


def _current_week_start() -> date:
    """Returns the most recent Monday as a date."""
    today = date.today()
    return today - timedelta(days=today.weekday())


async def record_loss_for_cashback(user_id: int, guild_id: int, amount: int) -> None:
    """
    Accumulate a loss into the cashback ledger for this week.
    Only called if the guild has cashback enabled.
    Only tracks losses > 0.
    """
    if amount <= 0:
        return
    try:
        week_start = _current_week_start().isoformat()

        # Upsert — increment total_lost if row exists, create if not
        existing = (
            supabase.table("cashback")
            .select("cashback_id, total_lost")
            .eq("user_id",    user_id)
            .eq("guild_id",   guild_id)
            .eq("week_start", week_start)
            .execute()
        )
        if existing.data:
            row = _row(existing.data[0])
            supabase.table("cashback").update({
                "total_lost": int(row["total_lost"]) + amount
            }).eq("cashback_id", row["cashback_id"]).execute()
        else:
            supabase.table("cashback").insert({
                "user_id":    user_id,
                "guild_id":   guild_id,
                "week_start": week_start,
                "total_lost": amount,
                "paid_out":   0,
            }).execute()
    except Exception as e:
        logger.error(f"record_loss_for_cashback({user_id}, {guild_id}, {amount}): {e}")


async def get_cashback_claim(user_id: int, guild_id: int) -> Optional[dict[str, Any]]:
    """
    Returns the claimable cashback row for this week if:
    - It's Monday UTC
    - The window is 12am–8am UTC
    - The row hasn't been claimed yet
    - paid_out is 0 (unclaimed)
    """
    try:
        now        = datetime.now(timezone.utc)
        week_start = _current_week_start().isoformat()

        # Must be Monday (weekday 0) between 00:00–08:00 UTC
        if now.weekday() != 0 or now.hour >= 8:
            return None

        res = (
            supabase.table("cashback")
            .select("*")
            .eq("user_id",    user_id)
            .eq("guild_id",   guild_id)
            .eq("week_start", week_start)
            .is_("claimed_at", "null")
            .execute()
        )
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_cashback_claim({user_id}, {guild_id}): {e}")
        return None


async def claim_cashback(user_id: int, guild_id: int) -> Optional[int]:
    """
    Pays out 15% of this week's losses to the user's wallet.
    Returns the amount paid, or None if nothing to claim.
    """
    try:
        row = await get_cashback_claim(user_id, guild_id)
        if not row:
            return None

        total_lost = int(row["total_lost"])
        if total_lost <= 0:
            return None

        payout = max(1, int(total_lost * CASHBACK_RATE))

        await update_wallet(user_id, payout)
        await log_transaction(0, user_id, payout, "cashback_payout")

        supabase.table("cashback").update({
            "paid_out":   payout,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("cashback_id", row["cashback_id"]).execute()

        logger.info(f"Cashback claimed user={user_id} guild={guild_id} payout=¥{payout:,}")
        return payout
    except Exception as e:
        logger.error(f"claim_cashback({user_id}, {guild_id}): {e}")
        return None


async def get_cashback_summary(user_id: int, guild_id: int) -> dict[str, Any]:
    """
    Returns a summary of the user's cashback status for the current week.
    Used by /cashback to show the user what they have pending.
    """
    try:
        now        = datetime.now(timezone.utc)
        week_start = _current_week_start().isoformat()

        res = (
            supabase.table("cashback")
            .select("*")
            .eq("user_id",    user_id)
            .eq("guild_id",   guild_id)
            .eq("week_start", week_start)
            .execute()
        )

        if not res.data:
            return {"total_lost": 0, "paid_out": 0, "claimed": False, "claimable": False, "payout": 0}

        row         = _row(res.data[0])
        total_lost  = int(row["total_lost"])
        paid_out    = int(row["paid_out"])
        claimed     = row.get("claimed_at") is not None
        is_monday   = now.weekday() == 0
        in_window   = is_monday and now.hour < 8
        claimable   = in_window and not claimed and total_lost > 0
        payout      = max(1, int(total_lost * CASHBACK_RATE)) if total_lost > 0 else 0

        return {
            "total_lost": total_lost,
            "paid_out":   paid_out,
            "claimed":    claimed,
            "claimable":  claimable,
            "payout":     payout,
            "in_window":  in_window,
        }
    except Exception as e:
        logger.error(f"get_cashback_summary({user_id}, {guild_id}): {e}")
        return {"total_lost": 0, "paid_out": 0, "claimed": False, "claimable": False, "payout": 0}


# ── Seasons ───────────────────────────────────────────────────────────────────

async def get_active_season() -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("seasons").select("*").eq("active", True).limit(1).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_active_season(): {e}")
        raise


async def get_season(season_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("seasons").select("*").eq("season_id", season_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_season({season_id}): {e}")
        raise


async def create_season(name: str = "New Season", theme: Optional[str] = None) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").insert({
            "name":     name,
            "theme":    theme,
            "tax_rate": 0,
            "active":   True,
        }).execute()
        logger.info(f"Created new season: {name}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"create_season({name}): {e}")
        raise


async def close_season(season_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").update({"active": False}).eq("season_id", season_id).execute()
        logger.info(f"Closed season {season_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"close_season({season_id}): {e}")
        raise


async def update_season(season_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").update(updates).eq("season_id", season_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"update_season({season_id}, {updates}): {e}")
        raise


# ── Banks ─────────────────────────────────────────────────────────────────────

async def get_bank(user_id: int, guild_id: int, season_id: int) -> Optional[dict[str, Any]]:
    try:
        res = (
            supabase.table("banks")
            .select("*")
            .eq("user_id",   user_id)
            .eq("guild_id",  guild_id)
            .eq("season_id", season_id)
            .execute()
        )
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_bank({user_id}, {guild_id}, {season_id}): {e}")
        raise


async def get_or_create_bank(user_id: int, guild_id: int, season_id: int) -> dict[str, Any]:
    try:
        bank = await get_bank(user_id, guild_id, season_id)
        if bank:
            return bank
        res = supabase.table("banks").insert({
            "user_id":      user_id,
            "guild_id":     guild_id,
            "season_id":    season_id,
            "balance":      0,
            "invested":     0,
            "total_earned": 0,
        }).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_bank({user_id}, {guild_id}, {season_id}): {e}")
        raise


async def update_bank_balance(user_id: int, guild_id: int, season_id: int, amount: int) -> dict[str, Any]:
    try:
        bank        = await get_or_create_bank(user_id, guild_id, season_id)
        new_balance = int(bank["balance"]) + amount
        if new_balance < 0:
            raise ValueError(f"Insufficient server bank funds. Balance: ¥{bank['balance']:,}.")
        update_data: dict[str, Any] = {"balance": new_balance}
        if amount > 0:
            update_data["total_earned"] = int(bank["total_earned"]) + amount
        res = supabase.table("banks").update(update_data).eq("bank_id", bank["bank_id"]).execute()
        return _row(res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"update_bank_balance({user_id}, {guild_id}, {season_id}, {amount}): {e}")
        raise


async def add_investment(user_id: int, guild_id: int, season_id: int, amount: int) -> dict[str, Any]:
    try:
        await update_wallet(user_id, -amount)
        bank = await get_or_create_bank(user_id, guild_id, season_id)
        res  = supabase.table("banks").update({
            "invested":     int(bank["invested"])     + amount,
            "total_earned": int(bank["total_earned"]) + amount,
        }).eq("bank_id", bank["bank_id"]).execute()
        logger.info(f"User {user_id} invested ¥{amount:,} in guild {guild_id} season {season_id}")
        return _row(res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"add_investment({user_id}, {guild_id}, {season_id}, {amount}): {e}")
        raise


async def get_top_investors(guild_id: int, season_id: int, limit: int = 7) -> list[dict[str, Any]]:
    try:
        res = (
            supabase.table("banks")
            .select("user_id, invested, total_earned")
            .eq("guild_id",  guild_id)
            .eq("season_id", season_id)
            .order("invested", desc=True)
            .limit(limit)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_top_investors({guild_id}, {season_id}): {e}")
        raise


async def get_season_vault_total(guild_id: int, season_id: int) -> int:
    try:
        res = (
            supabase.table("banks")
            .select("invested")
            .eq("guild_id",  guild_id)
            .eq("season_id", season_id)
            .execute()
        )
        return sum(int(r["invested"]) for r in _rows(res.data))
    except Exception as e:
        logger.error(f"get_season_vault_total({guild_id}, {season_id}): {e}")
        raise


# ── Cooldowns ─────────────────────────────────────────────────────────────────

async def get_cooldown(user_id: int, cooldown_type: str) -> Optional[datetime]:
    try:
        res = (
            supabase.table("cooldowns")
            .select("last_used")
            .eq("user_id", user_id)
            .eq("type",    cooldown_type)
            .execute()
        )
        if res.data:
            return datetime.fromisoformat(str(_row(res.data[0])["last_used"]))
        return None
    except Exception as e:
        logger.error(f"get_cooldown({user_id}, {cooldown_type}): {e}")
        raise


async def set_cooldown(user_id: int, cooldown_type: str) -> None:
    try:
        now      = datetime.now(timezone.utc).isoformat()
        existing = await get_cooldown(user_id, cooldown_type)
        if existing is not None:
            supabase.table("cooldowns").update({"last_used": now}).eq("user_id", user_id).eq("type", cooldown_type).execute()
        else:
            supabase.table("cooldowns").insert({"user_id": user_id, "type": cooldown_type, "last_used": now}).execute()
    except Exception as e:
        logger.error(f"set_cooldown({user_id}, {cooldown_type}): {e}")
        raise


# ── Transactions ──────────────────────────────────────────────────────────────

async def log_transaction(sender_id: int, receiver_id: int, amount: int, tx_type: str) -> dict[str, Any]:
    try:
        res = supabase.table("transactions").insert({
            "sender_id":   sender_id,
            "receiver_id": receiver_id,
            "amount":      amount,
            "type":        tx_type,
        }).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"log_transaction({sender_id}, {receiver_id}, {amount}, {tx_type}): {e}")
        raise


async def get_transaction_history(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    try:
        res = (
            supabase.table("transactions")
            .select("*")
            .or_(f"sender_id.eq.{user_id},receiver_id.eq.{user_id}")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_transaction_history({user_id}): {e}")
        raise


# ── Shop items ────────────────────────────────────────────────────────────────

async def get_shop_items(guild_id: Optional[int] = None) -> list[dict[str, Any]]:
    try:
        query = supabase.table("shopitems").select("*").eq("active", True)
        query = query.is_("guild_id", "null") if guild_id is None else query.eq("guild_id", guild_id)
        return _rows(query.execute().data)
    except Exception as e:
        logger.error(f"get_shop_items({guild_id}): {e}")
        raise


async def get_shop_item(item_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("shopitems").select("*").eq("item_id", item_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_shop_item({item_id}): {e}")
        raise


async def create_shop_item(
    guild_id: Optional[int],
    name: str,
    description: str,
    price: int,
    item_type: str,
    role_id: Optional[int] = None,
    effect: Optional[str] = None,
) -> dict[str, Any]:
    try:
        res = supabase.table("shopitems").insert({
            "guild_id":    guild_id,
            "name":        name,
            "description": description,
            "price":       price,
            "type":        item_type,
            "role_id":     role_id,
            "effect":      effect,
            "active":      True,
        }).execute()
        logger.info(f"Created shop item '{name}' for guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"create_shop_item({guild_id}, {name}): {e}")
        raise


async def disable_shop_item(item_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("shopitems").update({"active": False}).eq("item_id", item_id).execute()
        logger.info(f"Disabled shop item {item_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"disable_shop_item({item_id}): {e}")
        raise


# ── Inventory ─────────────────────────────────────────────────────────────────

async def add_to_inventory(user_id: int, item_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("inventory").insert({"user_id": user_id, "item_id": item_id}).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"add_to_inventory({user_id}, {item_id}): {e}")
        raise


async def get_inventory(user_id: int) -> list[dict[str, Any]]:
    try:
        res = (
            supabase.table("inventory")
            .select("*, shopitems(name, description, type, guild_id)")
            .eq("user_id", user_id)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_inventory({user_id}): {e}")
        raise


async def user_owns_item(user_id: int, item_id: int) -> bool:
    try:
        res = supabase.table("inventory").select("inv_id").eq("user_id", user_id).eq("item_id", item_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"user_owns_item({user_id}, {item_id}): {e}")
        raise


# ── Reports ───────────────────────────────────────────────────────────────────

async def create_report(
    reported_id: int,
    reporter_id: int,
    guild_id: int,
    reason: str,
    wallet_snap: int,
) -> dict[str, Any]:
    try:
        res = supabase.table("reports").insert({
            "reported_id": reported_id,
            "reporter_id": reporter_id,
            "guild_id":    guild_id,
            "reason":      reason,
            "wallet_snap": wallet_snap,
            "status":      "pending",
        }).execute()
        logger.info(f"Report filed against {reported_id} by {reporter_id} in guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"create_report({reported_id}, {reporter_id}): {e}")
        raise


async def get_reports(
    reported_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    try:
        query = supabase.table("reports").select("*").order("created_at", desc=True)
        if reported_id is not None:
            query = query.eq("reported_id", reported_id)
        if status is not None:
            query = query.eq("status", status)
        return _rows(query.execute().data)
    except Exception as e:
        logger.error(f"get_reports({reported_id}, {status}): {e}")
        raise


async def update_report_status(report_id: int, status: str) -> dict[str, Any]:
    try:
        res = supabase.table("reports").update({"status": status}).eq("report_id", report_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"update_report_status({report_id}, {status}): {e}")
        raise


# ── Warns ─────────────────────────────────────────────────────────────────────

async def issue_warn(user_id: int, reason: str, issued_by: int) -> dict[str, Any]:
    try:
        res = supabase.table("warns").insert({
            "user_id":   user_id,
            "reason":    reason,
            "issued_by": issued_by,
            "active":    True,
        }).execute()
        logger.info(f"Warn issued to {user_id} by {issued_by}: {reason}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"issue_warn({user_id}): {e}")
        raise


async def get_active_warns(user_id: int) -> list[dict[str, Any]]:
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = (
            supabase.table("warns")
            .select("*")
            .eq("user_id", user_id)
            .eq("active",  True)
            .gt("expires_at", now)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_active_warns({user_id}): {e}")
        raise


async def count_active_warns(user_id: int) -> int:
    return len(await get_active_warns(user_id))


async def clear_warn(warn_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("warns").update({"active": False}).eq("warn_id", warn_id).execute()
        logger.info(f"Warn {warn_id} cleared")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"clear_warn({warn_id}): {e}")
        raise


# ── Bans ──────────────────────────────────────────────────────────────────────

async def get_ban(user_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("bans").select("*").eq("user_id", user_id).eq("active", True).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_ban({user_id}): {e}")
        raise


async def is_banned(user_id: int) -> bool:
    return (await get_ban(user_id)) is not None


async def ban_user(user_id: int, reason: str, banned_by: int) -> dict[str, Any]:
    try:
        res = supabase.table("bans").upsert({
            "user_id":   user_id,
            "reason":    reason,
            "banned_by": banned_by,
            "active":    True,
        }, on_conflict="user_id").execute()
        logger.info(f"User {user_id} banned by {banned_by}: {reason}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"ban_user({user_id}): {e}")
        raise


async def unban_user(user_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("bans").update({"active": False}).eq("user_id", user_id).execute()
        logger.info(f"User {user_id} unbanned")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"unban_user({user_id}): {e}")
        raise


# ── Leaderboards ──────────────────────────────────────────────────────────────

async def get_leaderboard_server(guild_id: int, limit: int = 7) -> list[dict[str, Any]]:
    try:
        res = (
            supabase.table("banks")
            .select("user_id, users(wallet)")
            .eq("guild_id", guild_id)
            .order("users(wallet)", desc=True)
            .limit(limit)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_leaderboard_server({guild_id}): {e}")
        raise


async def get_leaderboard_global(limit: int = 7) -> list[dict[str, Any]]:
    try:
        res = (
            supabase.table("users")
            .select("user_id, wallet")
            .order("wallet", desc=True)
            .limit(limit)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_leaderboard_global(): {e}")
        raise


async def enrol_guild_global(guild_id: int, guild_name: str) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({
            "global_enrolled": True,
            "global":          True,
            "guild_name":      guild_name,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} enrolled in global leaderboard")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"enrol_guild_global({guild_id}): {e}")
        raise


async def set_guild_invite(guild_id: int, invite_url: str) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"invite_url": invite_url}).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} invite set: {invite_url}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"set_guild_invite({guild_id}): {e}")
        raise


async def get_global_leaderboard_guilds(limit: int = 10) -> list[dict[str, Any]]:
    try:
        res    = supabase.table("guilds").select("guild_id, guild_name, invite_url, icon_url").eq("global_enrolled", True).execute()
        guilds = _rows(res.data)
        if not guilds:
            return []

        results: list[dict[str, Any]] = []
        for guild in guilds:
            gid      = int(guild["guild_id"])
            bank_res = supabase.table("banks").select("user_id").eq("guild_id", gid).execute()
            user_ids = list({int(r["user_id"]) for r in _rows(bank_res.data)})
            if not user_ids:
                wallet_total = 0
            else:
                user_res     = supabase.table("users").select("wallet").in_("user_id", user_ids).execute()
                wallet_total = sum(int(r["wallet"]) for r in _rows(user_res.data))
            results.append({
                "guild_id":     gid,
                "guild_name":   guild.get("guild_name") or f"Server {gid}",
                "invite_url":   guild.get("invite_url"),
                "icon_url":     guild.get("icon_url"),
                "wallet_total": wallet_total,
            })

        results.sort(key=lambda x: x["wallet_total"], reverse=True)
        return results[:limit]
    except Exception as e:
        logger.error(f"get_global_leaderboard_guilds(): {e}")
        raise


# ── Shop management ───────────────────────────────────────────────────────────

SHOP_OPEN_COST: int = 10_000


async def open_server_shop(guild_id: int, season_id: int) -> dict[str, Any]:
    try:
        config = await get_or_create_guild_config(guild_id)
        if config["shop_enabled"]:
            raise ValueError("This server's shop is already open.")

        vault_total = await get_season_vault_total(guild_id, season_id)
        if vault_total < SHOP_OPEN_COST:
            raise ValueError(f"Insufficient vault funds. Need ¥{SHOP_OPEN_COST:,} — vault has ¥{vault_total:,}.")

        top = await get_top_investors(guild_id, season_id, limit=1)
        if not top:
            raise ValueError("No investors found in this season's vault.")

        top_user_id  = int(top[0]["user_id"])
        bank         = await get_or_create_bank(top_user_id, guild_id, season_id)
        new_invested = int(bank["invested"]) - SHOP_OPEN_COST
        if new_invested < 0:
            raise ValueError("Top investor's balance is insufficient to cover the shop cost.")

        supabase.table("banks").update({"invested": new_invested}).eq("bank_id", bank["bank_id"]).execute()
        config_res = supabase.table("guildconfig").update({"shop_enabled": True}).eq("guild_id", guild_id).execute()

        logger.info(f"Server shop opened for guild {guild_id} — ¥{SHOP_OPEN_COST:,} deducted from vault")
        return _row(config_res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"open_server_shop({guild_id}, {season_id}): {e}")
        raise


# ── top.gg ────────────────────────────────────────────────────────────────────

async def check_topgg_vote(user_id: int, bot_id: int, topgg_token: str) -> dict:
    import aiohttp
    url     = f"https://top.gg/api/bots/{bot_id}/check?userId={user_id}"
    headers = {"Authorization": topgg_token}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {
                    "voted":     bool(data.get("voted", 0)),
                    "isWeekend": bool(data.get("isWeekend", False)),
                }
            raise RuntimeError(f"top.gg API returned HTTP {resp.status} for user {user_id}")