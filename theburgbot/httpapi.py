import logging
import threading

import chevron
from aiohttp import web

from theburgbot import constants
from theburgbot.db import TheBurgBotDB, audit_log_start_end_async

LOGGER = logging.getLogger("discord")


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
            ]
        )
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
