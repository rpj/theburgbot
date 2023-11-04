import discord

from typing import Dict

def register_intents(intents_config: Dict[str, bool]) -> discord.Intents:
    intents = discord.Intents.default()
    for (intent_name, intent_enabled) in intents_config.items():
        try:
            setattr(intents, intent_name, bool(intent_enabled))
        except AttributeError:
            print(f"Intent '{intent_name}' does not exist! Ignored.")
    return intents

