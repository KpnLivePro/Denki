from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from embeds import Embeds

# Command map — single source of truth for /help and !d help
# Every command we are building is listed here grouped by module.
# Each entry: { name, aliases, usage, description, examples, notes }

COMMAND_MAP: dict[str, list[dict]] = {
    "economy": [
        {
            "name": "/balance",
            "aliases": ["!d bal", "!d b"],
            "usage": "/balance [user]",
            "description": "View your global ¥ Yen wallet, server bank balance, and invested amount.",
            "examples": ["/balance", "/balance @user", "!d bal", "!d b @user"],
            "notes": "Wallet is global. Bank and invested amounts are per-server per-season.",
        },
        {
            "name": "/daily",
            "aliases": ["!d daily", "!d d"],
            "usage": "/daily",
            "description": "Claim your daily ¥ Yen reward. 24-hour cooldown.",
            "examples": ["/daily", "!d daily", "!d d"],
            "notes": "Can be disabled by server admins. Payout is boosted by server tier.",
        },
        {
            "name": "/work",
            "aliases": ["!d work", "!d w"],
            "usage": "/work",
            "description": "Work a random job to earn ¥ Yen. 1-hour cooldown.",
            "examples": ["/work", "!d work", "!d w"],
            "notes": "Can be disabled by server admins. Payout is boosted by server tier.",
        },
        {
            "name": "/rob",
            "aliases": ["!d rob", "!d r"],
            "usage": "/rob <user>",
            "description": "Attempt to steal ¥ Yen from another user's pocket. 2-hour cooldown.",
            "examples": ["/rob @user", "!d rob @user", "!d r @user"],
            "notes": "40% success chance. Fail and you pay a fine. Can be disabled by admins.",
        },
        {
            "name": "/pay",
            "aliases": ["!d pay", "!d p"],
            "usage": "/pay <user> <amount>",
            "description": "Send ¥ Yen from your pocket to another user. No fee.",
            "examples": ["/pay @user 500", "!d pay @user 500", "!d p @user 1000"],
            "notes": None,
        },
    ],
    "gambling": [
        {
            "name": "/coinflip",
            "aliases": ["!d coinflip", "!d cf"],
            "usage": "/coinflip <heads|tails> <amount>",
            "description": "Bet on a coin flip. 49% chance to double your bet.",
            "examples": ["/coinflip heads 500", "!d cf tails 1000"],
            "notes": "House edge: 2%. Amount can be `all` to bet your full pocket.",
        },
        {
            "name": "/slots",
            "aliases": ["!d slots", "!d sl"],
            "usage": "/slots <amount>",
            "description": "Spin a 3-reel slot machine. Matching symbols pay out multipliers.",
            "examples": ["/slots 200", "!d slots 500", "!d sl all"],
            "notes": "3 rare = 10x  •  3 common = 3x  •  2 match = 1.5x  •  no match = 0x",
        },
        {
            "name": "/blackjack",
            "aliases": ["!d blackjack", "!d bj"],
            "usage": "/blackjack <amount>",
            "description": "Play blackjack against the dealer. Get closer to 21 without busting.",
            "examples": ["/blackjack 500", "!d bj 1000"],
            "notes": "Win = 1x  •  Blackjack = 1.5x  •  Dealer hits until 17.",
        },
        {
            "name": "/guess",
            "aliases": ["!d guess", "!d g"],
            "usage": "/guess <number|letter> <amount>",
            "description": "Guess a number or letter to win a multiplied payout.",
            "examples": ["/guess number 500", "/guess letter 200", "!d g number 100"],
            "notes": "Number easy (1-10) = 8x  •  Number hard (1-50) = 30x  •  Letter (A-Z) = 20x",
        },
    ],
    "investing": [
        {
            "name": "/invest",
            "aliases": ["!d invest", "!d inv"],
            "usage": "/invest <amount>",
            "description": "Invest ¥ Yen from your pocket into your server's season vault. Locked until season ends.",
            "examples": ["/invest 1000", "!d invest 500", "!d inv 2000"],
            "notes": "Must be a server member for 30+ days. Minimum ¥100. Top 3 investors earn a season bonus.",
        },
        {
            "name": "/vault",
            "aliases": ["!d vault", "!d v"],
            "usage": "/vault",
            "description": "View the current server vault — total pooled, days remaining, and top 7 investors.",
            "examples": ["/vault", "!d vault", "!d v"],
            "notes": None,
        },
    ],
    "season": [
        {
            "name": "/season",
            "aliases": ["!d season", "!d s"],
            "usage": "/season",
            "description": "View the current season — name, theme, days remaining, and vault total.",
            "examples": ["/season", "!d season", "!d s"],
            "notes": "Seasons last 30 days. Server banks reset each season. Personal wallets are never wiped.",
        },
    ],
    "shop": [
        {
            "name": "/shop",
            "aliases": ["!d shop"],
            "usage": "/shop",
            "description": "Browse the server shop and global shop.",
            "examples": ["/shop", "!d shop"],
            "notes": "Server shops sell roles and pets. Global shop sells badges and collectibles.",
        },
        {
            "name": "/buy",
            "aliases": ["!d buy"],
            "usage": "/buy <item_id>",
            "description": "Purchase an item from the shop. Deducted from your pocket.",
            "examples": ["/buy 3", "!d buy 5"],
            "notes": None,
        },
        {
            "name": "/inventory",
            "aliases": ["!d inventory", "!d i"],
            "usage": "/inventory [user]",
            "description": "View your (or another user's) inventory of owned items.",
            "examples": ["/inventory", "/inventory @user", "!d i"],
            "notes": "Inventory is global — follows your wallet across all servers.",
        },
        {
            "name": "/additem",
            "aliases": ["!d additem"],
            "usage": "/additem <name> <price> <type> [description] [role]",
            "description": "Add an item to your server shop. Admin only.",
            "examples": ["/additem VIP 5000 role VIP member access @VIPRole"],
            "notes": "Types: `role` `pet`  •  Server shop must be open first.",
        },
        {
            "name": "/removeitem",
            "aliases": ["!d removeitem"],
            "usage": "/removeitem <item_id>",
            "description": "Disable an item from the shop. Admin only.",
            "examples": ["/removeitem 3"],
            "notes": "Item is soft-deleted — history is preserved.",
        },
    ],
    "leaderboard": [
        {
            "name": "/leaderboard server",
            "aliases": ["!d lb server", "!d lbs", "!d l server"],
            "usage": "/leaderboard server",
            "description": "Top 7 richest wallet holders in this server.",
            "examples": ["/leaderboard server", "!d lbs", "!d l server"],
            "notes": "Available in all servers.",
        },
        {
            "name": "/leaderboard investors",
            "aliases": ["!d lb investors", "!d lbi", "!d l investors"],
            "usage": "/leaderboard investors",
            "description": "Top 7 investors in this server's current season vault.",
            "examples": ["/leaderboard investors", "!d lbi", "!d l investors"],
            "notes": "Resets each season.",
        },
        {
            "name": "/leaderboard global",
            "aliases": ["!d lb global", "!d lbg", "!d l global"],
            "usage": "/leaderboard global",
            "description": "Top 7 richest players globally across all servers.",
            "examples": ["/leaderboard global", "!d lbg"],
            "notes": "Only available in servers with 250+ members.",
        },
    ],
    "setup": [
        {
            "name": "/init",
            "aliases": [],
            "usage": "/init",
            "description": "Step-by-step wizard to set up Denki for your server. Sets notification channel, role, and earn toggles.",
            "examples": ["/init"],
            "notes": "Administrator permission required. Ephemeral — only you can see it.",
        },
        {
            "name": "/config",
            "aliases": ["!d cfg"],
            "usage": "/config",
            "description": "View your current server configuration at any time.",
            "examples": ["/config", "!d cfg"],
            "notes": None,
        },
    ],
    "admin": [
        {
            "name": "/config",
            "aliases": ["!d config", "!d cfg"],
            "usage": "/config",
            "description": "Configure Denki for your server — notification channel, role, and earn toggles.",
            "examples": ["/config", "!d config"],
            "notes": "Administrator permission required.",
        },
        {
            "name": "/earnsettings",
            "aliases": ["!d earnsettings"],
            "usage": "/earnsettings",
            "description": "Choose which earning commands are enabled in your server. At least one must stay on.",
            "examples": ["/earnsettings", "!d earnsettings"],
            "notes": "Options: daily / work / rob. All three cannot be disabled.",
        },
        {
            "name": "/denkireport",
            "aliases": ["!d report"],
            "usage": "/denkireport <user> <reason>",
            "description": "Report a user to the bot owner for review.",
            "examples": ["/denkireport @user exploiting the economy"],
            "notes": "Report is logged and a DM is sent to the bot owner. Admins cannot ban users directly.",
        },
        {
            "name": "/shop open",
            "aliases": ["!d shop open", "!d sopen"],
            "usage": "/shop open",
            "description": "Open a shop for your server. Costs ¥10,000 from the season vault.",
            "examples": ["/shop open", "!d sopen"],
            "notes": "One-time fee per server. Shop stays open across seasons once opened.",
        },
        {
            "name": "/season set",
            "aliases": ["!d season set"],
            "usage": "/season set <name> [theme]",
            "description": "Set the name and theme for the upcoming season. Sudo only.",
            "examples": ["/season set 'Winter Arc' 'Ice and snow'"],
            "notes": "Sudo command — bot owner only.",
        },
    ],
}

