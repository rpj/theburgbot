import asyncio
import json

from theburgbot import constants
from theburgbot.config import discord_ids
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async


def invite_thread_run(client: "TheBurgBotClient"):
    invite_channel = client.get_channel(discord_ids.INVITE_CHANNEL_ID)

    async def invite_req_runner_async():
        tldb = TheBurgBotDB(client.db_path)
        while True:
            req = client.invite_req_queue.get()

            @audit_log_start_end_async(
                "INVITE_REQ_RUNNER__CODE_PRODUCER", db_path=client.db_path
            )
            async def code_producer(result_cb):
                invite_fut = asyncio.run_coroutine_threadsafe(
                    invite_channel.create_invite(
                        reason=f"REDEEMED {req.passphrase}", max_uses=1
                    ),
                    loop=client.loop,
                )

                invite_fut.add_done_callback(lambda future: result_cb(future.result()))

            can_redeem = await tldb.can_redeem_invite(json.dumps(req.passphrase))
            if not can_redeem:
                req.return_queue.put_nowait(None)
            else:

                def redeemer(invite):
                    redeemed_fut = asyncio.run_coroutine_threadsafe(
                        tldb.try_redeem_invite(json.dumps(req.passphrase), invite.url),
                        loop=client.loop,
                    )

                    redeemed_fut.add_done_callback(
                        lambda r_fut: req.return_queue.put_nowait(r_fut.result())
                    )

                await code_producer(redeemer)

    asyncio.run(invite_req_runner_async())
