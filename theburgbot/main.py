import argparse
import os

import discord

from theburgbot.client import TheBurgBotClient
from theburgbot.commands import register_slash_commands


def parse_args() -> argparse.Namespace:
    args = argparse.ArgumentParser(description="")
    args.add_argument(
        "--sync_commands",
        action="store_true",
        help="Sync slash commands with the server.",
    )
    args.set_defaults(sync_commands=False)
    return args.parse_args()


def main():
    args = parse_args()

    client = register_slash_commands(
        TheBurgBotClient(
            db_path=os.getenv("THEBURGBOT_DB_PATH", "data/db.sqlite3"),
            sync_commands=args.sync_commands,
            command_prefix="/",
            intents=discord.Intents.all(),
        )
    )

    client.run(os.getenv("THEBURGBOT_DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
