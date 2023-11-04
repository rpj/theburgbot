import discord
import nltk
import requests
from discord import app_commands

from theburgbot import constants
from theburgbot.client import TheBurgBotClient
from theburgbot.cmd_handlers.admin import admin_cmd_handler
from theburgbot.cmd_handlers.gpt import gpt_cmd_handler
from theburgbot.cmd_handlers.igdb import idgb_cmd_handler
from theburgbot.cmd_handlers.new_invite import invite_cmd_handler
from theburgbot.cmd_handlers.scry import scry_cmd_handler
from theburgbot.cmd_handlers.user import user_cmd_handler
from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async


def register_slash_commands(
    client: TheBurgBotClient,
    min_word_length: int = constants.MIN_WORD_LENGTH,
    max_word_length: int = constants.MAX_WORD_LENGTH,
) -> discord.ext.commands.Bot:
    nltk.download("words")
    badwords = requests.get(constants.LDNOOBW_URL, timeout=30).text.split("\n")
    filtered_words = [
        word
        for word in list(nltk.corpus.words.words())
        if min_word_length <= len(word) <= max_word_length
        and not word[0].isupper()
        and not word in badwords
    ]

    async def command_use_log(interaction: discord.Interaction):
        return await TheBurgBotDB(client.db_path).cmd_use_log(
            interaction.command.name, interaction.user.id, interaction.user.display_name
        )

    async def command_audit_logger(obj, event):
        return await TheBurgBotDB(client.db_path).audit_log_event_json(obj, event=event)

    async def command_create_internal_logger(event_pre, pre_obj):
        async def _int_logger(event_post, obj):
            return await command_audit_logger(
                {**pre_obj, **obj},
                event=f"{event_pre}__{event_post}",
            )

        return _int_logger

    @client.tree.command(
        name="invite",
        description="Create a one-time-use invite code. "
        "The response will be shown only to you.",
    )
    @app_commands.describe(
        invite_for="Who this invite is for (Discord user or real name)"
    )
    @audit_log_start_end_async("COMMAND_INVITE", db_path=client.db_path)
    async def create_invite(interaction: discord.Interaction, invite_for: str):
        await command_use_log(interaction)
        return await invite_cmd_handler(
            command_audit_logger,
            interaction,
            invite_for,
            client.db_path,
            filtered_words,
        )

    @client.tree.command(
        name="scry",
        description="Lookup Magic: The Gathering card info on scryfall.com",
    )
    @app_commands.describe(
        query="The search string",
        public_reply="Send the reply to the channel (defaults to False)",
        exact_match="Return exact matches only (defaults to True)",
    )
    @audit_log_start_end_async("COMMAND_SCRY", db_path=client.db_path)
    async def scryfall(
        interaction: discord.Interaction,
        query: str,
        public_reply: bool = False,
        exact_match: bool = True,
    ):
        await command_use_log(interaction)
        return await scry_cmd_handler(
            command_create_internal_logger,
            command_audit_logger,
            interaction,
            query,
            public_reply,
            exact_match,
        )

    @client.tree.command(
        name="gpt",
        description="Talk to ChatGPT. Please use sparingly: it isn't free!",
    )
    @app_commands.describe(
        prompt="What to ask of ChatGPT",
        public_reply="Send the reply to the channel (defaults to False)",
        shorten_response="Append instruction to the prompt to keep the response short",
        model="The model to use (only available to Admins)",
    )
    @audit_log_start_end_async("COMMAND_GPT", db_path=client.db_path)
    async def gpt(
        interaction: discord.Interaction,
        prompt: str,
        public_reply: bool = False,
        shorten_response: bool = True,
        model: str = None,
    ):
        await command_use_log(interaction)
        if model is not None:
            member = client.get_guild(discord_ids.GUILD_ID).get_member(
                interaction.user.id
            )
            if member.get_role(discord_ids.ADMINS_ROLE_ID) is None:
                return await interaction.response.send_message(
                    "You do not have permission to use the `model` option. Please remove it and try again.",
                    ephemeral=True,
                )
        return await gpt_cmd_handler(
            command_create_internal_logger,
            command_audit_logger,
            client.db_path,
            interaction,
            prompt,
            public_reply,
            shorten_response,
            model,
        )

    @client.tree.command(
        name="igdb",
        description="Lookup video games on igdb.com",
    )
    @app_commands.describe(
        query="The search string",
        public_reply="Send the reply to the channel (defaults to False)",
        exact_match="Return exact matches only (defaults to True)",
    )
    @audit_log_start_end_async("COMMAND_IGDB", db_path=client.db_path)
    async def igdb(
        interaction: discord.Interaction,
        query: str,
        public_reply: bool = False,
        exact_match: bool = True,
    ):
        await command_use_log(interaction)
        return await idgb_cmd_handler(
            command_create_internal_logger,
            command_audit_logger,
            interaction,
            query,
            public_reply,
            exact_match,
        )

    @client.tree.command(
        name="admin",
    )
    @app_commands.describe(
        command_usage="Include the command usage statistics embed. Can be sent publicly.",
        discord_ids="Include the relevant DiscordIDs embed. Can **not** be sent publicly.",
        list_invites="List all invites and their metadata.",
        # public_reply="Send the reply to the channel (defaults to False)",
    )
    @audit_log_start_end_async("COMMAND_ADMIN", db_path=client.db_path)
    async def admin(
        interaction: discord.Interaction,
        command_usage: bool = False,
        discord_ids: bool = False,
        list_invites: bool = False,
        # public_reply: bool = False,
    ):
        await command_use_log(interaction)
        return await admin_cmd_handler(
            interaction,
            client.db_path,
            **{
                "command_usage": command_usage,
                "discord_ids": discord_ids,
                "list_invites": list_invites,
                # "public_reply": public_reply,
            },
        )

    @client.tree.command(
        name="user",
        description="Commands related to actions you've performed with the bot",
    )
    @app_commands.describe(
        list_pages="Lists all the pages the bot has created on your behalf"
    )
    @audit_log_start_end_async("COMMAND_USER", db_path=client.db_path)
    async def user(
        interaction: discord.Interaction,
        list_pages: bool = False,
    ):
        await command_use_log(interaction)
        return await user_cmd_handler(
            command_create_internal_logger,
            command_audit_logger,
            client.db_path,
            interaction,
            list_pages,
        )

    # return for register_slash_commands
    return client
