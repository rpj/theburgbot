import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import discord
from discord import app_commands

from theburgbot.common import CommandHandler, dprint
from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB, TheBurgBotKeyedJSONStore
from theburgbot.ical import iCalSyncer

IGNORE_DISCORD_IDS = ["ROLE_REACTION_MESSAGE_ID", "GUILD_ID"]


async def command_usage_embed(
    interaction: discord.Interaction,
    db_path: str,
    ical_syncer: iCalSyncer,
    command_dict: Dict[str, Any],
) -> discord.Embed:
    db = TheBurgBotDB(db_path)
    e = discord.Embed(title="Command Usage")
    for user_id, usage_count in await db._direct_exec(
        "select user_id, count(user_id) from cmd_use_log group by user_id"
    ):
        e.add_field(value=f"<@{user_id}>", name=usage_count)
    return e


async def discord_id_embed(
    interaction: discord.Interaction,
    db_path: str,
    ical_syncer: iCalSyncer,
    command_dict: Dict[str, Any],
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
    interaction: discord.Interaction,
    db_path: str,
    ical_syncer: iCalSyncer,
    command_dict: Dict[str, Any],
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


async def _events_listUrls(
    args: List[str], kv_store: TheBurgBotKeyedJSONStore, ical_syncer: iCalSyncer
):
    return "\n".join(
        [
            f"* {name}: {url}"
            for (name, url) in (
                await kv_store.get("ical/urls", default_producer=dict)
            ).items()
        ]
    )


async def _events_addUrl(
    args: List[str], kv_store: TheBurgBotKeyedJSONStore, ical_syncer: iCalSyncer
):
    output = ""
    if len(args) > 1:
        output += "Warning: multiple arguments after the first are ignored!\n\n"
    if len(args) == 0:
        return "Must provide a URL as the sole argument!"

    current: Dict[str, str] = await kv_store.get("ical/urls", default_producer=dict)
    [set_url, *name_comps] = args
    name = " ".join(name_comps)

    if name in current or set_url in list(current.values()):
        return "That is already in the set."

    parsed = urlparse(set_url)
    path = Path(parsed.path)
    if parsed.scheme != "https" or path.suffix != ".ics":
        return "Malformed URL!"

    current = {name: set_url, **current}
    await kv_store.set("ical/urls", current)
    ical_syncer.force_refresh()
    return await _events_listUrls(args, kv_store, ical_syncer)


_EVENT_CMD_PREFIX = "_events_"
_EVENT_CMD_ALLOWS = ["listUrls", "addUrl"]


async def events_embed(
    interaction: discord.Interaction,
    db_path: str,
    ical_syncer: iCalSyncer,
    command_dict: Dict[str, Any],
):
    [command, *args] = command_dict["events"].split(" ")

    e = discord.Embed(title="Events")
    e.add_field(name="Command", value=command)
    e.add_field(name="Args", value=", ".join(args))
    if command in _EVENT_CMD_ALLOWS:
        glbls = globals()
        cmd_func_name = f"{_EVENT_CMD_PREFIX}{command}"
        if cmd_func_name in glbls:
            kv_store = TheBurgBotKeyedJSONStore(db_path=db_path, namespace="events")
            cmd_output = await glbls[cmd_func_name](args, kv_store, ical_syncer)
            e.add_field(name="Output", value=cmd_output, inline=False)

    return e


EMBED_CREATORS = {
    "command_usage": command_usage_embed,
    "discord_ids": discord_id_embed,
    "list_invites": invites_embed,
    "events": events_embed,
}


async def admin_cmd_handler(
    interaction: discord.Interaction,
    db_path: str,
    ical_syncer: iCalSyncer,
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
        if param_name in kwargs and kwargs[param_name]:
            embeds.append(
                await embed_creator(
                    interaction, db_path, ical_syncer, command_dict=kwargs
                )
            )

    if not len(embeds):
        return await interaction.response.send_message(
            "No embeds created! :shrug:", ephemeral=True
        )

    await interaction.response.send_message(embeds=embeds, ephemeral=True)


class TheBurgBotUserCommand(CommandHandler):
    def register_command(
        self,
        client: "TheBurgBotClient",
        audit_log_decorator,
        command_use_logger,
        command_create_internal_logger,
        command_audit_logger,
        filtered_words,
    ):
        @client.tree.command(
            name="admin",
        )
        @app_commands.describe(
            command_usage="Include the command usage statistics embed. Can be sent publicly.",
            discord_ids="Include the relevant DiscordIDs embed. Can **not** be sent publicly.",
            list_invites="List all invites and their metadata.",
            events="Events."
            # public_reply="Send the reply to the channel (defaults to False)",
        )
        @audit_log_decorator("COMMAND_ADMIN", db_path=client.db_path)
        async def admin(
            interaction: discord.Interaction,
            command_usage: bool = False,
            discord_ids: bool = False,
            list_invites: bool = False,
            events: Optional[str] = None,
            # public_reply: bool = False,
        ):
            await command_use_logger(interaction)
            return await admin_cmd_handler(
                interaction,
                client.db_path,
                client.ical_syncer,
                **{
                    "command_usage": command_usage,
                    "discord_ids": discord_ids,
                    "list_invites": list_invites,
                    "events": events,
                    # "public_reply": public_reply,
                },
            )

        return "admin"
