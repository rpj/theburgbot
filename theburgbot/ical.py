import asyncio
import datetime
import logging
import signal
import sys
from typing import Dict, List, Optional

import icalendar

from theburgbot.common import dprint as print
from theburgbot.common import dt_to_date, http_get_cached, http_get_cached_json
from theburgbot.db import TheBurgBotKeyedJSONStore

LOGGER = logging.getLogger("discord")

POLL_FREQ_MINS = 10
MTG_SETS_URL = "https://api.scryfall.com/sets"

# _could_ use GPT to analyze each event and try to determine if its MTG-related!
# would want to ensure it has web access though, because it would need up-to-date info
MTG_FILTER_STRINGS = [
    "MtG",
    "MTG",
    "Magic:",
    "Magic the Gathering",
    "Board Game",
]

INCLUDE_PROPS_DEFAULT = [*icalendar.Event.singletons, *icalendar.Event.multiple]


async def get_current_events_from_ICS_urls(
    urls: Dict[str, str],
    post_hours_before: int,
    summary_filter_strings: Optional[List[str]] = None,
    include_properties: Optional[List[str]] = None,
) -> List[icalendar.Event]:
    if not summary_filter_strings:
        summary_filter_strings = list()
    if not include_properties:
        include_properties = INCLUDE_PROPS_DEFAULT

    fetched = {}
    now_date = datetime.date.today()

    for name, url in urls.items():
        try:
            fetched[name] = await http_get_cached(url)
        except:
            LOGGER.error(f"iCal sync failed at {url} ({name})", exc_info=True)
            continue

    phb_timedelta = datetime.timedelta(hours=post_hours_before)
    all_events = {}
    for name, ics in fetched.items():
        cal = icalendar.Calendar.from_ical(ics)
        cal_events = []
        for event in cal.walk():
            ev_summary = event.get("SUMMARY")
            if ev_summary is None:
                continue
            if any([f_str in ev_summary for f_str in summary_filter_strings]):
                cal_events.append(event)

        current_events = {
            "onetime": [],
            "recurring": [],
        }
        for event in cal_events:
            start_dt = dt_to_date(event.get("DTSTART").dt - phb_timedelta)
            end_dt = dt_to_date(event.get("DTEND").dt)

            # one time events
            if now_date > start_dt and now_date < end_dt:
                current_events["onetime"].append(event)
            else:
                # recurring events
                rrule = event.get("RRULE")
                if rrule and isinstance(rrule, icalendar.prop.vRecur):
                    # if UNTIL is in the future, the event is valid
                    # otherwise with no UNTIL, the event is still valid
                    until_rrules = rrule.get("UNTIL")
                    if until_rrules and len(until_rrules):
                        until_dt = until_rrules[0]
                        if now_date < dt_to_date(until_dt):
                            current_events["recurring"].append(event)
                    else:
                        current_events["recurring"].append(event)

        return_list = {
            "onetime": [],
            "recurring": [],
        }
        for ev_type, cur_events in current_events.items():
            for cur_event in cur_events:
                ev_dict = {}
                for prop_name in include_properties:
                    prop_val = cur_event.get(prop_name)
                    if prop_val:
                        ev_dict[prop_name] = prop_val
                return_list[ev_type].append(ev_dict)
        all_events[name] = return_list
    return all_events


async def mtg_current_events(
    urls: Dict[str, str],
    post_hours_before: int = 48,
    filter_strings: Optional[List[str]] = None,
):
    if not filter_strings:
        filter_strings = list(MTG_FILTER_STRINGS)
    sets = await http_get_cached_json(MTG_SETS_URL)
    filter_strings.extend([i["name"] for i in sets["data"]])

    return await get_current_events_from_ICS_urls(
        urls=urls,
        summary_filter_strings=filter_strings,
        post_hours_before=post_hours_before,
    )


class iCalSyncer:
    def __init__(
        self,
        db_path: str,
        filter_strings: Optional[List[str]] = None,
        post_hours_before: int = 48,
    ):
        self.kv_store = TheBurgBotKeyedJSONStore(db_path=db_path, namespace="events")
        self.filter_strings = filter_strings
        self.post_hours_before = post_hours_before
        self._task: Optional[asyncio.Task] = None

    async def start_sync(
        self,
        synced_callback,
        *,
        exit_immediately: bool = False,
        refresh_every_hours: int = 24,
    ):
        await self.kv_store.initialize()

        while True:
            tzinfo = datetime.timezone(offset=datetime.timedelta(hours=-8))
            urls = await self.kv_store.get("ical/urls", default_producer=dict)
            print(f"iCal sync has {len(urls)} URLs: {', '.join(urls.keys())}")
            mtg_events = await mtg_current_events(
                urls=urls,
                post_hours_before=self.post_hours_before,
                filter_strings=self.filter_strings,
            )
            sync_events = []
            print(f"iCal sync checking {len(mtg_events)} events...")
            for cal_name, events_dict in mtg_events.items():
                for event in events_dict["onetime"]:
                    std = event["DTSTART"].dt
                    etd = event["DTEND"].dt
                    if dt_to_date(datetime.datetime.today()) > std:
                        std = None

                    sync_events.append(
                        {
                            "name": f'[{cal_name}] {str(event["SUMMARY"])}',
                            "description": str(event["DESCRIPTION"])
                            if "DESCRIPTION" in event
                            else "(No description given)",
                            "start_time": datetime.datetime(
                                day=std.day,
                                month=std.month,
                                year=std.year,
                                tzinfo=tzinfo,
                            )
                            if std
                            else datetime.datetime.now(tzinfo)
                            + datetime.timedelta(minutes=1),
                            "end_time": datetime.datetime(
                                day=etd.day,
                                month=etd.month,
                                year=etd.year,
                                tzinfo=tzinfo,
                            ),
                            "location": str(event["LOCATION"]),
                        }
                    )
                print(f"... {len(sync_events)} events to act on.")
                await synced_callback(sync_events)
            if exit_immediately:
                break

            async def sleeper():
                try:
                    end_ts = (
                        datetime.datetime.now().timestamp()
                        + refresh_every_hours * 60 * 60
                    )
                    while datetime.datetime.now().timestamp() < end_ts:
                        # according to the docs, sleep of any value *should* be cancellable here
                        # but in practice, it was not! so we have to do it ourselves?
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    # XXX: need to differentiate signal-based cancellation (e.g. CTRL-C) from .cancel()...
                    pass

            self._task = asyncio.create_task(sleeper())
            self._task.set_name("sleeper")
            await self._task

    def force_refresh(self):
        self._task.cancel()


async def main():
    async def _cb(evs):
        print("Sync these:")
        print(evs)

    DB_PATH = ".ical_main.sqlite3"
    kv = TheBurgBotKeyedJSONStore(db_path=DB_PATH, namespace="events")
    await kv.initialize()
    await kv.setnx(
        "ical/urls",
        {
            "Outer Planes": "https://calendar.google.com/calendar/ical/outerplanesgames%40gmail.com/public/basic.ics"
        },
    )
    syncer = iCalSyncer(db_path=DB_PATH, filter_strings=["Prerelease"])

    last_sig = 0

    def sighandler(sig, *args):
        nonlocal last_sig
        if datetime.datetime.now().timestamp() - last_sig < 1:
            sys.exit(sig)
        syncer.force_refresh()
        last_sig = datetime.datetime.now().timestamp()

    signal.signal(signal.SIGINT, sighandler)
    await syncer.start_sync(_cb, exit_immediately=False, refresh_every_hours=0.005)


if __name__ == "__main__":
    asyncio.run(main())
