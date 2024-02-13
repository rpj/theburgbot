import logging
import threading

import aiohttp_cors
import aiosqlite
import chevron
from aiohttp import web

from theburgbot import constants
from theburgbot.common import dprint as print
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async
from twentywordmtg.populate import mtgjson_sqlite_path

LOGGER = logging.getLogger("discord")


async def twentywordmagic_cards(req: web.Request):
    if "card_name" not in req.query:
        return
    db_path = await mtgjson_sqlite_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        records = await db.execute_fetchall(
            "select * from cards left join twentyword_cards as tw "
            + "left join cardPurchaseUrls as urls "
            + "where cards.uuid = tw.card_uuid and cards.uuid = urls.uuid and cards.name like ?",
            (req.query["card_name"],),
        )
        await db.commit()

        html_out = ""
        frag_str = None
        with open("templates/twmtg_card_frag.html", "r") as frag:
            frag_str = frag.read()
        for row in records[:1]:
            row_copy = {**row}
            row_copy["text"] = row_copy["text"].replace("\\n", "<br/>")
            if row_copy["legal"]:
                row_copy["TMPL_legal"] = [True]
            # print(row_copy)
            html_out += chevron.render(frag_str, row_copy)
            html_out += "<hr>"

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
        cors_allowed_routes = [web.get("/twentywordmagic/card", twentywordmagic_cards)]
        self.app_cors = aiohttp_cors.setup(
            self.app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True, expose_headers="*", allow_headers="*"
                )
            },
        )

        self.app.add_routes(
            [
                web.post("/redeem-invite", self.redeem_invite_route_handler),
                web.get(
                    f"/{constants.USER_STATIC_HTTP_PATH}/" "{doc_id}",
                    self.get_static_route_handler,
                ),
                *cors_allowed_routes,
            ]
        )

        cors_allowed_paths = [route.path for route in cors_allowed_routes]
        for route in list(self.app.router.routes()):
            route_info = route.resource.get_info()
            if "path" in route_info and route_info["path"] in cors_allowed_paths:
                print(f"Opening up CORS on {route_info['path']}")
                self.app_cors.add(route)

        self.thread = threading.Thread(target=self.thread_runner, daemon=True)
        self.thread.start()

    async def shutdown(self):
        await self.app.shutdown()
        await self.app.cleanup()

    async def twmtg_cards(self, req):
        @audit_log_start_end_async("TWMTG_CARDS_GET", db_path=self.parent.db_path)
        async def _inner():
            return await twentywordmagic_cards(req)

        return await _inner()

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
