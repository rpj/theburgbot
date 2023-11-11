import discord
from discord import app_commands

from theburgbot import constants
from theburgbot.common import CommandHandler
from theburgbot.db import TheBurgBotDB

TITLE_TRUNC_LEN = 1024
PAGE_CHUNK_SIZE = 5


async def user_cmd_handler(
    command_create_internal_logger,
    command_audit_logger,
    db_path: str,
    interaction: discord.Interaction,
    list_pages: bool = False,
):
    embeds = []
    if list_pages:
        page_list = await TheBurgBotDB(db_path).get_users_http_statics(
            interaction.user.id
        )
        pages_view = [*page_list]
        page_count = 1
        while len(pages_view):
            emb = discord.Embed(title=f"User Pages (pg. {page_count})")
            for row in pages_view[:PAGE_CHUNK_SIZE]:
                emb.add_field(
                    name=f"🌐 {constants.SITE_URL.lower()}/{constants.USER_STATIC_HTTP_PATH}/{row[2]}",
                    value=f'Via `/{row[3]}`: "{row[4][:TITLE_TRUNC_LEN]}"\n_{row[0]}_',
                    inline=False,
                )
            embeds.append(emb)
            pages_view = pages_view[PAGE_CHUNK_SIZE:]
            page_count += 1
    await interaction.response.send_message(
        "## User data",
        embeds=embeds,
        ephemeral=True,
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
            name="user",
            description="Commands related to actions you've performed with the bot",
        )
        @app_commands.describe(
            list_pages="Lists all the pages the bot has created on your behalf"
        )
        @audit_log_decorator("COMMAND_USER", db_path=client.db_path)
        async def user(
            interaction: discord.Interaction,
            list_pages: bool = False,
        ):
            await command_use_logger(interaction)
            return await user_cmd_handler(
                command_create_internal_logger,
                command_audit_logger,
                client.db_path,
                interaction,
                list_pages,
            )

        return "user"
