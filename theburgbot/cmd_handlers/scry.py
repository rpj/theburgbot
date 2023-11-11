import datetime
import logging
import urllib.parse
from typing import List

import discord
import httpx
from discord import app_commands

from theburgbot.common import CommandHandler

SCRYFALL_URL = "https://api.scryfall.com"

LOGGER = logging.getLogger("discord")


async def scry_lookup(
    requestor: discord.Member,
    lookup: str,
    exact_match: bool,
    max_embeds: int = 10,
    *,
    audit_logger,
) -> List[discord.Embed]:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SCRYFALL_URL}/cards/search?dir=desc&q={urllib.parse.quote(lookup)}"
        )
        if res.status_code != 200:
            return ([], False)
        res_json = res.json()
        res_list = res_json["data"]
        await audit_logger("FULL_RESULTS", {"results": res_list})
        if exact_match:
            res_list = [li for li in res_list if li["name"] == lookup]
        ret_list = []

        def _emb_from_item_obj(item):
            emb = discord.Embed(title=item["name"])
            if "scryfall_uri" in item:
                emb.url = item["scryfall_uri"]
            emb.set_author(
                name=requestor.display_name, icon_url=requestor.display_avatar.url
            )
            emb.timestamp = datetime.datetime.now()

            if "image_uris" in item and "png" in item["image_uris"]:
                emb.set_image(url=item["image_uris"]["png"])

            if "prices" in item:
                for name, price in [
                    (i[0].replace("_", " "), i[1])
                    for i in item["prices"].items()
                    if i[0].startswith("usd") and i[1]
                ]:
                    emb.add_field(
                        name=f"Price, {name.upper()}", value=price, inline=True
                    )

            if "related_uris" in item and "gatherer" in item["related_uris"]:
                emb.add_field(
                    name="Gatherer",
                    value=f'[{item["name"]}]({item["related_uris"]["gatherer"]})',
                )
            return emb

        for item in res_list:
            if len(ret_list) == max_embeds:
                return (ret_list, True)
            if "card_faces" in item:
                for face in item["card_faces"]:
                    ret_list.append(_emb_from_item_obj(face))
            else:
                ret_list.append(_emb_from_item_obj(item))
        return (ret_list, False)


async def scry_cmd_handler(
    command_create_internal_logger,
    command_audit_logger,
    interaction: discord.Interaction,
    query: str,
    public_reply: bool = False,
    exact_match: bool = True,
):
    audit_obj = {
        "query": query,
        "exact": exact_match,
        "public": public_reply,
        "user_id": interaction.user.id,
    }
    await interaction.response.defer(thinking=bool, ephemeral=not public_reply)
    (q_list, was_more) = await scry_lookup(
        interaction.user,
        query,
        exact_match,
        audit_logger=await command_create_internal_logger("COMMAND_SCRY", audit_obj),
    )
    if len(q_list):
        msg = f'## Scryfall search results for "{query}"'
        if was_more:
            msg = f"{msg}\n_More results were available than can be shown here! Try narrowing your search._\n"
        await interaction.followup.send(msg, embeds=q_list)
    else:
        await interaction.followup.send("No results found (or error encountered)!")
    await command_audit_logger(
        {
            **audit_obj,
            "was_more": was_more,
            "num_results": len(q_list),
        },
        event="COMMAND_SCRY",
    )


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
            name="scry",
            description="Lookup Magic: The Gathering card info on scryfall.com",
        )
        @app_commands.describe(
            query="The search string",
            public_reply="Send the reply to the channel (defaults to False)",
            exact_match="Return exact matches only (defaults to True)",
        )
        @audit_log_decorator("COMMAND_SCRY", db_path=client.db_path)
        async def scryfall(
            interaction: discord.Interaction,
            query: str,
            public_reply: bool = False,
            exact_match: bool = True,
        ):
            await command_use_logger(interaction)
            return await scry_cmd_handler(
                command_create_internal_logger,
                command_audit_logger,
                interaction,
                query,
                public_reply,
                exact_match,
            )

        return "scry"
