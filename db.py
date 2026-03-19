from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logger = logging.getLogger("denki.db")

# Client

_url: str = os.getenv("SUPABASE_URL", "")
_key: str = os.getenv("SUPABASE_KEY", "")

if not _url or not _key:
    logger.warning("SUPABASE_URL or SUPABASE_KEY is not set — DB calls will fail.")

try:
    supabase: Client = create_client(_url, _key)
except Exception as e:
    logger.critical(f"Failed to create Supabase client: {e}")
    raise


# Internal helpers

def _row(data: Any) -> dict[str, Any]:
    """Cast a single Supabase result row to dict."""
    return dict(data)


def _rows(data: Any) -> list[dict[str, Any]]:
    """Cast a Supabase result list to list[dict]."""
    if not data:
        return []
    return [dict(r) for r in data]


# Users

async def get_user(user_id: int) -> Optional[dict[str, Any]]:
    """Fetch a user row by user_id. Returns None if not found."""
    try:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_user({user_id}): {e}")
        raise


async def get_or_create_user(user_id: int) -> dict[str, Any]:
    """Fetch user or create with 0 wallet if first time."""
    try:
        user = await get_user(user_id)
        if user:
            return user
        res = supabase.table("users").insert({
            "user_id": user_id,
            "wallet": 0,
        }).execute()
        logger.info(f"Created new user {user_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_user({user_id}): {e}")
        raise


async def update_wallet(user_id: int, amount: int) -> dict[str, Any]:
    """
    Add or subtract from users.wallet.
    Positive amount = earn, negative = spend.
    Raises ValueError if balance would go below 0.
    """
    try:
        user = await get_or_create_user(user_id)
        new_balance: int = int(user["wallet"]) + amount
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


# Guilds

async def get_guild(guild_id: int) -> Optional[dict[str, Any]]:
    """Fetch a guild row. Returns None if not registered."""
    try:
        res = supabase.table("guilds").select("*").eq("guild_id", guild_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_guild({guild_id}): {e}")
        raise


async def get_or_create_guild(guild_id: int) -> dict[str, Any]:
    """Fetch guild or create with defaults."""
    try:
        guild = await get_guild(guild_id)
        if guild:
            return guild
        res = supabase.table("guilds").insert({
            "guild_id": guild_id,
            "global": False,
            "wins": 0,
            "tier": 1,
        }).execute()
        logger.info(f"Registered new guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_guild({guild_id}): {e}")
        raise


async def set_guild_global(guild_id: int, is_global: bool) -> dict[str, Any]:
    """Set guilds.global flag (triggered when server hits 250+ members)."""
    try:
        res = supabase.table("guilds").update({"global": is_global}).eq("guild_id", guild_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"set_guild_global({guild_id}, {is_global}): {e}")
        raise


async def increment_guild_wins(guild_id: int) -> dict[str, Any]:
    """Increment wins and update tier based on win streak."""
    try:
        guild = await get_or_create_guild(guild_id)
        new_wins: int = int(guild["wins"]) + 1
        new_tier: int = _calculate_tier(new_wins)
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
    """Reset win streak to 0 and drop back to Tier 1."""
    try:
        res = supabase.table("guilds").update({"wins": 0, "tier": 1}).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} win streak reset")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"reset_guild_wins({guild_id}): {e}")
        raise


def _calculate_tier(wins: int) -> int:
    """Derive tier from consecutive win count."""
    if wins >= 10:
        return 5
    if wins >= 7:
        return 4
    if wins >= 4:
        return 3
    if wins >= 2:
        return 2
    return 1


# Guild config

