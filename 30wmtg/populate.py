import asyncio
import re
import subprocess
from pathlib import Path

import aiosqlite
from alive_progress import alive_bar

from theburgbot.common import dprint as print
from theburgbot.common import http_get_path_cached_checksummed

THIRTY = 20

MTGJSON_SQLITE_CHECKSUM_URL = (
    "https://mtgjson.com/api/v5/AllPrintings.sqlite.bz2.sha256"
)
MTGJSON_SQLITE_ASSET_URL = "https://mtgjson.com/api/v5/AllPrintings.sqlite.bz2"


async def mtgjson_sqlite_path():
    asset_path = await http_get_path_cached_checksummed(
        MTGJSON_SQLITE_ASSET_URL, MTGJSON_SQLITE_CHECKSUM_URL
    )
    asset_uncompressed = Path(str(asset_path) + ".out")

    if not asset_uncompressed.exists():
        process = subprocess.run(["bunzip2", "-k", asset_path])
        if process.returncode != 0:
            raise Exception("bunzip2")

    return asset_uncompressed


async def main():
    asset_uncompressed = await mtgjson_sqlite_path()
    async with aiosqlite.connect(asset_uncompressed) as db:
        await db.execute(
            (
                "create table if not exists thirtyword_cards ("
                "card_uuid VARCHAR(36) NOT NULL,"
                "legal BOOLEAN NOT NULL,"
                "num_words INTEGER NOT NULL"
                ")"
            )
        )
        await db.commit()

        [(count,)] = await db.execute_fetchall("select count(*) from cards")
        print(f"Processing legality of {count} cards...")
        with alive_bar(count) as bar:
            cursor = await db.execute(
                "select uuid, replace(text, '\\n', ' ') as text from cards"
            )
            await db.commit()
            async for row in cursor:
                (uuid, text) = row
                if text:
                    text_rm_reminder_text = re.sub(
                        r"\s+", " ", re.sub(r"\([^\)]+\)", "", text).strip()
                    )
                    num_words = len(text_rm_reminder_text.split(" "))
                    legal = num_words <= THIRTY
                    await db.execute(
                        "insert into thirtyword_cards values (?, ?, ?)",
                        (uuid, legal, num_words),
                    )
                    await db.commit()
                bar()

        [(legal_count,)] = await db.execute_fetchall(
            "select count(*) from cards left join thirtyword_cards where cards.uuid = thirtyword_cards.card_uuid and thirtyword_cards.legal = 1"
        )
        [(illegal_count,)] = await db.execute_fetchall(
            "select count(*) from cards left join thirtyword_cards where cards.uuid = thirtyword_cards.card_uuid and thirtyword_cards.legal = 0"
        )
        print(f"{legal_count} legal, {illegal_count} illegal")


if __name__ == "__main__":
    asyncio.run(main())
