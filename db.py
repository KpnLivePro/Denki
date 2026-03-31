from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logger = logging.getLogger("denki.db")

# ── Client (singleton — correct for a persistent container) ───────────────────

_url: str = os.getenv("SUPABASE_URL", "")
_key: str = os.getenv("SUPABASE_KEY", "")

if not _url or not _key:
    logger.warning("SUPABASE_URL or SUPABASE_KEY is not set — DB calls will fail.")

try:
    supabase: Client = create_client(_url, _key)
except Exception as _exc:
    logger.critical("Failed to create Supabase client: %s", _exc)
    raise

# ── Internal helpers ──────────────────────────────────────────────────────────

def _row(data: Any) -> dict[str, Any]:
    """Return first element of a result list as a dict, or empty dict."""
    if not data:
        return {}
    item = data[0] if isinstance(data, list) else data
    return dict(item)


def _rows(data: Any) -> list[dict[str, Any]]:
    if not data:
        return []
    return [dict(r) for r in data]


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_user(%d): %s", user_id, exc)
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
        logger.info("Created new user %d", user_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("get_or_create_user(%d): %s", user_id, exc)
        raise


async def update_wallet(user_id: int, amount: int) -> dict[str, Any]:
    """Add/subtract from wallet. Raises ValueError if balance would go negative."""
    try:
        user        = await get_or_create_user(user_id)
        new_balance = int(user["wallet"]) + amount
        if new_balance < 0:
            raise ValueError(
                f"Insufficient funds. Wallet: ¥{user['wallet']:,} — tried to change by ¥{amount:,}."
            )
        res = supabase.table("users").update({"wallet": new_balance}).eq("user_id", user_id).execute()
        return _row(res.data)
    except ValueError:
        raise
    except Exception as exc:
        logger.error("update_wallet(%d, %d): %s", user_id, amount, exc)
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
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_richest_user(): %s", exc)
        raise


# ── Vote streak ───────────────────────────────────────────────────────────────

async def get_vote_streak(user_id: int) -> tuple[int, Optional[datetime]]:
    try:
        user   = await get_or_create_user(user_id)
        streak = int(user.get("vote_streak") or 0)
        raw    = user.get("last_vote_at")
        last   = datetime.fromisoformat(str(raw)) if raw else None
        return streak, last
    except Exception as exc:
        logger.error("get_vote_streak(%d): %s", user_id, exc)
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

        logger.info("Vote streak updated user=%d streak=%d", user_id, new_streak)
        return new_streak
    except Exception as exc:
        logger.error("update_vote_streak(%d): %s", user_id, exc)
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
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_guild(%d): %s", guild_id, exc)
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
        logger.info("Registered new guild %d", guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("get_or_create_guild(%d): %s", guild_id, exc)
        raise


async def update_guild_meta(guild_id: int, name: str, icon_url: Optional[str]) -> None:
    try:
        await get_or_create_guild(guild_id)
        supabase.table("guilds").update({
            "guild_name": name,
            "icon_url":   icon_url,
        }).eq("guild_id", guild_id).execute()
    except Exception as exc:
        logger.error("update_guild_meta(%d): %s", guild_id, exc)
        raise


async def set_guild_global(guild_id: int, is_global: bool) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"global": is_global}).eq("guild_id", guild_id).execute()
        return _row(res.data)
    except Exception as exc:
        logger.error("set_guild_global(%d, %s): %s", guild_id, is_global, exc)
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
        logger.info("Guild %d wins=%d tier=%d", guild_id, new_wins, new_tier)
        return _row(res.data)
    except Exception as exc:
        logger.error("increment_guild_wins(%d): %s", guild_id, exc)
        raise