async def get_guild_config(guild_id: int) -> Optional[dict[str, Any]]:
    """Fetch guildconfig row."""
    try:
        res = supabase.table("guildconfig").select("*").eq("guild_id", guild_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_guild_config({guild_id}): {e}")
        raise


async def get_or_create_guild_config(guild_id: int) -> dict[str, Any]:
    """Fetch guildconfig or create with defaults. Ensures guild row exists first."""
    try:
        config = await get_guild_config(guild_id)
        if config:
            return config
        # Guild must exist before config due to FK constraint
        await get_or_create_guild(guild_id)
        res = supabase.table("guildconfig").insert({
            "guild_id": guild_id,
            "daily_enabled": True,
            "work_enabled": True,
            "rob_enabled": True,
            "notif_channel": None,
            "notif_role": None,
            "shop_enabled": False,
        }).execute()
        logger.info(f"Created guildconfig for guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_guild_config({guild_id}): {e}")
        raise


async def update_guild_config(guild_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """
    Update any guildconfig fields.
    Raises ValueError if all three earn toggles would be disabled.
    """
    try:
        config = await get_or_create_guild_config(guild_id)
        merged = {**config, **updates}
        earn_flags = [
            bool(merged.get("daily_enabled", True)),
            bool(merged.get("work_enabled", True)),
            bool(merged.get("rob_enabled", True)),
        ]
        if not any(earn_flags):
            raise ValueError(
                "Cannot disable all three earning methods. At least one must remain active."
            )
        res = supabase.table("guildconfig").update(updates).eq("guild_id", guild_id).execute()
        return _row(res.data[0])
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"update_guild_config({guild_id}, {updates}): {e}")
        raise


# Seasons

async def get_active_season() -> Optional[dict[str, Any]]:
    """Fetch the current active season. Returns None if none exists."""
    try:
        res = supabase.table("seasons").select("*").eq("active", True).limit(1).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_active_season(): {e}")
        raise


async def get_season(season_id: int) -> Optional[dict[str, Any]]:
    """Fetch a specific season by ID."""
    try:
        res = supabase.table("seasons").select("*").eq("season_id", season_id).execute()
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_season({season_id}): {e}")
        raise


async def create_season(name: str = "New Season", theme: Optional[str] = None) -> dict[str, Any]:
    """Insert a new active season row."""
    try:
        res = supabase.table("seasons").insert({
            "name": name,
            "theme": theme,
            "tax_rate": 0,
            "active": True,
        }).execute()
        logger.info(f"Created new season: {name}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"create_season({name}): {e}")
        raise


async def close_season(season_id: int) -> dict[str, Any]:
    """Mark a season as inactive (archived)."""
    try:
        res = supabase.table("seasons").update({"active": False}).eq("season_id", season_id).execute()
        logger.info(f"Closed season {season_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"close_season({season_id}): {e}")
        raise


async def update_season(season_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """Update season name/theme."""
    try:
        res = supabase.table("seasons").update(updates).eq("season_id", season_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"update_season({season_id}, {updates}): {e}")
        raise


# Banks

async def get_bank(user_id: int, guild_id: int, season_id: int) -> Optional[dict[str, Any]]:
    """Fetch a user's bank for a specific guild and season."""
    try:
        res = (
            supabase.table("banks")
            .select("*")
            .eq("user_id", user_id)
            .eq("guild_id", guild_id)
            .eq("season_id", season_id)
            .execute()
        )
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_bank({user_id}, {guild_id}, {season_id}): {e}")
        raise


async def get_or_create_bank(user_id: int, guild_id: int, season_id: int) -> dict[str, Any]:
    """Fetch bank or create fresh one for this season."""
    try:
        bank = await get_bank(user_id, guild_id, season_id)
        if bank:
            return bank
        res = supabase.table("banks").insert({
            "user_id": user_id,
            "guild_id": guild_id,
            "season_id": season_id,
            "balance": 0,
            "invested": 0,
            "total_earned": 0,
        }).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"get_or_create_bank({user_id}, {guild_id}, {season_id}): {e}")
        raise


async def update_bank_balance(user_id: int, guild_id: int, season_id: int, amount: int) -> dict[str, Any]:
    """Add or subtract from banks.balance. Raises ValueError if insufficient."""
    try:
        bank = await get_or_create_bank(user_id, guild_id, season_id)
        new_balance: int = int(bank["balance"]) + amount
        if new_balance < 0:
            raise ValueError(
                f"Insufficient server bank funds. Balance: ¥{bank['balance']:,}."
            )
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
    """
    Move amount from users.wallet into banks.invested.
    Deducts from wallet first — raises ValueError if wallet is insufficient.
    """
    try:
        await update_wallet(user_id, -amount)
        bank = await get_or_create_bank(user_id, guild_id, season_id)
        res = supabase.table("banks").update({
            "invested": int(bank["invested"]) + amount,
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
    """Fetch top investors for a guild's season, sorted by invested descending."""
    try:
        res = (
            supabase.table("banks")
            .select("user_id, invested, total_earned")
            .eq("guild_id", guild_id)
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
    """Get total Yen invested into a guild's vault this season."""
    try:
        res = (
            supabase.table("banks")
            .select("invested")
            .eq("guild_id", guild_id)
            .eq("season_id", season_id)
            .execute()
        )
        rows = _rows(res.data)
        return sum(int(r["invested"]) for r in rows)
    except Exception as e:
        logger.error(f"get_season_vault_total({guild_id}, {season_id}): {e}")
        raise


# Cooldowns

async def get_cooldown(user_id: int, cooldown_type: str) -> Optional[datetime]:
    """
    Returns last_used datetime for a cooldown type, or None if never used.
    cooldown_type: 'daily' | 'work' | 'rob'
    """
    try:
        res = (
            supabase.table("cooldowns")
            .select("last_used")
            .eq("user_id", user_id)
            .eq("type", cooldown_type)
            .execute()
        )
        if res.data:
            row = _row(res.data[0])
            raw: str = str(row["last_used"])
            return datetime.fromisoformat(raw)
        return None
    except Exception as e:
        logger.error(f"get_cooldown({user_id}, {cooldown_type}): {e}")
        raise


async def set_cooldown(user_id: int, cooldown_type: str) -> None:
    """Upsert the last_used timestamp for a cooldown type to now."""
    try:
        now: str = datetime.now(timezone.utc).isoformat()
        existing = await get_cooldown(user_id, cooldown_type)
        if existing is not None:
            supabase.table("cooldowns").update({"last_used": now}).eq("user_id", user_id).eq("type", cooldown_type).execute()
        else:
            supabase.table("cooldowns").insert({
                "user_id": user_id,
                "type": cooldown_type,
                "last_used": now,
            }).execute()
    except Exception as e:
        logger.error(f"set_cooldown({user_id}, {cooldown_type}): {e}")
        raise


# Transactions

async def log_transaction(sender_id: int, receiver_id: int, amount: int, tx_type: str) -> dict[str, Any]:
    """
    Log a transaction.
    Use sender_id=0 for system transactions (season bonus, admin adjust).
    tx_type: 'transfer' | 'rob' | 'daily' | 'work' | 'season_bonus' | 'admin_adjust' | 'gamble_win' | 'gamble_loss'
    """
    try:
        res = supabase.table("transactions").insert({
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "amount": amount,
            "type": tx_type,
        }).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"log_transaction({sender_id}, {receiver_id}, {amount}, {tx_type}): {e}")
        raise


async def get_transaction_history(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch last N transactions where user is sender or receiver."""
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


# Shop items

async def get_shop_items(guild_id: Optional[int] = None) -> list[dict[str, Any]]:
    """
    Fetch active shop items.
    guild_id=None returns global items only (guild_id IS NULL).
    guild_id=<id> returns items for that server.
    """
    try:
        query = supabase.table("shopitems").select("*").eq("active", True)
        if guild_id is None:
            query = query.is_("guild_id", "null")
        else:
            query = query.eq("guild_id", guild_id)
        res = query.execute()
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_shop_items({guild_id}): {e}")
        raise


async def get_shop_item(item_id: int) -> Optional[dict[str, Any]]:
    """Fetch a single shop item by ID."""
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
) -> dict[str, Any]:
    """
    Create a new shop item.
    guild_id=None = global item (bot owner only).
    item_type: 'role' | 'pet' | 'badge' | 'collectible'
    """
    try:
        res = supabase.table("shopitems").insert({
            "guild_id": guild_id,
            "name": name,
            "description": description,
            "price": price,
            "type": item_type,
            "role_id": role_id,
            "active": True,
        }).execute()
        logger.info(f"Created shop item '{name}' for guild {guild_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"create_shop_item({guild_id}, {name}): {e}")
        raise


async def disable_shop_item(item_id: int) -> dict[str, Any]:
    """Soft-delete a shop item by setting active=False."""
    try:
        res = supabase.table("shopitems").update({"active": False}).eq("item_id", item_id).execute()
        logger.info(f"Disabled shop item {item_id}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"disable_shop_item({item_id}): {e}")
        raise


# Inventory

async def add_to_inventory(user_id: int, item_id: int) -> dict[str, Any]:
    """Add a purchased item to a user's inventory."""
    try:
        res = supabase.table("inventory").insert({
            "user_id": user_id,
            "item_id": item_id,
        }).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"add_to_inventory({user_id}, {item_id}): {e}")
        raise


async def get_inventory(user_id: int) -> list[dict[str, Any]]:
    """Fetch all items owned by a user, joined with shopitems details."""
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
    """Check if a user already owns a specific item."""
    try:
        res = (
            supabase.table("inventory")
            .select("inv_id")
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(f"user_owns_item({user_id}, {item_id}): {e}")
        raise


# Reports

async def create_report(
    reported_id: int,
    reporter_id: int,
    guild_id: int,
    reason: str,
    wallet_snap: int,
) -> dict[str, Any]:
    """File a new report against a user."""
    try:
        res = supabase.table("reports").insert({
            "reported_id": reported_id,
            "reporter_id": reporter_id,
            "guild_id": guild_id,
            "reason": reason,
            "wallet_snap": wallet_snap,
            "status": "pending",
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
    """
    Fetch reports filtered by reported_id and/or status.
    status: 'pending' | 'reviewed' | 'banned' | 'dismissed'
    """
    try:
        query = supabase.table("reports").select("*").order("created_at", desc=True)
        if reported_id is not None:
            query = query.eq("reported_id", reported_id)
        if status is not None:
            query = query.eq("status", status)
        res = query.execute()
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_reports({reported_id}, {status}): {e}")
        raise


async def update_report_status(report_id: int, status: str) -> dict[str, Any]:
    """Update a report's status after owner review."""
    try:
        res = supabase.table("reports").update({"status": status}).eq("report_id", report_id).execute()
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"update_report_status({report_id}, {status}): {e}")
        raise


# Warns

async def issue_warn(user_id: int, reason: str, issued_by: int) -> dict[str, Any]:
    """Issue a new warn to a user."""
    try:
        res = supabase.table("warns").insert({
            "user_id": user_id,
            "reason": reason,
            "issued_by": issued_by,
            "active": True,
        }).execute()
        logger.info(f"Warn issued to {user_id} by {issued_by}: {reason}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"issue_warn({user_id}): {e}")
        raise


async def get_active_warns(user_id: int) -> list[dict[str, Any]]:
    """
    Fetch all active non-expired warns for a user.
    Counts only rows where active=True AND expires_at > now.
    """
    try:
        now: str = datetime.now(timezone.utc).isoformat()
        res = (
            supabase.table("warns")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .gt("expires_at", now)
            .execute()
        )
        return _rows(res.data)
    except Exception as e:
        logger.error(f"get_active_warns({user_id}): {e}")
        raise


async def count_active_warns(user_id: int) -> int:
    """Count active non-expired warns. Auto-ban triggers at 3."""
    warns = await get_active_warns(user_id)
    return len(warns)


async def clear_warn(warn_id: int) -> dict[str, Any]:
    """Manually deactivate a warn by owner."""
    try:
        res = supabase.table("warns").update({"active": False}).eq("warn_id", warn_id).execute()
        logger.info(f"Warn {warn_id} cleared")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"clear_warn({warn_id}): {e}")
        raise


# Bans

async def get_ban(user_id: int) -> Optional[dict[str, Any]]:
    """Check if a user has an active ban. Returns ban row or None."""
    try:
        res = (
            supabase.table("bans")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .execute()
        )
        return _row(res.data[0]) if res.data else None
    except Exception as e:
        logger.error(f"get_ban({user_id}): {e}")
        raise


async def is_banned(user_id: int) -> bool:
    """Quick check — returns True if user has an active ban."""
    return (await get_ban(user_id)) is not None


async def ban_user(user_id: int, reason: str, banned_by: int) -> dict[str, Any]:
    """Globally ban a user from Denki. Upserts on user_id."""
    try:
        res = supabase.table("bans").upsert({
            "user_id": user_id,
            "reason": reason,
            "banned_by": banned_by,
            "active": True,
        }, on_conflict="user_id").execute()
        logger.info(f"User {user_id} banned by {banned_by}: {reason}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"ban_user({user_id}): {e}")
        raise


async def unban_user(user_id: int) -> dict[str, Any]:
    """Remove a global Denki ban."""
    try:
        res = supabase.table("bans").update({"active": False}).eq("user_id", user_id).execute()
        logger.info(f"User {user_id} unbanned")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"unban_user({user_id}): {e}")
        raise


# Leaderboards

async def get_leaderboard_server(guild_id: int, limit: int = 7) -> list[dict[str, Any]]:
    """
    Top N richest users in a guild.
    Filters to users with a bank record in this guild, sorted by wallet.
    """
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
    """
    Top N richest users globally across all servers.
    Only called in guilds where guilds.global=True.
    """
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
    """Enrol a guild in the global leaderboard — sets global_enrolled=True and stores name."""
    try:
        res = supabase.table("guilds").update({
            "global_enrolled": True,
            "global": True,
            "guild_name": guild_name,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} enrolled in global leaderboard")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"enrol_guild_global({guild_id}): {e}")
        raise


async def set_guild_invite(guild_id: int, invite_url: str) -> dict[str, Any]:
    """Store the invite URL for a guild on the global leaderboard."""
    try:
        res = supabase.table("guilds").update({
            "invite_url": invite_url,
        }).eq("guild_id", guild_id).execute()
        logger.info(f"Guild {guild_id} invite set: {invite_url}")
        return _row(res.data[0])
    except Exception as e:
        logger.error(f"set_guild_invite({guild_id}): {e}")
        raise


async def get_global_leaderboard_guilds(limit: int = 10) -> list[dict[str, Any]]:
    """
    Fetch top globally enrolled servers ranked by total wallet sum of their members.
    Returns guild rows with their stored name, invite_url, and computed wallet_total.
    """
    try:
        # Fetch all enrolled guilds
        res = supabase.table("guilds").select("guild_id, guild_name, invite_url").eq("global_enrolled", True).execute()
        guilds = _rows(res.data)
        if not guilds:
            return []

        # For each guild, sum up the wallets of members who have a bank record in that guild
        results = []
        for guild in guilds:
            gid = int(guild["guild_id"])
            # Get all user_ids in this guild via banks
            bank_res = supabase.table("banks").select("user_id").eq("guild_id", gid).execute()
            user_ids = list({int(r["user_id"]) for r in (_rows(bank_res.data))})
            if not user_ids:
                wallet_total = 0
            else:
                # Sum wallets for those users
                user_res = supabase.table("users").select("wallet").in_("user_id", user_ids).execute()
                wallet_total = sum(int(r["wallet"]) for r in (_rows(user_res.data)))
            results.append({
                "guild_id": gid,
                "guild_name": guild.get("guild_name") or f"Server {gid}",
                "invite_url": guild.get("invite_url"),
                "wallet_total": wallet_total,
            })

        # Sort by wallet_total descending
        results.sort(key=lambda x: x["wallet_total"], reverse=True)
        return results[:limit]
    except Exception as e:
        logger.error(f"get_global_leaderboard_guilds(): {e}")
        raise


# Shop management

SHOP_OPEN_COST: int = 10_000


async def open_server_shop(guild_id: int, season_id: int) -> dict[str, Any]:
    """
    Open a server shop by deducting SHOP_OPEN_COST from the guild's vault
    and setting guildconfig.shop_enabled = True.

    Vault total is the sum of all banks.invested for this guild/season.
    We deduct the cost from the top investor's bank record to keep accounting clean.

    Raises ValueError if:
    - Shop is already open
    - Vault total is insufficient to cover the cost
    - No investors found
    """
    try:
        config = await get_or_create_guild_config(guild_id)
        if config["shop_enabled"]:
            raise ValueError("This server's shop is already open.")

        vault_total = await get_season_vault_total(guild_id, season_id)
        if vault_total < SHOP_OPEN_COST:
            raise ValueError(
                f"Insufficient vault funds. Need ¥{SHOP_OPEN_COST:,} — vault has ¥{vault_total:,}."
            )

        # Deduct cost from the top investor's bank record
        top = await get_top_investors(guild_id, season_id, limit=1)
        if not top:
            raise ValueError("No investors found in this season's vault.")

        top_user_id: int = int(top[0]["user_id"])
        bank = await get_or_create_bank(top_user_id, guild_id, season_id)
        new_invested: int = int(bank["invested"]) - SHOP_OPEN_COST

        if new_invested < 0:
            raise ValueError("Top investor's balance is insufficient to cover the shop cost.")

        supabase.table("banks").update({
            "invested": new_invested
        }).eq("bank_id", bank["bank_id"]).execute()

        # Enable shop in guild config
        config_res = supabase.table("guildconfig").update({
            "shop_enabled": True
        }).eq("guild_id", guild_id).execute()

        logger.info(f"Server shop opened for guild {guild_id} — ¥{SHOP_OPEN_COST:,} deducted from vault")
        return _row(config_res.data[0])

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"open_server_shop({guild_id}, {season_id}): {e}")
        raise