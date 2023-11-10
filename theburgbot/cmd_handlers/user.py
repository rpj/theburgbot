import discord

from theburgbot import constants
from theburgbot.db import TheBurgBotDB

TITLE_TRUNC_LEN = 256


async def user_cmd_handler(
    command_create_internal_logger,
    command_audit_logger,
    db_path: str,
    interaction: discord.Interaction,
    list_pages: bool = False,
):
    msg = "## User data\n"
    if list_pages:
        page_list = await TheBurgBotDB(db_path).get_users_http_statics(
            interaction.user.id
        )
        msg += "\n".join(
            [
                "* ["
                + (f'"_{row[4][:TITLE_TRUNC_LEN]}_", v' if row[4] is not None else "V")
                + f"ia `/{row[3]}`]({constants.SITE_URL.lower()}/{constants.USER_STATIC_HTTP_PATH}/{row[2]}) "
                f"(c: {row[0]}, u: {row[1]})"
                for row in page_list
            ]
        )
    await interaction.response.send_message(
        msg,
        ephemeral=True,
    )
