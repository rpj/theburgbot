import asyncio
import datetime
import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import List, Optional

import discord
import httpx
from discord import app_commands

from theburgbot.common import CommandHandler

LOGGER = logging.getLogger("discord")
IGDB_URL = "https://api.igdb.com/v4"
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"


@dataclass
class Token:
    access_token: str = None
    expires_in: int = -1
    token_type: str = None
    refreshed_at: int = -1

    def __init__(self, access_token, expires_in, token_type, refreshed_at=None):
        self.access_token = access_token
        self.expires_in = expires_in
        self.token_type = token_type
        self.refreshed_at = (
            refreshed_at if refreshed_at else datetime.datetime.now().timestamp()
        )

    @property
    def expires_at(self) -> int:
        return self.refreshed_at + self.expires_in


TOKEN: Optional[Token] = None


async def igdb_refresh_token(*, audit_logger):
    global TOKEN
    cache_file = os.getenv("TWITCH_TOKEN_CACHE_FILE", ".twitch_token")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as cf:
            TOKEN = Token(**json.load(cf))
            LOGGER.info("Loaded Twitch token")
            await audit_logger(
                "LOADED_FROM_CACHE",
                asdict(TOKEN),
            )

    async def _refresher():
        global TOKEN
        while True:
            if TOKEN and TOKEN.expires_in != -1:
                now = datetime.datetime.now().timestamp()
                refresh_at = max(TOKEN.expires_at - (60 * 60), now)
                refresh_in = refresh_at - now
                LOGGER.info(
                    f"Twitch token refresh scheduled for {datetime.datetime.fromtimestamp(refresh_at)} "
                    f"(expires {datetime.datetime.fromtimestamp(TOKEN.expires_at)}) [{refresh_in}]"
                )
                await asyncio.sleep(refresh_in)
            cid = os.getenv("TWITCH_APP_ID")
            csk = os.getenv("TWITCH_APP_SECRET")
            url = f"{TWITCH_OAUTH_URL}?client_id={cid}&client_secret={csk}&grant_type=client_credentials"

            async with httpx.AsyncClient() as client:
                res = await client.post(url)
                token_obj = res.json()
                TOKEN = Token(**token_obj)
                with open(cache_file, "w") as cfw:
                    json.dump(asdict(TOKEN), cfw)
                LOGGER.critical("Refreshed Twitch token")
                await audit_logger(
                    "REFRESHED",
                    asdict(TOKEN),
                )

    asyncio.ensure_future(_refresher())


async def igdb_authed_request(*, path, data):
    url = f"{IGDB_URL}{path}"
    headers = {
        "Client-ID": os.getenv("TWITCH_APP_ID"),
        "Authorization": f"Bearer {TOKEN.access_token}",
    }
    async with httpx.AsyncClient() as client:
        return await client.post(
            url,
            data=data,
            headers=headers,
        )


IMAGE_URLER_PRE = "https://images.igdb.com/igdb/image/upload/t_"


def _image_urler(imghash, size="screenshot_med"):
    return f"{IMAGE_URLER_PRE}{size}/{imghash}.jpg"


def embed_from_game_entry(entry) -> discord.Embed:
    emb = discord.Embed(title=entry["name"])
    emb.description = entry["summary"]
    if all([key in entry for key in ["rating", "rating_count"]]):
        emb.add_field(
            name="Rating",
            value=f"~{int(entry['rating'])}/100 (samples: {entry['rating_count']})",
        )
    if "_artworks_fetched" in entry and len(entry["_artworks_fetched"]):
        art = entry["_artworks_fetched"][0]
        emb.set_image(url=_image_urler(art["image_id"]))
        emb.set_thumbnail(url=_image_urler(art["image_id"], size="thumb"))
    if "first_release_date" in entry:
        emb.add_field(
            name="First Release Date",
            value=datetime.datetime.fromtimestamp(entry["first_release_date"]),
        )
    if "url" in entry:
        emb.url = entry["url"]
    return emb


async def igdb_fetch_art(game_obj):
    art_res = await igdb_authed_request(
        path="/artworks", data=f'fields *; where game = {game_obj["id"]};'
    )
    if art_res.status_code == 200:
        return art_res.json()
    return []


async def igdb_lookup(*, query, exact_match, audit_logger) -> List[discord.Embed]:
    try:
        data = f'fields *; where name = "{query}";'
        res = await igdb_authed_request(path="/games", data=data)
        if res.status_code == 200:
            res_ids = res.json()
            if audit_logger:
                await audit_logger(
                    "FULL_RESULTS_START", {"query": query, "full_results": res_ids}
                )
            if exact_match:
                res_ids = [item for item in res_ids if item["name"] == query]
                if len(res_ids) > 1:
                    smallest_slug = min([len(item["slug"]) for item in res_ids])
                    res_ids = [
                        item for item in res_ids if len(item["slug"]) == smallest_slug
                    ]
            res_ids = [
                {**item, "_artworks_fetched": await igdb_fetch_art(item)}
                for item in res_ids
            ]
            if audit_logger:
                await audit_logger(
                    "FULL_RESULTS_END",
                    {
                        "query": query,
                        "full_results": res_ids,
                        "exact_match": exact_match,
                    },
                )
            return [embed_from_game_entry(entry) for entry in res_ids]
        else:
            print("FAIL:")
            print(res.text)
    except:
        LOGGER.error("igdb_lookup", exc_info=True)
    finally:
        pass
    return []


async def idgb_cmd_handler(
    command_create_internal_logger,
    command_audit_logger,
    interaction: discord.Interaction,
    query: str,
    public_reply: bool = False,
    exact_match: bool = True,
):
    audit_obj = {
        "query": query,
        "user_id": interaction.user.id,
        "exact": exact_match,
        "public": public_reply,
    }
    await interaction.response.defer(thinking=bool, ephemeral=not public_reply)
    await interaction.followup.send(
        f'Search result for "_{query}_":\n',
        embeds=await igdb_lookup(
            query=query,
            exact_match=exact_match,
            audit_logger=await command_create_internal_logger(
                "COMMAND_IGDB", audit_obj
            ),
        ),
        ephemeral=not public_reply,
    )
    await command_audit_logger(
        audit_obj,
        event="COMMAND_IGDB",
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
            name="igdb",
            description="Lookup video games on igdb.com",
        )
        @app_commands.describe(
            query="The search string",
            public_reply="Send the reply to the channel (defaults to False)",
            exact_match="Return exact matches only (defaults to True)",
        )
        @audit_log_decorator("COMMAND_IGDB", db_path=client.db_path)
        async def igdb(
            interaction: discord.Interaction,
            query: str,
            public_reply: bool = False,
            exact_match: bool = True,
        ):
            await command_use_logger(interaction)
            return await idgb_cmd_handler(
                command_create_internal_logger,
                command_audit_logger,
                interaction,
                query,
                public_reply,
                exact_match,
            )

        return "igdb"
