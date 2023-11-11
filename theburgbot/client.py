import asyncio
import datetime
import logging
import queue
import re
import sys
import threading
from dataclasses import dataclass

import discord
from discord.ext import commands

from theburgbot import constants
from theburgbot.cmd_handlers.igdb import igdb_refresh_token
from theburgbot.cmd_handlers.scry import scry_lookup
from theburgbot.common import strip_html
from theburgbot.config import discord_ids, reaction_roles
from theburgbot.db import (TheBurgBotDB, audit_log_start_end_async,
                           command_create_internal_logger)
from theburgbot.httpapi import TheBurgBotHTTP
from theburgbot.ical import iCalSyncer
from theburgbot.invite_thread import invite_thread_run

LOGGER = logging.getLogger("discord")

from theburgbot.common import dprint as print


class TheBurgBotClient(commands.Bot):
    db_path: str = None
    sync_commands: bool = False

    @dataclass
    class InviteReq:
        passphrase: str
        return_queue: queue.Queue() = queue.Queue()

    def __init__(self, db_path: str, sync_commands: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_path = db_path
        self.sync_commands = sync_commands
        self.invite_req_thread = threading.Thread(
            target=invite_thread_run, args=(self,), daemon=True
        )
        self.invite_req_queue = queue.Queue()
        self.initialized = False
        self.ical_syncer = iCalSyncer(
            filter_strings=["Prerelease"], db_path=self.db_path
        )

    async def on_ready(self):
        if self.initialized:
            LOGGER.info("TheBurgBot is ready again")
            return

        await TheBurgBotDB(self.db_path).initialize()

        if self.sync_commands and self.tree is not None:
            LOGGER.info("Syncing commands...")
            synced_cmds = await self.tree.sync()
            if len(synced_cmds):
                LOGGER.info(
                    f"Synced: {', '.join([f'{self.command_prefix}{synced}' for synced in synced_cmds])}"
                )
            LOGGER.critical(
                f"Exiting after command sync: remove the option and re-run!"
            )
            sys.exit(0)

        def redeem_req_handler(passphrase: str):
            req = self.InviteReq(passphrase=passphrase)
            self.invite_req_queue.put_nowait(req)
            return req.return_queue.get()

        async def redeem_success_cb(**kwargs):
            await TheBurgBotDB(self.db_path).audit_log_event_json(
                {**kwargs}, event="INVITE_REDEEMED"
            )

        self.loop = asyncio.get_running_loop()
        self.invite_req_thread.start()
        self.http_server = TheBurgBotHTTP(
            redeem_req=redeem_req_handler,
            parent=self,
            redeem_success_cb=redeem_success_cb,
        )
        await igdb_refresh_token(
            audit_logger=lambda ev_extra, extra_dict: TheBurgBotDB(
                self.db_path
            ).audit_log_event_json(
                {
                    "timestamp": str(datetime.datetime.now()),
                    **extra_dict,
                },
                event=f"IGDB_TOKEN_REFRESH__{ev_extra}",
            ),
        )

        async def ical_bot_synced_callback(current_events):
            tz = datetime.timezone(offset=datetime.timedelta(hours=-8))
            guild: discord.Guild = self.get_guild(discord_ids.GUILD_ID)
            db = TheBurgBotDB(self.db_path)
            for event in current_events:
                print(event)
                ev_for_json = {**event}
                del ev_for_json["start_time"]  # XXX fix
                for k in ["end_time"]:  # ["start_time", "end_time"]:
                    ev_for_json[k] = ev_for_json[k].timestamp()
                print(f"Checking event: {ev_for_json}")

                # only adjust `event` AFTER getting the JSON obj; that's what we ALWAYS hash
                event["description"] = strip_html(event["description"])
                if event["start_time"] <= datetime.datetime.now(tz=tz):
                    event["start_time"] = datetime.datetime.now(
                        tz=tz
                    ) + datetime.timedelta(hours=12)

                extant_event_snowflake = await db.get_event_snowflake_if_exists(
                    ev_for_json
                )
                if extant_event_snowflake:
                    print("UPDATE?")
                    print(
                        await db.event_has_changed(extant_event_snowflake, ev_for_json)
                    )
                else:
                    new_event_snowflake = await guild.create_scheduled_event(
                        **{
                            **event,
                            "entity_type": discord.EntityType.external,
                            "privacy_level": discord.PrivacyLevel.guild_only,
                        }
                    )
                    print(f"new_event_snowflake={new_event_snowflake.id}")
                    digest = await db.add_event(
                        str(new_event_snowflake.id), ev_for_json
                    )
                    print(f"digest={digest}")

        await self.ical_syncer.start_sync(ical_bot_synced_callback)

        self.initialized = True
        LOGGER.info("✅ TheBurgBot is ready")

    async def on_message(self, message: discord.Message):
        @audit_log_start_end_async("CLIENT_ON_MESSAGE", db_path=self.db_path)
        async def _on_message__inner():
            if message.author.id == self.user.id:
                # don't log our own messages
                return
            db = TheBurgBotDB(self.db_path)
            embeds = []
            for card_name in re.findall(constants.INLINE_SCRY_PATTERN, message.content):
                (scry_embeds, _was_more) = await scry_lookup(
                    message.author,
                    card_name,
                    exact_match=True,
                    audit_logger=await command_create_internal_logger(
                        self.db_path,
                        "INLINE_SCRY_LOOKUP",
                        {"query": card_name, "author": message.author.id},
                    ),
                )
                if scry_embeds:
                    if len(scry_embeds) > 1:
                        LOGGER.warning(f"More than one scry result for inline lookup!")
                    embeds.extend(scry_embeds)
            if len(embeds) > 0:
                await message.channel.send(embeds=embeds)

            await db.log_message(
                channel_id=message.channel.id,
                channel_name=message.channel.name,
                author_id=message.author.id,
                author_name=message.author.display_name,
                message_id=message.id,
                content=message.content,
            )

        return await _on_message__inner()

    async def _on_raw_reaction__add_or_rm(
        self, payload: discord.RawReactionActionEvent
    ):
        @audit_log_start_end_async(
            f"CLIENT_ON_RAW__{payload.event_type}", db_path=self.db_path
        )
        async def _on_raw__inner():
            try:
                if payload.message_id == discord_ids.ROLE_REACTION_MESSAGE_ID:
                    if payload.emoji and payload.emoji.name in reaction_roles:
                        member = self.get_guild(discord_ids.GUILD_ID).get_member(
                            payload.user_id
                        )
                        snowflake = discord.Object(
                            id=reaction_roles[payload.emoji.name]
                        )
                        actions = {
                            "REACTION_ADD": lambda: member.add_roles(snowflake),
                            "REACTION_REMOVE": lambda: member.remove_roles(snowflake),
                        }
                        if payload.event_type in actions:
                            await actions[payload.event_type]()
            except:
                LOGGER.error("_on_raw_reaction__add_or_rm", exc_info=True)
            finally:
                await TheBurgBotDB(self.db_path).audit_log_event_json(
                    {
                        "role_id": reaction_roles[payload.emoji.name]
                        if payload.emoji and payload.emoji.name in reaction_roles
                        else None,
                        "channel_id": payload.channel_id,
                        "user_id": payload.user_id,
                    },
                    event=payload.event_type,
                )

        return await _on_raw__inner()

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        return await self._on_raw_reaction__add_or_rm(payload)

    async def on_raw_reaction_remove(self, payload):
        return await self._on_raw_reaction__add_or_rm(payload)

    async def _on_member_audit(self, event, userOrMember):
        gname = ""
        if isinstance(userOrMember, discord.Member):
            gname = userOrMember.global_name
        elif isinstance(userOrMember, discord.User):
            gname = userOrMember.display_name
        else:
            LOGGER.warning("What the hell is this instance?")
            print(userOrMember)
        await TheBurgBotDB(self.db_path).register_user_flux(
            userOrMember.id, userOrMember.name, gname, event
        )
        return await TheBurgBotDB(self.db_path).audit_log_event_json(
            {
                "user_id": userOrMember.id,
                "display_name": userOrMember.name,
                "global_name": userOrMember.global_name,
            },
            event=f"CLIENT_ON_MEMBER_{event}",
        )

    async def on_member_join(self, payload):
        @audit_log_start_end_async(f"CLIENT_ON_MEMBER_JOIN", db_path=self.db_path)
        async def _on_member_join__inner():
            await self.get_channel(discord_ids.ADMINS_CHANNEL_ID).send(
                f"<@{payload.id}> joined!"
            )
            return await self._on_member_audit("JOIN", payload)

        return await _on_member_join__inner()

    async def on_raw_member_remove(self, payload):
        @audit_log_start_end_async(f"CLIENT_ON_MEMBER_REMOVE", db_path=self.db_path)
        async def _on_raw_member_remove_join__inner():
            await self.get_channel(discord_ids.ADMINS_CHANNEL_ID).send(
                f"<@{payload.user.id}> left!"
            )
            return await self._on_member_audit("REMOVE", payload.user)

        return await _on_raw_member_remove_join__inner()
