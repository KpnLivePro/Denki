from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.leaderboard")


async def _respond(
    ctx_or_interaction: Any,
    embed: discord.Embed,
    is_slash: bool,
    ephemeral: bool = False,
) -> None:
    if is_slash:
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.reply(embed=embed)


async def _build_name_map(bot: commands.Bot, guild: discord.Guild, rows: list[dict]) -> dict[int, str]:
    """Resolve user IDs to display names. Falls back to Discord API if not in cache."""
    name_map: dict[int, str] = {}
    for row in rows:
        uid = int(row["user_id"])
        member = guild.get_member(uid)
        if member:
            name_map[uid] = member.display_name
        else:
            try:
                user = await bot.fetch_user(uid)
                name_map[uid] = user.display_name
            except Exception:
                name_map[uid] = f"User {uid}"
    return name_map


class Leaderboard(commands.Cog):
    """Leaderboard commands — server, investors, global."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # /leaderboard slash with board choice

    @app_commands.command(name="leaderboard", description="View the Denki leaderboard.")
    @app_commands.describe(board="Which leaderboard to view")
    @app_commands.choices(board=[
        app_commands.Choice(name="Server — top richest in this server",      value="server"),
        app_commands.Choice(name="Investors — top investors this season",     value="investors"),
        app_commands.Choice(name="Global — top richest across all servers",  value="global"),
    ])
    async def leaderboard_slash(self, interaction: discord.Interaction, board: str) -> None:
        if board == "server":
            await self._leaderboard_server(interaction, is_slash=True)
        elif board == "investors":
            await self._leaderboard_investors(interaction, is_slash=True)
        elif board == "global":
            await self._leaderboard_global(interaction, is_slash=True)

    # Prefix group — !d lb / !d l

    @commands.group(name="leaderboard", aliases=["lb", "l"], invoke_without_command=True)
    async def leaderboard_prefix(self, ctx: commands.Context[Any]) -> None:
        await ctx.reply(embed=Embeds.info(
            "Use a subcommand:\n"
            "> `!d lb server` / `!d lbs`\n"
            "> `!d lb investors` / `!d lbi`\n"
            "> `!d lb global` / `!d lbg`"
        ))

    @leaderboard_prefix.command(name="server", aliases=["s"])
    async def lb_server_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_server(ctx, is_slash=False)

    @leaderboard_prefix.command(name="investors", aliases=["i"])
    async def lb_investors_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_investors(ctx, is_slash=False)

    @leaderboard_prefix.command(name="global", aliases=["g"])
    async def lb_global_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_global(ctx, is_slash=False)

    # Top-level short aliases

    @commands.command(name="lbs")
    async def lbs(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_server(ctx, is_slash=False)

    @commands.command(name="lbi")
    async def lbi(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_investors(ctx, is_slash=False)

    @commands.command(name="lbg")
    async def lbg(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_global(ctx, is_slash=False)

    # ── Server leaderboard ────────────────────────────────────────────────────

    async def _leaderboard_server(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        guild = ctx_or_interaction.guild

        rows = await db.get_leaderboard_server(guild.id, limit=7)
        if not rows:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("No wallet data found for this server yet."),
                is_slash,
            )

        # Flatten nested users(wallet) join — Supabase may return dict or single-item list
        flat: list[dict] = []
        for row in rows:
            r = dict(row)
            nested = r.get("users") or {}
            if isinstance(nested, list):
                nested = nested[0] if nested else {}
            if isinstance(nested, dict):
                r["wallet"] = int(nested.get("wallet", 0))
            else:
                r["wallet"] = 0
            flat.append(r)

        flat.sort(key=lambda x: int(x.get("wallet", 0)), reverse=True)

        name_map = await _build_name_map(self.bot, guild, flat)

        embed = Embeds.leaderboard(
            title=f"{guild.name} — Richest Members",
            rows=flat,
            name_map=name_map,
            value_key="wallet",
            value_prefix="¥",
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # ── Investors leaderboard ─────────────────────────────────────────────────

    async def _leaderboard_investors(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        guild = ctx_or_interaction.guild

        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("There is no active season right now."),
                is_slash,
            )

        season_id: int   = int(season["season_id"])
        season_name: str = str(season["name"])

        rows = await db.get_top_investors(guild.id, season_id, limit=7)
        if not rows:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("No investments found for this season yet."),
                is_slash,
            )

        name_map = await _build_name_map(self.bot, guild, rows)

        embed = Embeds.leaderboard(
            title=f"{guild.name} — Top Investors",
            rows=rows,
            name_map=name_map,
            value_key="invested",
            value_prefix="¥",
            season_name=season_name,
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # ── Global leaderboard ────────────────────────────────────────────────────

    async def _leaderboard_global(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        guild = ctx_or_interaction.guild

        guild_data = await db.get_guild(guild.id)
        if not guild_data or not guild_data.get("global"):
            return await _respond(
                ctx_or_interaction,
                Embeds.error(
                    "This server hasn't unlocked the global leaderboard yet.\n"
                    "> You need **250+ members** to access it."
                ),
                is_slash,
            )

        rows = await db.get_leaderboard_global(limit=7)
        if not rows:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("No global wallet data found yet."),
                is_slash,
            )

        # Fetch all global users concurrently — they may not be in this guild's cache
        user_objects: list[discord.User | None] = await asyncio.gather(
            *[self._safe_fetch_user(int(row["user_id"])) for row in rows]
        )

        name_map: dict[int, str] = {}
        for row, user_obj in zip(rows, user_objects):
            uid = int(row["user_id"])
            name_map[uid] = user_obj.display_name if user_obj else f"User {uid}"

        embed = Embeds.leaderboard(
            title="Global — Richest Denki Players",
            rows=rows,
            name_map=name_map,
            value_key="wallet",
            value_prefix="¥",
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    async def _safe_fetch_user(self, user_id: int) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user_id)
        except Exception:
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))