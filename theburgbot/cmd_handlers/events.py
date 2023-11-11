from typing import Optional

import discord
from discord import app_commands

from theburgbot.common import CommandHandler, strip_html
from theburgbot.db import TheBurgBotKeyedJSONStore
from theburgbot.ical import mtg_current_events

CHUNK_SIZE = 3


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
            name="events",
            description="Info about Events.",
        )
        @app_commands.describe(
            venue="Venue name, optional. Without, lists all venues.",
            public_reply="Show the response in public.",
        )
        @audit_log_decorator("COMMAND_EVENTS", db_path=client.db_path)
        async def events(
            interaction: discord.Interaction,
            public_reply: bool = False,
            venue: Optional[str] = None,
        ):
            await command_use_logger(interaction)
            urls = await TheBurgBotKeyedJSONStore(
                db_path=client.db_path, namespace="events"
            ).get("ical/urls", default_producer=dict)
            cur_events = await mtg_current_events(urls=urls)
            if not venue:
                await interaction.response.send_message(
                    "## Venues\n\n" + "\n".join([f"* {x}" for x in cur_events.keys()]),
                    ephemeral=True,
                )
            else:
                if not venue in cur_events:
                    return await interaction.response.send_message(
                        f'Sorry, no venue named "{venue}" known!', ephemeral=True
                    )

                await interaction.response.defer(
                    thinking=True, ephemeral=not public_reply
                )
                embeds = []
                for ev_type, events in cur_events[venue].items():
                    events_view = [*events]
                    page_no = 1
                    paginate = len(events_view) > CHUNK_SIZE
                    while len(events_view):
                        emb = discord.Embed(
                            title=f"{venue} {ev_type} events"
                            + (f" (page {page_no})" if paginate else "")
                        )
                        for event in events_view[:CHUNK_SIZE]:
                            st_end = ""
                            if ev_type != "recurring":
                                st_end = (
                                    "Starts: "
                                    + str(event["DTSTART"].dt)
                                    + "\nEnds: "
                                    + str(event["DTEND"].dt)
                                    + "\n\n"
                                )
                            emb.add_field(
                                name="📅 " + str(event["SUMMARY"]),
                                value=st_end + strip_html(str(event["DESCRIPTION"])),
                                inline=False,
                            )
                        embeds.append(emb)
                        events_view = events_view[CHUNK_SIZE:]
                        page_no += 1

                await interaction.followup.send(
                    embeds=embeds,
                    ephemeral=not public_reply,
                )

        return "events"
