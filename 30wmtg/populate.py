import asyncio

from theburgbot.common import dprint as print
from theburgbot.common import dt_to_date, http_get_cached, http_get_cached_json
from theburgbot.ical import MTG_SETS_URL


async def main():
    sets = await http_get_cached_json(MTG_SETS_URL)
    if sets["has_more"]:
        print("HAS_MORE! not implemented...")
        return
    
    print(len(sets))


if __name__ == "__main__":
    asyncio.run(main())
