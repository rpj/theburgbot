import asyncio
from pathlib import Path
import subprocess
from theburgbot.common import dprint as print
from theburgbot.common import http_get_path_cached_checksummed
from theburgbot.ical import MTG_SETS_URL

MTGJSON_SQLITE_CHECKSUM_URL = "https://mtgjson.com/api/v5/AllPrintings.sqlite.bz2.sha256"
MTGJSON_SQLITE_ASSET_URL = "https://mtgjson.com/api/v5/AllPrintings.sqlite.bz2"

async def main():
    asset_path = await http_get_path_cached_checksummed(MTGJSON_SQLITE_ASSET_URL, MTGJSON_SQLITE_CHECKSUM_URL)
    print(asset_path)
    asset_uncompressed = Path(str(asset_path) + ".out")
    print(asset_uncompressed)
    print(type(asset_uncompressed))
    if not asset_uncompressed.exists():
        process = subprocess.run(["bunzip2", "-k", asset_path])
        print(process.stdout)
        print(process.stderr)
        print(process)


if __name__ == "__main__":
    asyncio.run(main())
