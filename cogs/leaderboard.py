from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.leaderboard")

GLOBAL_MIN_MEMBERS = 100


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
    """Leaderboard + global enrolment commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /leaderboard ─────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="View the Denki leaderboard.")
    @app_commands.describe(board="Which leaderboard to view")
    @app_commands.choices(board=[
        app_commands.Choice(name="Server — top richest in this server",           value="server"),
        app_commands.Choice(name="Investors — top investors this season",          value="investors"),
        app_commands.Choice(name="Global — top enrolled servers by ¥ Yen earned", value="global"),
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

    @commands.command(name="lbs")
    async def lbs(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_server(ctx, is_slash=False)

    @commands.command(name="lbi")
    async def lbi(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_investors(ctx, is_slash=False)

    @commands.command(name="lbg")
    async def lbg(self, ctx: commands.Context[Any]) -> None:
        await self._leaderboard_global(ctx, is_slash=False)

    # ── /global group ─────────────────────────────────────────────────────────

    global_group = app_commands.Group(
        name="global",
        description="Global leaderboard enrolment commands.",
    )

    @global_group.command(name="enrol", description="Enrol your server in the global leaderboard. Requires 100+ members. Admin only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def global_enrol(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        guild = interaction.guild
        member_count = guild.member_count or 0

        if member_count < GLOBAL_MIN_MEMBERS:
            needed = GLOBAL_MIN_MEMBERS - member_count
            return await interaction.response.send_message(
                embed=Embeds.error(
                    f"Your server needs **{GLOBAL_MIN_MEMBERS}+ members** to join the global leaderboard.\n"
                    f"> You currently have `{member_count}` members — `{needed}` more needed."
                ),
                ephemeral=True,
            )

        guild_data = await db.get_or_create_guild(guild.id)

        if guild_data.get("global_enrolled"):
            return await interaction.response.send_message(
                embed=Embeds.info("Your server is already enrolled in the global leaderboard."),
                ephemeral=True,
            )

        await db.enrol_guild_global(guild.id, guild.name)

        await interaction.response.send_message(
            embed=Embeds.success(
                f"**{guild.name}** is now enrolled in the global leaderboard! 🌐\n\n"
                f"> Run `/global invite` to add your server's invite link.\n"
                f"> Your server will appear on `/leaderboard global` ranked by total ¥ Yen."
            ),
        )
        logger.info("denki.global action=enrol guild_id=%d name=%r members=%d", guild.id, guild.name, member_count)

    @global_group.command(name="invite", description="Set your server's invite link on the global leaderboard. Admin only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def global_invite(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        guild = interaction.guild
        guild_data = await db.get_guild(guild.id)

        if not guild_data or not guild_data.get("global_enrolled"):
            return await interaction.response.send_message(
                embed=Embeds.error("Your server must be enrolled first. Run `/global enrol`."),
                ephemeral=True,
            )

        try:
            invite = await interaction.channel.create_invite(
                max_age=0,
                max_uses=0,
                unique=False,
                reason="Denki global leaderboard invite",
            )
            invite_url = invite.url
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=Embeds.error(
                    "I need **Create Invite** permission in this channel to generate a link."
                ),
                ephemeral=True,
            )
        except Exception as e:
            logger.error("global_invite: failed for guild %d: %s", guild.id, e)
            return await interaction.response.send_message(
                embed=Embeds.error("Failed to create invite. Please try again."),
                ephemeral=True,
            )

        await db.set_guild_invite(guild.id, invite_url)

        await interaction.response.send_message(
            embed=Embeds.success(
                f"Invite link set for **{guild.name}**!\n\n"
                f"> `{invite_url}`\n\n"
                f"> This will appear as a clickable link on `/leaderboard global`."
            ),
        )
        logger.info("denki.global action=invite guild_id=%d url=%s", guild.id, invite_url)

    @global_enrol.error
    @global_invite.error
    async def global_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=Embeds.error("You need **Administrator** permission to use this command."),
                ephemeral=True,
            )

    # ── Leaderboard implementations ───────────────────────────────────────────

    async def _leaderboard_server(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        guild = ctx_or_interaction.guild

        rows = await db.get_leaderboard_server(guild.id, limit=7)
        if not rows:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("No wallet data found for this server yet."),
                is_slash,
            )

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

    async def _leaderboard_global(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        rows = await db.get_global_leaderboard_guilds(limit=10)
        if not rows:
            return await _respond(
                ctx_or_interaction,
                Embeds.error(
                    "No servers have enrolled in the global leaderboard yet.\n"
                    "> Admins can run `/global enrol` to join (requires 100+ members)."
                ),
                is_slash,
            )

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for i, row in enumerate(rows):
            medal = medals[i] if i < len(medals) else f"`#{i+1}`"
            name  = row["guild_name"]
            invite = row.get("invite_url")
            display = f"[{name}]({invite})" if invite else f"**{name}**"
            lines.append(f"{medal} {display} — `¥{row['wallet_total']:,}`")

        embed = discord.Embed(
            description="> `🌐` *Global Leaderboard — Top Servers*\n\n" + "\n".join(lines),
            color=0xCD7F32,
        )
        embed.set_footer(text="Ranked by total ¥ Yen held by server members  •  /global enrol to join")
        await _respond(ctx_or_interaction, embed, is_slash)

    async def _safe_fetch_user(self, user_id: int) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user_id)
        except Exception:
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))