async def reset_guild_wins(guild_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"wins": 0, "tier": 1}).eq("guild_id", guild_id).execute()
        logger.info("Guild %d win streak reset", guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("reset_guild_wins(%d): %s", guild_id, exc)
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
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_guild_config(%d): %s", guild_id, exc)
        raise


async def get_or_create_guild_config(guild_id: int) -> dict[str, Any]:
    try:
        config = await get_guild_config(guild_id)
        if config:
            return config
        await get_or_create_guild(guild_id)
        res = supabase.table("guildconfig").insert({
            "guild_id":      guild_id,
            "daily_enabled": True,
            "work_enabled":  True,
            "rob_enabled":   True,
            "notif_channel": None,
            "notif_role":    None,
            "shop_enabled":  False,
        }).execute()
        logger.info("Created guildconfig for guild %d", guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("get_or_create_guild_config(%d): %s", guild_id, exc)
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
            raise ValueError(
                "Cannot disable all three earning methods. At least one must remain active."
            )
        res = supabase.table("guildconfig").update(updates).eq("guild_id", guild_id).execute()
        return _row(res.data)
    except ValueError:
        raise
    except Exception as exc:
        logger.error("update_guild_config(%d): %s", guild_id, exc)
        raise


# ── Premium guild flags (read-only helpers used by cogs) ──────────────────────

async def get_guild_tea_ai(guild_id: int) -> bool:
    """Return True if Tea AI is active for this guild (seasons_remaining > 0)."""
    try:
        config = await get_guild_config(guild_id)
        if not config:
            return False
        return int(config.get("tea_ai_seasons_remaining", 0) or 0) > 0
    except Exception as exc:
        logger.error("get_guild_tea_ai(%d): %s", guild_id, exc)
        return False


async def get_guild_tea_ai_seasons_remaining(guild_id: int) -> int:
    try:
        config = await get_guild_config(guild_id)
        return int((config or {}).get("tea_ai_seasons_remaining", 0) or 0)
    except Exception as exc:
        logger.error("get_guild_tea_ai_seasons_remaining(%d): %s", guild_id, exc)
        return 0


async def get_guild_cashback(guild_id: int) -> bool:
    """Return True if Weekly Cashback is enabled for this guild."""
    try:
        config = await get_guild_config(guild_id)
        return bool((config or {}).get("cashback_enabled", False))
    except Exception as exc:
        logger.error("get_guild_cashback(%d): %s", guild_id, exc)
        return False


# ── Server upgrade application ────────────────────────────────────────────────

async def apply_server_upgrade(guild_id: int, effect: str, season_id: Optional[int] = None) -> None:
    """
    Apply a purchased server upgrade effect to guildconfig.

    Supported effects:
      tea_ai   — increments tea_ai_seasons_remaining by 3 (stacks)
      cashback — enables cashback_enabled flag (one-time)
    """
    try:
        config = await get_or_create_guild_config(guild_id)
        if effect == "tea_ai":
            current  = int(config.get("tea_ai_seasons_remaining", 0) or 0)
            new_val  = current + 3
            supabase.table("guildconfig").update({
                "tea_ai_seasons_remaining": new_val,
                "tea_ai_enabled":           True,
            }).eq("guild_id", guild_id).execute()
            logger.info(
                "Tea AI upgraded guild=%d seasons_remaining=%d", guild_id, new_val
            )
        elif effect == "cashback":
            if config.get("cashback_enabled"):
                raise ValueError("This server already has Weekly Cashback unlocked.")
            supabase.table("guildconfig").update({
                "cashback_enabled": True,
            }).eq("guild_id", guild_id).execute()
            logger.info("Cashback enabled guild=%d", guild_id)
        else:
            raise ValueError(f"Unknown upgrade effect: {effect!r}")
    except ValueError:
        raise
    except Exception as exc:
        logger.error("apply_server_upgrade(%d, %s): %s", guild_id, effect, exc)
        raise


async def tick_tea_ai_seasons() -> list[int]:
    """
    Decrement tea_ai_seasons_remaining for all guilds that have it > 0.
    Called at season end. Returns list of guild_ids whose subscription expired (hit 0).
    """
    try:
        res = (
            supabase.table("guildconfig")
            .select("guild_id, tea_ai_seasons_remaining")
            .gt("tea_ai_seasons_remaining", 0)
            .execute()
        )
        rows     = _rows(res.data)
        expired: list[int] = []

        for row in rows:
            guild_id = int(row["guild_id"])
            new_val  = int(row["tea_ai_seasons_remaining"]) - 1
            updates: dict[str, Any] = {"tea_ai_seasons_remaining": new_val}
            if new_val <= 0:
                updates["tea_ai_enabled"] = False
                expired.append(guild_id)
            supabase.table("guildconfig").update(updates).eq("guild_id", guild_id).execute()

        return expired
    except Exception as exc:
        logger.error("tick_tea_ai_seasons(): %s", exc)
        return []


# ── Cashback ──────────────────────────────────────────────────────────────────

def _cashback_window_open() -> bool:
    """Monday 00:00–08:00 UTC."""
    now = datetime.now(timezone.utc)
    return now.weekday() == 0 and now.hour < 8


async def record_loss_for_cashback(user_id: int, guild_id: int, amount: int) -> None:
    """Accumulate gambling losses in the cashback table for weekly payout."""
    try:
        # Week key: ISO year + week number keeps records tidy
        now      = datetime.now(timezone.utc)
        week_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"

        res = (
            supabase.table("cashback")
            .select("*")
            .eq("user_id",  user_id)
            .eq("guild_id", guild_id)
            .eq("week_key", week_key)
            .execute()
        )
        if res.data:
            row        = _row(res.data)
            new_total  = int(row["total_lost"]) + amount
            supabase.table("cashback").update({
                "total_lost": new_total,
            }).eq("cb_id", row["cb_id"]).execute()
        else:
            supabase.table("cashback").insert({
                "user_id":    user_id,
                "guild_id":   guild_id,
                "week_key":   week_key,
                "total_lost": amount,
                "claimed":    False,
                "paid_out":   0,
            }).execute()
    except Exception as exc:
        logger.error("record_loss_for_cashback(%d, %d, %d): %s", user_id, guild_id, amount, exc)


async def get_cashback_summary(user_id: int, guild_id: int) -> dict[str, Any]:
    """
    Return a dict with cashback status for the current week:
      total_lost, payout, claimed, paid_out, claimable, in_window
    """
    try:
        now      = datetime.now(timezone.utc)
        week_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
        in_window = _cashback_window_open()

        res = (
            supabase.table("cashback")
            .select("*")
            .eq("user_id",  user_id)
            .eq("guild_id", guild_id)
            .eq("week_key", week_key)
            .execute()
        )

        if not res.data:
            return {
                "total_lost": 0,
                "payout":     0,
                "claimed":    False,
                "paid_out":   0,
                "claimable":  False,
                "in_window":  in_window,
            }

        row        = _row(res.data)
        total_lost = int(row["total_lost"])
        claimed    = bool(row["claimed"])
        paid_out   = int(row.get("paid_out", 0))
        payout     = int(total_lost * 0.15)
        claimable  = in_window and not claimed and payout > 0

        return {
            "total_lost": total_lost,
            "payout":     payout,
            "claimed":    claimed,
            "paid_out":   paid_out,
            "claimable":  claimable,
            "in_window":  in_window,
        }
    except Exception as exc:
        logger.error("get_cashback_summary(%d, %d): %s", user_id, guild_id, exc)
        return {
            "total_lost": 0, "payout": 0, "claimed": False,
            "paid_out": 0, "claimable": False, "in_window": False,
        }


async def claim_cashback(user_id: int, guild_id: int) -> Optional[int]:
    """
    Claim the weekly cashback. Returns the payout amount, or None if not eligible.
    Marks the record as claimed and pays the wallet.
    """
    try:
        summary = await get_cashback_summary(user_id, guild_id)
        if not summary["claimable"]:
            return None

        payout   = summary["payout"]
        now      = datetime.now(timezone.utc)
        week_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"

        # Mark claimed
        supabase.table("cashback").update({
            "claimed":  True,
            "paid_out": payout,
        }).eq("user_id", user_id).eq("guild_id", guild_id).eq("week_key", week_key).execute()

        # Pay wallet
        await update_wallet(user_id, payout)
        await log_transaction(0, user_id, payout, "cashback")

        logger.info("Cashback claimed user=%d guild=%d payout=¥%d", user_id, guild_id, payout)
        return payout
    except Exception as exc:
        logger.error("claim_cashback(%d, %d): %s", user_id, guild_id, exc)
        return None


# ── Seasons ───────────────────────────────────────────────────────────────────

async def get_active_season() -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("seasons").select("*").eq("active", True).limit(1).execute()
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_active_season(): %s", exc)
        raise


async def get_season(season_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("seasons").select("*").eq("season_id", season_id).execute()
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_season(%d): %s", season_id, exc)
        raise


async def create_season(name: str = "New Season", theme: Optional[str] = None) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").insert({
            "name":     name,
            "theme":    theme,
            "tax_rate": 0,
            "active":   True,
        }).execute()
        logger.info("Created new season: %s", name)
        return _row(res.data)
    except Exception as exc:
        logger.error("create_season(%s): %s", name, exc)
        raise


async def close_season(season_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").update({"active": False}).eq("season_id", season_id).execute()
        logger.info("Closed season %d", season_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("close_season(%d): %s", season_id, exc)
        raise


async def update_season(season_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    try:
        res = supabase.table("seasons").update(updates).eq("season_id", season_id).execute()
        return _row(res.data)
    except Exception as exc:
        logger.error("update_season(%d): %s", season_id, exc)
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
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_bank(%d, %d, %d): %s", user_id, guild_id, season_id, exc)
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
        return _row(res.data)
    except Exception as exc:
        logger.error("get_or_create_bank(%d, %d, %d): %s", user_id, guild_id, season_id, exc)
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
        return _row(res.data)
    except ValueError:
        raise
    except Exception as exc:
        logger.error("update_bank_balance: %s", exc)
        raise


async def add_investment(user_id: int, guild_id: int, season_id: int, amount: int) -> dict[str, Any]:
    try:
        await update_wallet(user_id, -amount)
        bank = await get_or_create_bank(user_id, guild_id, season_id)
        res  = supabase.table("banks").update({
            "invested":     int(bank["invested"])     + amount,
            "total_earned": int(bank["total_earned"]) + amount,
        }).eq("bank_id", bank["bank_id"]).execute()
        logger.info("User %d invested ¥%d in guild %d season %d", user_id, amount, guild_id, season_id)
        return _row(res.data)
    except ValueError:
        raise
    except Exception as exc:
        logger.error("add_investment(%d, %d, %d, %d): %s", user_id, guild_id, season_id, amount, exc)
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
    except Exception as exc:
        logger.error("get_top_investors(%d, %d): %s", guild_id, season_id, exc)
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
    except Exception as exc:
        logger.error("get_season_vault_total(%d, %d): %s", guild_id, season_id, exc)
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
            return datetime.fromisoformat(str(_row(res.data)["last_used"]))
        return None
    except Exception as exc:
        logger.error("get_cooldown(%d, %s): %s", user_id, cooldown_type, exc)
        raise


async def set_cooldown(user_id: int, cooldown_type: str) -> None:
    try:
        now      = datetime.now(timezone.utc).isoformat()
        existing = await get_cooldown(user_id, cooldown_type)
        if existing is not None:
            supabase.table("cooldowns").update(
                {"last_used": now}
            ).eq("user_id", user_id).eq("type", cooldown_type).execute()
        else:
            supabase.table("cooldowns").insert(
                {"user_id": user_id, "type": cooldown_type, "last_used": now}
            ).execute()
    except Exception as exc:
        logger.error("set_cooldown(%d, %s): %s", user_id, cooldown_type, exc)
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
        return _row(res.data)
    except Exception as exc:
        logger.error("log_transaction(%d, %d, %d, %s): %s", sender_id, receiver_id, amount, tx_type, exc)
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
    except Exception as exc:
        logger.error("get_transaction_history(%d): %s", user_id, exc)
        raise


# ── Shop items ────────────────────────────────────────────────────────────────

async def get_shop_items(guild_id: Optional[int] = None) -> list[dict[str, Any]]:
    try:
        query = supabase.table("shopitems").select("*").eq("active", True)
        query = query.is_("guild_id", "null") if guild_id is None else query.eq("guild_id", guild_id)
        return _rows(query.execute().data)
    except Exception as exc:
        logger.error("get_shop_items(%s): %s", guild_id, exc)
        raise


async def get_shop_item(item_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("shopitems").select("*").eq("item_id", item_id).execute()
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_shop_item(%d): %s", item_id, exc)
        raise


async def create_shop_item(
    guild_id: Optional[int],
    name: str,
    description: str,
    price: int,
    item_type: str,
    role_id: Optional[int] = None,
) -> dict[str, Any]:
    try:
        res = supabase.table("shopitems").insert({
            "guild_id":    guild_id,
            "name":        name,
            "description": description,
            "price":       price,
            "type":        item_type,
            "role_id":     role_id,
            "active":      True,
        }).execute()
        logger.info("Created shop item '%s' for guild %s", name, guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("create_shop_item(%s, %s): %s", guild_id, name, exc)
        raise


async def disable_shop_item(item_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("shopitems").update({"active": False}).eq("item_id", item_id).execute()
        logger.info("Disabled shop item %d", item_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("disable_shop_item(%d): %s", item_id, exc)
        raise


# ── Inventory ─────────────────────────────────────────────────────────────────

async def add_to_inventory(user_id: int, item_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("inventory").insert({"user_id": user_id, "item_id": item_id}).execute()
        return _row(res.data)
    except Exception as exc:
        logger.error("add_to_inventory(%d, %d): %s", user_id, item_id, exc)
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
    except Exception as exc:
        logger.error("get_inventory(%d): %s", user_id, exc)
        raise


async def user_owns_item(user_id: int, item_id: int) -> bool:
    try:
        res = (
            supabase.table("inventory")
            .select("inv_id")
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.error("user_owns_item(%d, %d): %s", user_id, item_id, exc)
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
        logger.info("Report filed against %d by %d in guild %d", reported_id, reporter_id, guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("create_report(%d, %d): %s", reported_id, reporter_id, exc)
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
    except Exception as exc:
        logger.error("get_reports(%s, %s): %s", reported_id, status, exc)
        raise


async def update_report_status(report_id: int, status: str) -> dict[str, Any]:
    try:
        res = supabase.table("reports").update({"status": status}).eq("report_id", report_id).execute()
        return _row(res.data)
    except Exception as exc:
        logger.error("update_report_status(%d, %s): %s", report_id, status, exc)
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
        logger.info("Warn issued to %d by %d: %s", user_id, issued_by, reason)
        return _row(res.data)
    except Exception as exc:
        logger.error("issue_warn(%d): %s", user_id, exc)
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
    except Exception as exc:
        logger.error("get_active_warns(%d): %s", user_id, exc)
        raise


async def count_active_warns(user_id: int) -> int:
    return len(await get_active_warns(user_id))


async def clear_warn(warn_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("warns").update({"active": False}).eq("warn_id", warn_id).execute()
        logger.info("Warn %d cleared", warn_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("clear_warn(%d): %s", warn_id, exc)
        raise


# ── Bans ──────────────────────────────────────────────────────────────────────

async def get_ban(user_id: int) -> Optional[dict[str, Any]]:
    try:
        res = supabase.table("bans").select("*").eq("user_id", user_id).eq("active", True).execute()
        return _row(res.data) if res.data else None
    except Exception as exc:
        logger.error("get_ban(%d): %s", user_id, exc)
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
        logger.info("User %d banned by %d: %s", user_id, banned_by, reason)
        return _row(res.data)
    except Exception as exc:
        logger.error("ban_user(%d): %s", user_id, exc)
        raise


async def unban_user(user_id: int) -> dict[str, Any]:
    try:
        res = supabase.table("bans").update({"active": False}).eq("user_id", user_id).execute()
        logger.info("User %d unbanned", user_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("unban_user(%d): %s", user_id, exc)
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
    except Exception as exc:
        logger.error("get_leaderboard_server(%d): %s", guild_id, exc)
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
    except Exception as exc:
        logger.error("get_leaderboard_global(): %s", exc)
        raise


async def enrol_guild_global(guild_id: int, guild_name: str) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({
            "global_enrolled": True,
            "global":          True,
            "guild_name":      guild_name,
        }).eq("guild_id", guild_id).execute()
        logger.info("Guild %d enrolled in global leaderboard", guild_id)
        return _row(res.data)
    except Exception as exc:
        logger.error("enrol_guild_global(%d): %s", guild_id, exc)
        raise


async def set_guild_invite(guild_id: int, invite_url: str) -> dict[str, Any]:
    try:
        res = supabase.table("guilds").update({"invite_url": invite_url}).eq("guild_id", guild_id).execute()
        logger.info("Guild %d invite set: %s", guild_id, invite_url)
        return _row(res.data)
    except Exception as exc:
        logger.error("set_guild_invite(%d): %s", guild_id, exc)
        raise


async def get_global_leaderboard_guilds(limit: int = 10) -> list[dict[str, Any]]:
    try:
        res    = (
            supabase.table("guilds")
            .select("guild_id, guild_name, invite_url, icon_url")
            .eq("global_enrolled", True)
            .execute()
        )
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
    except Exception as exc:
        logger.error("get_global_leaderboard_guilds(): %s", exc)
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
            raise ValueError(
                f"Insufficient vault funds. Need ¥{SHOP_OPEN_COST:,} — vault has ¥{vault_total:,}."
            )

        top = await get_top_investors(guild_id, season_id, limit=1)
        if not top:
            raise ValueError("No investors found in this season's vault.")

        top_user_id  = int(top[0]["user_id"])
        bank         = await get_or_create_bank(top_user_id, guild_id, season_id)
        new_invested = int(bank["invested"]) - SHOP_OPEN_COST
        if new_invested < 0:
            raise ValueError("Top investor's balance is insufficient to cover the shop cost.")

        supabase.table("banks").update(
            {"invested": new_invested}
        ).eq("bank_id", bank["bank_id"]).execute()

        config_res = supabase.table("guildconfig").update(
            {"shop_enabled": True}
        ).eq("guild_id", guild_id).execute()

        logger.info("Server shop opened guild=%d — ¥%d deducted from vault", guild_id, SHOP_OPEN_COST)
        return _row(config_res.data)
    except ValueError:
        raise
    except Exception as exc:
        logger.error("open_server_shop(%d, %d): %s", guild_id, season_id, exc)
        raise


# ── top.gg ────────────────────────────────────────────────────────────────────

async def check_topgg_vote(user_id: int, bot_id: int, topgg_token: str) -> dict[str, Any]:
    """
    Poll the top.gg REST API to see if a user has voted.
    Returns { "voted": bool, "isWeekend": bool }.
    top.gg 404 means never voted — not an error.
    """
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
            if resp.status == 404:
                return {"voted": False, "isWeekend": False}
            raise RuntimeError(f"top.gg API returned HTTP {resp.status} for user {user_id}")