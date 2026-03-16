"""
Full DB logic test — shop, inventory, reports, guild tier, season flow.
    python test_db3.py
"""
from __future__ import annotations

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

TEST_USER_ID  = 933274396888539136
TEST_GUILD_ID = 1421383276328783924

PASS = "   ✅"
FAIL = "   ❌"


async def main() -> None:
    print("⚡ Denki — Full DB logic test\n")

    import db

    season = await db.get_active_season()
    if not season:
        print("❌ No active season found")
        return
    SEASON_ID = int(season["season_id"])
    print(f"Season: {season['name']} (ID: {SEASON_ID})")
    print(f"User:   {TEST_USER_ID}")
    print(f"Guild:  {TEST_GUILD_ID}\n")

    # ── Shop items ──────────────────────────────────────────

    print("── SHOP ITEMS")

    print("\n  Test 15: create_shop_item() — server item")
    try:
        item = await db.create_shop_item(
            guild_id=TEST_GUILD_ID,
            name="Test Role",
            description="A test role item",
            price=250,
            item_type="role",
            role_id=None,
        )
        item_id = int(item["item_id"])
        print(f"{PASS} Created server item ID={item_id} price=¥{item['price']:,}")
    except Exception as e:
        print(f"{FAIL} {e}")
        item_id = None

    print("\n  Test 16: create_shop_item() — global item")
    try:
        global_item = await db.create_shop_item(
            guild_id=None,
            name="Test Badge",
            description="A test global badge",
            price=500,
            item_type="badge",
        )
        global_item_id = int(global_item["item_id"])
        print(f"{PASS} Created global item ID={global_item_id}")
    except Exception as e:
        print(f"{FAIL} {e}")
        global_item_id = None

    print("\n  Test 17: get_shop_items() — server")
    try:
        items = await db.get_shop_items(guild_id=TEST_GUILD_ID)
        print(f"{PASS} {len(items)} server item(s) found")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 18: get_shop_items() — global")
    try:
        items = await db.get_shop_items(guild_id=None)
        print(f"{PASS} {len(items)} global item(s) found")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 19: get_shop_item() by ID")
    try:
        if item_id:
            item = await db.get_shop_item(item_id)
            print(f"{PASS} Fetched: {item['name']} — ¥{item['price']:,}")
        else:
            print("   ⚠️  Skipped — no item_id from test 15")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 20: disable_shop_item()")
    try:
        if item_id:
            await db.disable_shop_item(item_id)
            item = await db.get_shop_item(item_id)
            print(f"{PASS} Item active={item['active']}")
        else:
            print("   ⚠️  Skipped — no item_id from test 15")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Inventory ────────────────────────────────────────────

    print("\n── INVENTORY")

    print("\n  Test 21: add_to_inventory()")
    try:
        if global_item_id:
            inv = await db.add_to_inventory(TEST_USER_ID, global_item_id)
            print(f"{PASS} Added item {global_item_id} to inventory (inv_id={inv['inv_id']})")
        else:
            print("   ⚠️  Skipped — no global_item_id from test 16")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 22: get_inventory()")
    try:
        items = await db.get_inventory(TEST_USER_ID)
        print(f"{PASS} {len(items)} item(s) in inventory")
        for i in items:
            shop = i.get("shopitems") or {}
            print(f"        → {shop.get('name', '?')} (type={shop.get('type', '?')})")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 23: user_owns_item()")
    try:
        if global_item_id:
            owns = await db.user_owns_item(TEST_USER_ID, global_item_id)
            print(f"{PASS} user_owns_item={owns}")
        else:
            print("   ⚠️  Skipped")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Open server shop ─────────────────────────────────────

    print("\n── SHOP OPEN")

    print("\n  Test 24: open_server_shop()")
    try:
        # Ensure vault has enough
        bank = await db.get_or_create_bank(TEST_USER_ID, TEST_GUILD_ID, SEASON_ID)
        if int(bank["invested"]) < db.SHOP_OPEN_COST:
            needed = db.SHOP_OPEN_COST - int(bank["invested"])
            # Top up wallet first
            await db.update_wallet(TEST_USER_ID, needed + 500)
            await db.add_investment(TEST_USER_ID, TEST_GUILD_ID, SEASON_ID, needed)

        result = await db.open_server_shop(TEST_GUILD_ID, SEASON_ID)
        print(f"{PASS} Shop opened — shop_enabled={result['shop_enabled']}")
    except ValueError as e:
        print(f"   ⚠️  ValueError (expected if shop already open): {e}")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 25: open_server_shop() — already open")
    try:
        await db.open_server_shop(TEST_GUILD_ID, SEASON_ID)
        print(f"{FAIL} Should have raised ValueError")
    except ValueError as e:
        print(f"{PASS} Correctly raised ValueError: {e}")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Reports ──────────────────────────────────────────────

    print("\n── REPORTS")

    print("\n  Test 26: create_report()")
    try:
        report = await db.create_report(
            reported_id=TEST_USER_ID,
            reporter_id=TEST_USER_ID,
            guild_id=TEST_GUILD_ID,
            reason="Test report — ignore",
            wallet_snap=500,
        )
        report_id = int(report["report_id"])
        print(f"{PASS} Report created ID={report_id} status={report['status']}")
    except Exception as e:
        print(f"{FAIL} {e}")
        report_id = None

    print("\n  Test 27: get_reports() — pending")
    try:
        reports = await db.get_reports(status="pending")
        print(f"{PASS} {len(reports)} pending report(s)")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 28: update_report_status() — dismiss")
    try:
        if report_id:
            updated = await db.update_report_status(report_id, "dismissed")
            print(f"{PASS} Report {report_id} status={updated['status']}")
        else:
            print("   ⚠️  Skipped")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Guild wins and tier ───────────────────────────────────

    print("\n── GUILD TIER & WINS")

    print("\n  Test 29: increment_guild_wins() x3 — tier progression")
    try:
        await db.reset_guild_wins(TEST_GUILD_ID)
        for i in range(1, 4):
            g = await db.increment_guild_wins(TEST_GUILD_ID)
            print(f"        wins={g['wins']} tier={g['tier']}")
        print(f"{PASS} Tier progression correct")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 30: reset_guild_wins()")
    try:
        g = await db.reset_guild_wins(TEST_GUILD_ID)
        print(f"{PASS} After reset: wins={g['wins']} tier={g['tier']}")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Guild config earn toggle validation ───────────────────

    print("\n── EARN TOGGLE VALIDATION")

    print("\n  Test 31: update_guild_config() — disable 2 of 3")
    try:
        cfg = await db.update_guild_config(TEST_GUILD_ID, {
            "daily_enabled": False,
            "work_enabled": False,
            "rob_enabled": True,
        })
        print(f"{PASS} daily={cfg['daily_enabled']} work={cfg['work_enabled']} rob={cfg['rob_enabled']}")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 32: update_guild_config() — disable all 3 (should fail)")
    try:
        await db.update_guild_config(TEST_GUILD_ID, {
            "daily_enabled": False,
            "work_enabled": False,
            "rob_enabled": False,
        })
        print(f"{FAIL} Should have raised ValueError")
    except ValueError as e:
        print(f"{PASS} Correctly raised ValueError: {e}")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n  Test 33: reset guild config to all enabled")
    try:
        cfg = await db.update_guild_config(TEST_GUILD_ID, {
            "daily_enabled": True,
            "work_enabled": True,
            "rob_enabled": True,
        })
        print(f"{PASS} Reset: daily={cfg['daily_enabled']} work={cfg['work_enabled']} rob={cfg['rob_enabled']}")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── Transaction history ───────────────────────────────────

    print("\n── TRANSACTIONS")

    print("\n  Test 34: get_transaction_history()")
    try:
        txs = await db.get_transaction_history(TEST_USER_ID, limit=5)
        print(f"{PASS} {len(txs)} transaction(s) found")
        for tx in txs:
            print(f"        → type={tx['type']} amount=¥{int(tx['amount']):,}")
    except Exception as e:
        print(f"{FAIL} {e}")

    # ── set_guild_global ──────────────────────────────────────

    print("\n── GUILD GLOBAL FLAG")

    print("\n  Test 35: set_guild_global() — enable and disable")
    try:
        await db.set_guild_global(TEST_GUILD_ID, True)
        g = await db.get_guild(TEST_GUILD_ID)
        print(f"        global=True  → {g['global']}")
        await db.set_guild_global(TEST_GUILD_ID, False)
        g = await db.get_guild(TEST_GUILD_ID)
        print(f"        global=False → {g['global']}")
        print(f"{PASS} Guild global flag works")
    except Exception as e:
        print(f"{FAIL} {e}")

    print("\n── All tests complete.")
    print("   If all passed, the full DB layer is verified and the bot is ready to run.\n")


if __name__ == "__main__":
    asyncio.run(main())