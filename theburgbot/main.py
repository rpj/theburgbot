import sys

import discord

from theburgbot.config import parse_config_file
from theburgbot.bot import register_intents
from theburgbot.client import TheBurgBotClient

if __name__ == "__main__":
    config = parse_config_file(sys.argv[-1])
    print(config)

    intents = register_intents(config["intents"])
    print(intents)

    client = TheBurgBotClient(intents=intents)
    client.run(config["discord"]["token"])
