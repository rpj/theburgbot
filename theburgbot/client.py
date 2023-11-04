import asyncio
import datetime
import logging
import queue
import sys
import threading
from dataclasses import dataclass

import discord
from discord.ext import commands

from theburgbot.cmd_handlers.igdb import igdb_refresh_token
from theburgbot.config import discord_ids, reaction_roles
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async
from theburgbot.httpapi import TheBurgBotHTTP
from theburgbot.invite_thread import invite_thread_run

LOGGER = logging.getLogger("discord")


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
        self.initialized = True
        LOGGER.info("✅ TheBurgBot is ready")

    async def on_message(self, message: discord.Message):
        @audit_log_start_end_async("CLIENT_ON_MESSAGE", db_path=self.db_path)
        async def _on_message__inner():
            if message.author.id == self.user.id:
                # don't log our own messages
                return
            await TheBurgBotDB(self.db_path).log_message(
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
        await TheBurgBotDB(self.db_path).register_user_flux(
            userOrMember.id, userOrMember.name, userOrMember.global_name, event
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
