import json
from dataclasses import asdict

import discord

from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB

IGNORE_DISCORD_IDS = ["ROLE_REACTION_MESSAGE_ID", "GUILD_ID"]


async def command_usage_embed(
    interaction: discord.Interaction, db_path: str
) -> discord.Embed:
    db = TheBurgBotDB(db_path)
    e = discord.Embed(title="Command Usage")
    for display_name, usage_count in await db._direct_exec(
        "select display_name, count(display_name) from cmd_use_log group by display_name"
    ):
        e.add_field(name=display_name, value=usage_count)
    return e


async def discord_id_embed(
    interaction: discord.Interaction, db_path: str
) -> discord.Embed:
    e = discord.Embed(title="Discord IDs")
    msg = ""

    def xfer_v(key, value):
        for search, xf_func in {
            "CHANNEL": lambda s: f"<#{s}>",
            "ROLE": lambda s: f"<@&{s}>",
        }.items():
            if search in key:
                return xf_func(value)
        return value

    msg += "\n".join(
        [
            f"{key}: {xfer_v(key, v_id)}"
            for (key, v_id) in filter(
                lambda kvt: kvt[0] not in IGNORE_DISCORD_IDS,
                asdict(discord_ids).items(),
            )
        ]
    )

    e.description = msg
    return e


async def invites_embed(
    interaction: discord.Interaction, db_path: str
) -> discord.Embed:
    invites = await TheBurgBotDB(db_path).get_invites()
    e = discord.Embed(title="Invites")
    for inv_tuple in invites:
        (
            passphrase,
            _create,
            code,
            redeemed_at,
            _requestor,
            requestor_id,
            inv_for,
            inv_id,
        ) = inv_tuple
        e.add_field(
            name=f'{" ".join(json.loads(passphrase))}',
            value=f"id: `{inv_id}`\nfor: _**{inv_for}**_\nrequested by: <@{requestor_id}>"
            + (
                f"\nredeemed: {redeemed_at}\ncode: {code}"
                if redeemed_at and code
                else ""
            ),
            inline=False,
        )
    return e


EMBED_CREATORS = {
    "command_usage": command_usage_embed,
    "discord_ids": discord_id_embed,
    "list_invites": invites_embed,
}


async def admin_cmd_handler(
    interaction: discord.Interaction,
    db_path: str,
    *,
    public_reply: bool = False,
    **kwargs,
):
    if not any(
        [
            embed_is_enabled
            for (_param_name, embed_is_enabled) in list(
                filter(lambda kvt: kvt[0] in EMBED_CREATORS.keys(), kwargs.items())
            )
        ]
    ):
        return await interaction.response.send_message(
            "You didn't choose any embeds!", ephemeral=True
        )

    # TODO: handle public_reply!
    embeds = []
    for param_name, embed_creator in EMBED_CREATORS.items():
        if param_name in kwargs and kwargs[param_name] is True:
            embeds.append(await embed_creator(interaction, db_path))

    await interaction.response.send_message(embeds=embeds, ephemeral=True)
