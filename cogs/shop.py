from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import db
from embeds import Embeds

logger = logging.getLogger("denki.shop")


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


class Shop(commands.Cog):
    """Shop commands — shop, buy, inventory, additem, removeitem, shop open."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # /shop

    @app_commands.command(name="shop", description="Browse the server shop and global shop.")
    async def shop_slash(self, interaction: discord.Interaction) -> None:
        await self._shop(interaction, is_slash=True)

    @commands.command(name="shop")
    async def shop_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._shop(ctx, is_slash=False)

    async def _shop(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        guild = ctx_or_interaction.guild

        config = await db.get_or_create_guild_config(guild.id)

        server_items: list[dict] = []
        if config["shop_enabled"]:
            server_items = await db.get_shop_items(guild_id=guild.id)

        global_items = await db.get_shop_items(guild_id=None)

        embed = Embeds.shop(
            guild_name=guild.name,
            server_items=server_items,
            global_items=global_items,
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # /buy

    @app_commands.command(name="buy", description="Purchase an item from the shop.")
    @app_commands.describe(item_id="Item ID shown in /shop")
    async def buy_slash(self, interaction: discord.Interaction, item_id: int) -> None:
        await self._buy(interaction, item_id=item_id, is_slash=True)

    @commands.command(name="buy")
    async def buy_prefix(self, ctx: commands.Context[Any], item_id: int) -> None:
        await self._buy(ctx, item_id=item_id, is_slash=False)

    async def _buy(self, ctx_or_interaction: Any, item_id: int, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        guild  = ctx_or_interaction.guild

        item = await db.get_shop_item(item_id)

        if not item or not item["active"]:
            return await _respond(
                ctx_or_interaction,
                Embeds.error(f"Item `{item_id}` not found or is no longer available."),
                is_slash,
            )

        # Server items can only be bought in their own server
        if item["guild_id"] and int(item["guild_id"]) != guild.id:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("This item is only available in its own server."),
                is_slash,
            )

        # Check already owned
        if await db.user_owns_item(author.id, item_id):
            return await _respond(
                ctx_or_interaction,
                Embeds.error(f"You already own **{item['name']}**."),
                is_slash,
            )

        price: int = int(item["price"])
        user_data = await db.get_or_create_user(author.id)
        if int(user_data["wallet"]) < price:
            return await _respond(
                ctx_or_interaction,
                Embeds.error(f"Insufficient funds. This item costs ¥{price:,}."),
                is_slash,
            )

        # Deduct and add to inventory
        try:
            await db.update_wallet(author.id, -price)
        except ValueError as e:
            return await _respond(ctx_or_interaction, Embeds.error(str(e)), is_slash)

        await db.add_to_inventory(author.id, item_id)
        await db.log_transaction(author.id, 0, price, "shop_purchase")

        # Assign Discord role if applicable
        if item["type"] == "role" and item.get("role_id"):
            try:
                role = guild.get_role(int(item["role_id"]))
                member = guild.get_member(author.id)
                if role and member:
                    await member.add_roles(role, reason="Denki shop purchase")
            except discord.Forbidden:
                logger.warning(f"Missing permissions to assign role {item['role_id']} in guild {guild.id}")
            except Exception as e:
                logger.error(f"Role assignment error: {e}")

        # Wallet was already fetched and reduced — compute new balance directly
        new_wallet = int(user_data["wallet"]) - price
        embed = Embeds.purchase(
            item_name=str(item["name"]),
            price=price,
            wallet=new_wallet,
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # /inventory

    @app_commands.command(name="inventory", description="View your inventory of owned items.")
    @app_commands.describe(user="User to check (defaults to you)")
    async def inventory_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        await self._inventory(interaction, user=user, is_slash=True)

    @commands.command(name="inventory", aliases=["i"])
    async def inventory_prefix(
        self,
        ctx: commands.Context[Any],
        user: discord.Member | None = None,
    ) -> None:
        await self._inventory(ctx, user=user, is_slash=False)

    async def _inventory(self, ctx_or_interaction: Any, user: discord.Member | None, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        author = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        target = user or author

        items = await db.get_inventory(target.id)

        embed = Embeds.inventory(user=target, items=items)
        await _respond(ctx_or_interaction, embed, is_slash)

    # /additem — admin only

    @app_commands.command(name="additem", description="Add an item to your server shop. Admin only.")
    @app_commands.describe(
        name="Item name",
        price="Item price in ¥ Yen",
        item_type="Item type",
        description="Item description",
        role="Discord role to assign (for role-type items)",
    )
    @app_commands.choices(item_type=[
        app_commands.Choice(name="Role",        value="role"),
        app_commands.Choice(name="Pet",         value="pet"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def additem_slash(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        item_type: str,
        description: str = "",
        role: discord.Role | None = None,
    ) -> None:
        await self._additem(
            interaction,
            name=name,
            price=price,
            item_type=item_type,
            description=description,
            role=role,
            is_slash=True,
        )

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def additem_prefix(
        self,
        ctx: commands.Context[Any],
        name: str,
        price: int,
        item_type: str,
        description: str = "",
    ) -> None:
        await self._additem(
            ctx,
            name=name,
            price=price,
            item_type=item_type,
            description=description,
            role=None,
            is_slash=False,
        )

    async def _additem(
        self,
        ctx_or_interaction: Any,
        name: str,
        price: int,
        item_type: str,
        description: str,
        role: discord.Role | None,
        is_slash: bool,
    ) -> None:
        await _defer(ctx_or_interaction, is_slash)
        guild = ctx_or_interaction.guild

        # Shop must be open
        config = await db.get_or_create_guild_config(guild.id)
        if not config["shop_enabled"]:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("Your server shop is not open yet. Use `/shop open` first."),
                is_slash,
            )

        if price <= 0:
            return await _respond(ctx_or_interaction, Embeds.error("Price must be greater than ¥0."), is_slash)

        if item_type not in ("role", "pet"):
            return await _respond(ctx_or_interaction, Embeds.error("Item type must be `role` or `pet`."), is_slash)

        role_id: int | None = role.id if role else None

        await db.create_shop_item(
            guild_id=guild.id,
            name=name,
            description=description,
            price=price,
            item_type=item_type,
            role_id=role_id,
        )

        embed = Embeds.success(f"Item **{name}** added to the shop for ¥{price:,}.")
        await _respond(ctx_or_interaction, embed, is_slash)

    # /removeitem — admin only

    @app_commands.command(name="removeitem", description="Remove an item from the server shop. Admin only.")
    @app_commands.describe(item_id="Item ID to remove")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeitem_slash(self, interaction: discord.Interaction, item_id: int) -> None:
        await self._removeitem(interaction, item_id=item_id, is_slash=True)

    @commands.command(name="removeitem")
    @commands.has_permissions(administrator=True)
    async def removeitem_prefix(self, ctx: commands.Context[Any], item_id: int) -> None:
        await self._removeitem(ctx, item_id=item_id, is_slash=False)

    async def _removeitem(self, ctx_or_interaction: Any, item_id: int, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        guild = ctx_or_interaction.guild

        item = await db.get_shop_item(item_id)

        if not item:
            return await _respond(ctx_or_interaction, Embeds.error(f"Item `{item_id}` not found."), is_slash)

        # Can only remove items from own server
        if not item["guild_id"] or int(item["guild_id"]) != guild.id:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("You can only remove items from your own server shop."),
                is_slash,
            )

        if not item["active"]:
            return await _respond(ctx_or_interaction, Embeds.error("This item is already removed."), is_slash)

        await db.disable_shop_item(item_id)

        embed = Embeds.success(f"Item **{item['name']}** has been removed from the shop.")
        await _respond(ctx_or_interaction, embed, is_slash)

    # /shop open — admin only

    @app_commands.command(name="shopopen", description="Open your server shop. Costs ¥10,000 from the vault. Admin only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def shopopen_slash(self, interaction: discord.Interaction) -> None:
        await self._shopopen(interaction, is_slash=True)

    @commands.command(name="shopopen", aliases=["sopen"])
    @commands.has_permissions(administrator=True)
    async def shopopen_prefix(self, ctx: commands.Context[Any]) -> None:
        await self._shopopen(ctx, is_slash=False)

    async def _shopopen(self, ctx_or_interaction: Any, is_slash: bool) -> None:
        await _defer(ctx_or_interaction, is_slash)
        guild = ctx_or_interaction.guild

        season = await db.get_active_season()
        if not season:
            return await _respond(
                ctx_or_interaction,
                Embeds.error("There is no active season. The vault must have funds to open a shop."),
                is_slash,
            )

        season_id: int = int(season["season_id"])

        try:
            await db.open_server_shop(guild.id, season_id)
        except ValueError as e:
            return await _respond(ctx_or_interaction, Embeds.error(str(e)), is_slash)

        embed = Embeds.success(
            f"Your server shop is now open! ¥{db.SHOP_OPEN_COST:,} has been deducted from the vault.\n"
            f"> Use `/additem` to add items."
        )
        await _respond(ctx_or_interaction, embed, is_slash)

    # Error handlers

    @additem_slash.error
    @removeitem_slash.error
    @shopopen_slash.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=Embeds.error("You need **Administrator** permission to use this command."),
                ephemeral=True,
            )



async def _defer(ctx_or_interaction: Any, is_slash: bool, ephemeral: bool = False) -> None:
    """Defer a slash interaction immediately to extend the 3-second response window."""
    if is_slash and not ctx_or_interaction.response.is_done():
        await ctx_or_interaction.response.defer(ephemeral=ephemeral)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shop(bot))