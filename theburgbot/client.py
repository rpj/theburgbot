import discord

class TheBurgBotClient(discord.Client):
    async def on_ready(self):
        print("ready!")
        print(self)
        print(self.shard_id)
        print(self.application_id)

    async def on_message(self, message):
        print("message!")
        print(message)
        print(message.content)

        do_this_better = f"<@{self.application_id}>"
        print(do_this_better)
        if message.content.startswith(do_this_better):
            print("TO ME!")
