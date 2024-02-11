import asyncio

from theburgbot.common import dprint as print
from theburgbot.common import dt_to_date, http_get_cached, http_get_cached_json
from theburgbot.ical import MTG_SETS_URL


async def main():
    sets = await http_get_cached_json(MTG_SETS_URL)
    if sets["has_more"]:
        print("HAS_MORE! not implemented...")
        return

    sets_data = sets["data"]
    cards_count = sum([set_dict["card_count"] for set_dict in sets_data])
    print(f"{cards_count} across {len(sets_data)} sets")


if __name__ == "__main__":
    asyncio.run(main())
