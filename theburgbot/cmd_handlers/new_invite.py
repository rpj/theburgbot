import json
import random
from typing import List

import discord
import nanoid
from discord import app_commands

from theburgbot import constants
from theburgbot.common import CommandHandler
from theburgbot.db import TheBurgBotDB

# todo: store in DB so that bot crash doesn't wipe these out?
INFLIGHT_INTERACTIONS = {}


def create_buttons_view(interaction_id: str):
    class ButtonsView(discord.ui.View):
        def __init__(self, *, timeout=180):
            super().__init__(timeout=timeout)

        @discord.ui.button(
            label="Try another...",
            style=discord.ButtonStyle.blurple,
            custom_id=f"AGAIN:{interaction_id}",
        )
        async def try_again_button(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ):
            inflight_ref = INFLIGHT_INTERACTIONS[button.custom_id.split(":")[-1]]
            (embed, code) = await create_new_invite(**inflight_ref)
            inflight_ref["try_phrase_json"] = code
            await interaction.response.edit_message(embeds=[embed])

        @discord.ui.button(
            label="Use this one!",
            style=discord.ButtonStyle.success,
            custom_id=f"ACCEPT:{interaction_id}",
        )
        async def accept_invite_button(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ):
            interaction_id = button.custom_id.split(":")[-1]
            invite_key = await accept_invite(interaction, interaction_id)
            inflight = INFLIGHT_INTERACTIONS[interaction_id]
            accepted_embed = create_embed(
                inflight["invite_for"], inflight["try_phrase_json"]
            )
            accepted_embed.set_footer(text=f"(ref: {invite_key})")
            await interaction.response.edit_message(
                content=f"## Invite created!"
                f"\n\nBe sure to share or save this: it will disappear eventually!\n",
                embeds=[accepted_embed],
                view=None,
            )
            del INFLIGHT_INTERACTIONS[interaction_id]

    return ButtonsView()


async def generate_new_passphrase(
    db_path: str,
    filtered_words: List[str],
    num_words: int,
):
    def _generate_one_passphrase() -> str:
        pick_words = list(filtered_words)
        random.shuffle(pick_words)
        return pick_words[0:num_words]

    while True:
        try_phrase_list = _generate_one_passphrase()
        try_phrase_json = json.dumps(try_phrase_list)
        db = TheBurgBotDB(db_path)
        if not await db.passphrase_exists(try_phrase_json):
            return try_phrase_json


def create_embed(invite_for: str, try_phrase_json: str, **kwargs):
    invite_emb = discord.Embed(title=f"{invite_for}'s invite:")
    invite_emb.url = constants.SITE_URL
    invite_emb.description = (
        f"## {(constants.SEPERATOR + '## ').join(json.loads(try_phrase_json))}"
    )
    return invite_emb


async def accept_invite(interaction: discord.Interaction, interaction_id: str):
    db = TheBurgBotDB(INFLIGHT_INTERACTIONS[interaction_id]["db_path"])
    try_phrase_json = INFLIGHT_INTERACTIONS[interaction_id]["try_phrase_json"]
    invite_for = INFLIGHT_INTERACTIONS[interaction_id]["invite_for"]
    return await db.add_new_invite(
        try_phrase_json,
        interaction.user.display_name,
        interaction.user.id,
        invite_for,
    )


async def create_new_invite(
    db_path: str,
    filtered_words: List[str],
    invite_for: str,
    num_words: int = constants.NUM_WORDS,
    **kwargs,
) -> discord.Embed:
    try_phrase_json = await generate_new_passphrase(db_path, filtered_words, num_words)
    return (create_embed(invite_for, try_phrase_json), try_phrase_json)


async def invite_cmd_handler(
    command_audit_logger,
    interaction: discord.Interaction,
    invite_for: str,
    db_path,
    filtered_words,
):
    global INFLIGHT_INTERACTIONS
    interaction_id = nanoid.generate()
    (embed, code) = await create_new_invite(
        db_path,
        filtered_words,
        invite_for,
    )
    # discord.Interaction convieniently has an .extras dictionary that users can put arbitrary data into!
    # *except* it's a _new instance_ (with .extras cleared!) passed into the button handler functions.
    # what f-ing good is that, then!? this is the *exact* use case it should be useful for! :facepalm:
    # I think discord.py may have been a mistake...
    INFLIGHT_INTERACTIONS[interaction_id] = {
        "try_phrase_json": code,
        "invite_for": invite_for,
        "db_path": db_path,
        "filtered_words": filtered_words,
    }
    await interaction.response.send_message(
        embed=embed,
        view=create_buttons_view(interaction_id),
        ephemeral=True,
    )
    await command_audit_logger(
        {
            "for": invite_for,
            "user_id": interaction.user.id,
            "passphrase": code,
        },
        event="COMMAND_INVITE",
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
            name="invite",
            description="Create a one-time-use invite code. "
            "The response will be shown only to you.",
        )
        @app_commands.describe(
            invite_for="Who this invite is for (Discord user or real name)"
        )
        @audit_log_decorator("COMMAND_INVITE", db_path=client.db_path)
        async def create_invite(interaction: discord.Interaction, invite_for: str):
            await command_use_logger(interaction)
            return await invite_cmd_handler(
                command_audit_logger,
                interaction,
                invite_for,
                client.db_path,
                filtered_words,
            )

        return "invite"