# Flat alias → command name lookup for /help <command>
_ALIAS_MAP: dict[str, tuple[str, dict]] = {}
for _module, _cmds in COMMAND_MAP.items():
    for _cmd in _cmds:
        _ALIAS_MAP[_cmd["name"].lower()] = (_module, _cmd)
        for _alias in _cmd.get("aliases", []):
            _ALIAS_MAP[_alias.lower()] = (_module, _cmd)


class Help(commands.Cog):
    """Help command — /help and !d help"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Learn about Denki or look up a command.")
    @app_commands.describe(
        module="Browse all commands in a module",
        command="Look up a specific command by name",
    )
    @app_commands.choices(module=[
        app_commands.Choice(name="Economy  —  balance, daily, work, rob, pay",          value="economy"),
        app_commands.Choice(name="Gambling  —  coinflip, slots, blackjack, guess",       value="gambling"),
        app_commands.Choice(name="Investing  —  invest, vault",                          value="investing"),
        app_commands.Choice(name="Season  —  season info",                               value="season"),
        app_commands.Choice(name="Shop  —  shop, buy, inventory, additem, removeitem",   value="shop"),
        app_commands.Choice(name="Leaderboard  —  server, investors, global",            value="leaderboard"),
        app_commands.Choice(name="Admin  —  config, earnsettings, denkireport",          value="admin"),
    ])
    async def help_slash(
        self,
        interaction: discord.Interaction,
        module: Optional[str] = None,
        command: Optional[str] = None,
    ) -> None:
        await self._send_help(interaction, module=module, command=command, is_slash=True)

    @commands.command(name="help", aliases=["h"])
    async def help_prefix(
        self,
        ctx: commands.Context,
        module: Optional[str] = None,
        command: Optional[str] = None,
    ) -> None:
        await self._send_help(ctx, module=module, command=command, is_slash=False)

    async def _send_help(
        self,
        ctx_or_interaction,
        module: Optional[str],
        command: Optional[str],
        is_slash: bool,
    ) -> None:
        # Resolve command lookup first — takes priority over module
        if command:
            key = command.lower()
            match = _ALIAS_MAP.get(key)
            if not match:
                # Try partial match
                match = next(
                    ((m, c) for k, (m, c) in _ALIAS_MAP.items() if key in k),
                    None,
                )
            if match:
                _, cmd = match
                embed = Embeds.help_command(
                    name=cmd["name"],
                    aliases=cmd.get("aliases", []),
                    usage=cmd["usage"],
                    description=cmd["description"],
                    examples=cmd.get("examples", []),
                    notes=cmd.get("notes"),
                )
            else:
                embed = Embeds.error(f"Command `{command}` not found. Use `/help` to see all modules.")
        elif module:
            key = module.lower()
            cmds = COMMAND_MAP.get(key)
            if cmds:
                embed = Embeds.help_module(module=key, commands=cmds)
            else:
                embed = Embeds.error(
                    f"Module `{module}` not found. Available: {', '.join(f'`{m}`' for m in COMMAND_MAP)}"
                )
        else:
            embed = Embeds.help_home()

        if is_slash:
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))