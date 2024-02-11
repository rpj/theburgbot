import datetime
import hashlib
import json
from functools import reduce
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol, Union

import httpx
import rich


class CommandHandler(Protocol):
    def register_command(
        self,
        client: "TheBurgBotClient",
        audit_log_decorator,
        command_use_logger,
        command_create_internal_logger,
        command_audit_logger,
        filtered_words,
    ) -> Any:
        pass


class SimpleHTMLStripper(HTMLParser):
    REPLACEMENTS = {
        "b": lambda d: f"**{d}**",
        "i": lambda d: f"*{d}*",
        "u": lambda d: f"__{d}__",
    }

    TAG_REPLACEMENTS = {"br": "\n"}

    def __init__(self):
        super().__init__()
        self.output = ""
        self.next_data_handlers = []

    def __str__(self):
        return self.output

    def handle_starttag(self, tag, attrs):
        if tag in self.TAG_REPLACEMENTS:
            self.output += self.TAG_REPLACEMENTS[tag]
            return

        if tag in self.REPLACEMENTS:
            self.next_data_handlers.append(self.REPLACEMENTS[tag])

    def handle_endtag(self, tag):
        self.next_data_handlers = []

    def handle_data(self, data):
        if not len(self.next_data_handlers):
            self.output += data
            return
        self.output += reduce(
            lambda o_str, d_handler: d_handler(o_str), self.next_data_handlers, data
        )


def strip_html(htmlish: str) -> str:
    stripper = SimpleHTMLStripper()
    stripper.feed(htmlish)
    return str(stripper)


def dprint(print_str, *args, **kwargs):
    return rich.print(
        f"[{datetime.datetime.now().isoformat()}] {print_str}", *args, **kwargs
    )


async def http_get_cached(
    url: str, *, ttl_hours: int = 24, reader=None, writer=None, ext: str = ""
):
    if not writer:
        writer = lambda f_handle, res: f_handle.write(res.text)
    if not reader:
        reader = lambda f_handle: f_handle.read()

    url_224 = hashlib.sha224(url.encode("utf-8")).hexdigest()
    cache_path = Path(__file__).resolve().parent / f".cache.{url_224}{ext}"

    async def _refresh():
        dprint(f"Refreshing {url} ({url_224})")
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            if res.status_code != 200:
                raise Exception(f"http_get_cached {url} ({url_224})")
            with open(cache_path, "w+") as f:
                writer(f, res)

    if Path.exists(cache_path):
        mod_dt = datetime.datetime.fromtimestamp(cache_path.stat().st_mtime)
        now_ts = datetime.datetime.now().timestamp()

        if mod_dt.timestamp() + (ttl_hours * 60 * 60) < now_ts:
            await _refresh()
        else:
            dprint(f"USING CACHED {cache_path}")
    else:
        await _refresh()

    with open(cache_path, "r") as r:
        return reader(r)


async def http_get_cached_json(url):
    return await http_get_cached(
        url,
        ext=".json",
        reader=lambda f_handle: json.load(f_handle),
        writer=lambda f_handle, res: json.dump(res.json(), f_handle),
    )


def dt_to_date(dt_or_date: Union[datetime.date, datetime.datetime]) -> datetime.date:
    if isinstance(dt_or_date, datetime.datetime):
        return datetime.date.fromtimestamp(dt_or_date.timestamp())
    return dt_or_date
