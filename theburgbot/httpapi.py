import logging
import threading

import aiosqlite
import chevron
from aiohttp import web

from theburgbot import constants
from theburgbot.common import dprint as print
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async
from twentywordmtg.populate import mtgjson_sqlite_path

LOGGER = logging.getLogger("discord")


async def twentywordmagic_cards(req: web.Request):
    print(req.match_info["card_name"])
    db_path = await mtgjson_sqlite_path()
    print(db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        records = await db.execute_fetchall(
            "select * from cards left join twentyword_cards as tw "
            + "where cards.uuid = tw.card_uuid and cards.name like ?",
            (req.match_info["card_name"],),
        )
        await db.commit()
        print(records[0])
        print(records[0].keys())
        print(records[0]["text"])

        html_out = ""
        frag_str = None
        with open("templates/twmtg_card_frag.html", "r") as frag:
            frag_str = frag.read()
        for row in records:
            row_copy = {**row}
            row_copy["text"] = row_copy["text"].replace("\\n", "<br/>")
            if row_copy["legal"]:
                row_copy["TMPL_legal"] = [True]
            print(row_copy)
            html_out += chevron.render(frag_str, row_copy)

        print(html_out)
        return web.Response(text=html_out, content_type="text/html")


class TheBurgBotHTTP:
    thread: threading.Thread
    run: bool = True
    port: int
    app: web.Application

    def __init__(
        self,
        redeem_req,
        parent: "TheBurgBotClient",
        redeem_success_cb,
        port: int = constants.DEFAULT_PORT,
    ):
        self.redeem_req = redeem_req
        self.parent = parent
        self.redeem_success_cb = redeem_success_cb
        self.port = port
        self.app = web.Application()
        self.app.add_routes(
            [
                web.post("/redeem-invite", self.redeem_invite_route_handler),
                web.get(
                    f"/{constants.USER_STATIC_HTTP_PATH}/" "{doc_id}",
                    self.get_static_route_handler,
                ),
                web.get("/twentywordmagic/card/{card_name}", twentywordmagic_cards),
            ]
        )
        print(self.app)
        self.thread = threading.Thread(target=self.thread_runner, daemon=True)
        self.thread.start()

    async def shutdown(self):
        await self.app.shutdown()
        await self.app.cleanup()

    async def get_static_route_handler(self, req: web.Request):
        @audit_log_start_end_async(
            "HTTPAPI_GET_STATIC_ROUTE_HANDLER", db_path=self.parent.db_path
        )
        async def _get_static_route_handler__inner():
            rendered_html = await TheBurgBotDB(
                self.parent.db_path
            ).get_http_static_rendered(req.match_info["doc_id"])
            if rendered_html is None:
                return web.HTTPPermanentRedirect(location=constants.SITE_URL)
            return web.Response(text=rendered_html, content_type="text/html")

        return await _get_static_route_handler__inner()

    async def redeem_invite_route_handler(self, req):
        @audit_log_start_end_async(
            "HTTPAPI_REDEEM_INVITE_ROUTE_HANDLER", db_path=self.parent.db_path
        )
        async def _redeem_invite_route_handler__inner():
            ret = {}
            try:
                req_json = await req.json()
                invite = self.redeem_req(req_json["passphrase"])
                if invite is not None:
                    ret["invite_code"] = invite
                    with open(constants.REDEEM_SUCCESS_FRAG_TMPL, "r") as f:
                        ret["html_frag"] = chevron.render(f, {**ret})
                    await self.redeem_success_cb(
                        invite_code=invite, passphrase=req_json["passphrase"]
                    )
                else:
                    LOGGER.warn(f'Failed redempetion attempt: {req_json["passphrase"]}')
                    return web.HTTPPermanentRedirect(location=constants.SITE_URL + "#")
            except Exception as e:
                LOGGER.warn("Exception in route handling:", exc_info=True)
            return web.json_response(ret)

        return await _redeem_invite_route_handler__inner()

    def thread_runner(self):
        LOGGER.info(f"HTTP API listening on port {self.port}")
        web.run_app(
            self.app,
            port=self.port,
            handle_signals=False,
            print=None,
            access_log=LOGGER,
        )
