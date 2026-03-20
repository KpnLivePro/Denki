from __future__ import annotations

"""
cogs/website_push.py

Background task that pushes a snapshot of Denki's live data to the website
API every 60 seconds. The website caches this payload and serves it to
visitors without making direct DB calls.

Payload shape (JSON POST to WEBSITE_API_URL):
{
  "secret":         "<WEBSITE_SECRET>",
  "bot_stats": {
    "guild_count":  int,
    "user_count":   int,
    "uptime_s":     int
  },
  "active_season": {
    "season_id":    int,
    "name":         str,
    "emoji":        str | null,
    "theme":        str | null,    # hex color e.g. "#F2C84B"
    "end":          str,           # ISO timestamp
    "active":       bool
  } | null,
  "richest_user": {
    "user_id":      int,
    "username":     str,
    "avatar_url":   str | null,
    "wallet":       int
  } | null,
  "guild_leaderboard": [
    {
      "guild_id":     int,
      "guild_name":   str,
      "icon_url":     str | null,
      "invite_url":   str | null,
      "wallet_total": int,
      "tier":         int,
      "wins":         int
    },
    ...  # top 10 enrolled guilds
  ]
}

Required environment variables:
  WEBSITE_API_URL  — full URL to POST to e.g. https://yoursite.com/api/bot-push
  WEBSITE_SECRET   — shared secret the website uses to authenticate the push
"""

import logging
import os
import time
from typing import Any

import aiohttp
import discord
from discord.ext import commands, tasks

import db

logger = logging.getLogger("denki.website_push")

WEBSITE_API_URL: str = os.environ.get("WEBSITE_API_URL", "")
WEBSITE_SECRET:  str = os.environ.get("WEBSITE_SECRET",  "")

# How often to push (seconds)
PUSH_INTERVAL: int = 60

# Module load time — used to calculate uptime
_start_time: float = time.time()


class WebsitePush(commands.Cog):
    """Pushes a live snapshot of bot data to the website API every 60 seconds."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        if not WEBSITE_API_URL:
            logger.warning("WEBSITE_API_URL is not set — website push is disabled.")
            return
        if not WEBSITE_SECRET:
            logger.warning("WEBSITE_SECRET is not set — website push is disabled.")
            return
        self.push_loop.start()
        logger.info("Website push loop started — interval=%ds url=%s", PUSH_INTERVAL, WEBSITE_API_URL)

    async def cog_unload(self) -> None:
        self.push_loop.cancel()

    @tasks.loop(seconds=PUSH_INTERVAL)
    async def push_loop(self) -> None:
        try:
            payload = await self._build_payload()
            await self._post(payload)
        except Exception as e:
            logger.error("website_push: push failed: %s", e)

    @push_loop.before_loop
    async def before_push(self) -> None:
        await self.bot.wait_until_ready()

    # ── Payload builder ───────────────────────────────────────────────────────

    async def _build_payload(self) -> dict[str, Any]:
        # Bot stats
        guild_count = len(self.bot.guilds)
        user_count  = sum(g.member_count or 0 for g in self.bot.guilds)
        uptime_s    = int(time.time() - _start_time)

        # Active season
        season_data: dict[str, Any] | None = None
        try:
            season = await db.get_active_season()
            if season:
                season_data = {
                    "season_id": int(season["season_id"]),
                    "name":      season.get("name")  or "Unnamed Season",
                    "emoji":     season.get("emoji"),
                    "theme":     season.get("theme"),
                    "end":       season.get("end"),
                    "active":    bool(season.get("active", True)),
                }
        except Exception as e:
            logger.warning("website_push: failed to fetch season: %s", e)

        # Richest user — resolve Discord username
        richest_data: dict[str, Any] | None = None
        try:
            richest_row = await db.get_richest_user()
            if richest_row:
                uid      = int(richest_row["user_id"])
                wallet   = int(richest_row["wallet"])
                discord_user = self.bot.get_user(uid)
                if discord_user is None:
                    try:
                        discord_user = await self.bot.fetch_user(uid)
                    except Exception:
                        discord_user = None
                richest_data = {
                    "user_id":    uid,
                    "username":   str(discord_user) if discord_user else f"User {uid}",
                    "avatar_url": str(discord_user.display_avatar.url) if discord_user else None,
                    "wallet":     wallet,
                }
        except Exception as e:
            logger.warning("website_push: failed to fetch richest user: %s", e)

        # Guild leaderboard — top 10 enrolled guilds
        guild_leaderboard: list[dict[str, Any]] = []
        try:
            raw_guilds = await db.get_global_leaderboard_guilds(limit=10)
            for g in raw_guilds:
                gid        = int(g["guild_id"])
                guild_row  = await db.get_guild(gid)
                tier       = int(guild_row["tier"]) if guild_row else 1
                wins       = int(guild_row["wins"]) if guild_row else 0
                guild_leaderboard.append({
                    "guild_id":     gid,
                    "guild_name":   g.get("guild_name") or f"Server {gid}",
                    "icon_url":     g.get("icon_url"),
                    "invite_url":   g.get("invite_url"),
                    "wallet_total": int(g.get("wallet_total", 0)),
                    "tier":         tier,
                    "wins":         wins,
                })
        except Exception as e:
            logger.warning("website_push: failed to fetch guild leaderboard: %s", e)

        return {
            "secret": WEBSITE_SECRET,
            "bot_stats": {
                "guild_count": guild_count,
                "user_count":  user_count,
                "uptime_s":    uptime_s,
            },
            "active_season":    season_data,
            "richest_user":     richest_data,
            "guild_leaderboard": guild_leaderboard,
        }

    async def _post(self, payload: dict[str, Any]) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                WEBSITE_API_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    logger.info(
                        "website_push: ok guilds=%d users=%d",
                        payload["bot_stats"]["guild_count"],
                        payload["bot_stats"]["user_count"],
                    )
                else:
                    body = await resp.text()
                    logger.warning(
                        "website_push: unexpected status=%d body=%r",
                        resp.status, body[:200],
                    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WebsitePush(bot))