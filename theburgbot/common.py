import datetime
import hashlib
import json
from functools import reduce
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional, Protocol, Union

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


async def http_get_path_cached_checksummed(asset_url: str, checksum_url: str) -> Path:
    async with httpx.AsyncClient() as client:

        async def _get_current_checksum():
            cs_res = await client.get(checksum_url)
            if cs_res.status_code != 200:
                raise Exception(
                    f"http_get_checksummed checksum {checksum_url}: {cs_res.status_code}"
                )
            return cs_res.text

        comb_shasum = hashlib.sha224(
            asset_url.encode("utf-8") + checksum_url.encode("utf-8")
        ).hexdigest()
        parent = Path(__file__).resolve().parent
        combsum_file = parent / f".checksum.{comb_shasum}"
        asset_file = parent / f".{comb_shasum}"

        async def _asset_needs_refresh() -> Optional[str]:
            """
            returning 'None' means: refresh not needed
            otherwise it's the fetched checksum of the new asset
            """
            fetched_checksum = await _get_current_checksum()
            if asset_file.exists() and combsum_file.exists():
                with open(combsum_file, "r") as cs_f:
                    current_checksum = cs_f.read()
                    print(f"{fetched_checksum} vs {current_checksum}: {fetched_checksum == current_checksum}")
                    if fetched_checksum == current_checksum:
                        return None
            return fetched_checksum

        nr_checksum = await _asset_needs_refresh()
        if nr_checksum:
            print(f"FETCH ASSET! {nr_checksum}")
            with open(combsum_file, "w+") as cs_w:
                cs_w.write(nr_checksum)

            with open(asset_file, "wb+") as as_w:
                print("FETCH ASSET")
                async with client.stream("GET", asset_url) as stream:
                    async for chunk in stream.aiter_bytes():
                        as_w.write(chunk)

        return asset_file


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
                raise Exception(f"http_get_cached {url} ({url_224}): {res.status_code}")
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
