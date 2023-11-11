import asyncio
import datetime
import logging

import discord
import mistune
import openai
from discord import app_commands

from theburgbot import constants
from theburgbot.common import CommandHandler
from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB

LOGGER = logging.getLogger("discord")


async def query_openai(
    query: str,
    *,
    audit_logger,
    model,
    retries: int = 5,
):
    comp = None
    await audit_logger("CHAT_COMPLETETION_CREATE", {"model": model, "prompt": query})
    while not comp and retries > 0:
        try:
            comp = await openai.ChatCompletion.acreate(
                model=model, messages=[{"role": "user", "content": query}], timeout=180
            )
        except openai.error.ServiceUnavailableError:
            retries -= 1
            LOGGER.warn(f"GPT unavailable, retrying ({retries} left)", exc_info=True)
            await audit_logger("SERVICE_UNAVAILABLE", {"retries": retries})
            asyncio.sleep(5 - retries)
    if comp:
        if audit_logger:
            await audit_logger("ALL_RESPONSES", {"responses": comp})
        return comp.choices[0].message.content
    else:
        return "OpenAI service is unavailable"


async def gpt_cmd_handler(
    command_create_internal_logger,
    command_audit_logger,
    db_path: str,
    interaction: discord.Interaction,
    query: str,
    public_reply: bool = False,
    shorten_response: bool = True,
    model: str = None,
):
    if not model:
        model = "gpt-3.5-turbo"
    real_prompt = query
    if shorten_response:
        real_prompt = f"{query}{constants.GPT_SHORTEN_PROMPT_POSTFIX}"
    audit_obj = {
        "query": query,
        "user_id": interaction.user.id,
        "public": public_reply,
        "model": model,
        "real_prompt": real_prompt,
    }
    await interaction.response.defer(thinking=bool, ephemeral=not public_reply)
    response = await query_openai(
        real_prompt,
        model=model,
        audit_logger=await command_create_internal_logger("COMMAND_GPT", audit_obj),
    )
    audit_obj["response"] = response
    query_quoted = "\n".join([f"> {l}" for l in query.split("\n")])

    url_id = await TheBurgBotDB(db_path).add_http_static(
        interaction.user.id,
        "gpt",
        "gpt_response",
        {
            "prompt": real_prompt,
            "response": mistune.html(response),
            "model": {
                "displayName": "OpenAI completions API",
                "sourceURL": "https://platform.openai.com/docs/api-reference/completions",
                "name": model,
            },
            "captureTimestamp": datetime.datetime.now().isoformat(),
        },
        query,
    )

    msg_postfix = f"_This response is available forever at:_ {constants.SITE_URL.lower()}/{constants.USER_STATIC_HTTP_PATH}/{url_id}\n\n"
    f"\n### Parameters:\n* Model: **{model}**\n* Response shortened? **{'Yes' if shorten_response else 'No'}**"

    try:
        await interaction.followup.send(
            f"# Prompt:\n{query_quoted}\n# Response:\n{response}\n\n{msg_postfix}",
            ephemeral=not public_reply,
        )
    except discord.errors.HTTPException:
        await interaction.followup.send(
            f"# Prompt:\n{query_quoted}\n# Response:\n_... is too large to be shown here!_\nSee below for a URL to view it.\n\n\n{msg_postfix}",
            ephemeral=not public_reply,
        )
    finally:
        await command_audit_logger(
            {**audit_obj, "url_id": url_id},
            event="COMMAND_GPT",
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
            name="gpt",
            description="Talk to ChatGPT. Please use sparingly: it isn't free!",
        )
        @app_commands.describe(
            prompt="What to ask of ChatGPT",
            public_reply="Send the reply to the channel (defaults to False)",
            shorten_response="Append instruction to the prompt to keep the response short",
            model="The model to use (only available to Admins)",
        )
        @audit_log_decorator("COMMAND_GPT", db_path=client.db_path)
        async def gpt(
            interaction: discord.Interaction,
            prompt: str,
            public_reply: bool = False,
            shorten_response: bool = True,
            model: str = None,
        ):
            await command_use_logger(interaction)
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

        return "gpt"
