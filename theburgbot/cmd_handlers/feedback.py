import discord
from discord import app_commands

from theburgbot.common import CommandHandler
from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB


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
            name="feedback",
            description="Submit feedback about the server, bug reports about the bot, feature requests, etc. etc.",
        )
        @app_commands.describe(feedback="Your feedback, freeform.")
        @audit_log_decorator("COMMAND_FEEDBACK", db_path=client.db_path)
        async def feedback(
            interaction: discord.Interaction,
            feedback: str,
        ):
            await command_use_logger(interaction)
            await TheBurgBotDB(client.db_path).add_feedback(
                interaction.user.id, feedback
            )
            await interaction.response.send_message(
                "Thank you very much for the feedback! If a resolution is required, we'll get back to you with information about it once complete.",
                ephemeral=True,
            )
            await client.get_channel(discord_ids.ADMINS_CHANNEL_ID).send(
                f"Feedback submitted by <@{interaction.user.id}>:\n> {feedback}\n"
            )

        return "feedback"
