import importlib
from pathlib import Path

import discord
import nltk
import requests

from theburgbot import constants
from theburgbot.client import TheBurgBotClient
from theburgbot.common import CommandHandler
from theburgbot.common import dprint as print
from theburgbot.db import (audit_log_start_end_async, command_audit_logger,
                           command_create_internal_logger, command_use_log)


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

    async def _command_use_log(interaction: discord.Interaction):
        return await command_use_log(client.db_path, interaction)

    async def _command_audit_logger(interaction: discord.Interaction, **kwargs):
        return await command_audit_logger(client.db_path, interaction, **kwargs)

    async def _command_create_internal_logger(event_pre, pre_obj):
        return await command_create_internal_logger(client.db_path, event_pre, pre_obj)

    expect_protocol_methods = [x for x in dir(CommandHandler) if not x.startswith("_")]
    cmd_handlers_path = Path(__file__).parent / "cmd_handlers"
    for ch_py_file in cmd_handlers_path.glob("*.py"):
        import_name = f"theburgbot.cmd_handlers.{ch_py_file.stem}"
        mod = importlib.import_module(import_name)
        mod_symbols = dir(mod)
        if "TheBurgBotUserCommand" in mod_symbols:
            tbbuc: CommandHandler = getattr(mod, "TheBurgBotUserCommand")
            if all(
                [
                    x in expect_protocol_methods
                    for x in dir(tbbuc)
                    if not x.startswith("_")
                ]
            ):
                cmd_instance = tbbuc()
                cmd_name = cmd_instance.register_command(
                    client,
                    audit_log_start_end_async,
                    _command_use_log,
                    _command_create_internal_logger,
                    _command_audit_logger,
                    filtered_words,
                )
                print(f"Registered user command /{cmd_name}")

    # return for register_slash_commands
    return client
