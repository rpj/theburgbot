import json
import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class DiscordIDs:
    GUILD_ID: int = -1
    INVITE_CHANNEL_ID: int = -1
    ROLE_REACTION_MESSAGE_ID: int = -1
    ADMINS_ROLE_ID: int = -1
    ADMINS_CHANNEL_ID: int = -1


discord_ids = DiscordIDs()
reaction_roles: Dict[str, int] = {}

"""
This file is required to have a definition matching DiscordIDs above, e.g.
```
{
    "GUILD_ID": ...,
    "INVITE_CHANNEL_ID": ...,
    ...,
}
```
"""
with open(
    os.getenv("THEBURGBOT_DISCORD_IDS_JSON_PATH", "config/discord_ids.json"), "r"
) as f:
    discord_ids = DiscordIDs(**json.load(f))

"""
Key's are the emoji itself, values are the Role ID.

Example:

```json
{
    "♟️": -1,
    "🃏": -1,
    "🕹️": -1
}
```
"""
with open(
    os.getenv("THEBURGBOT_REACTION_ROLES_JSON_PATH", "config/reaction_roles.json"), "r"
) as f:
    reaction_roles = json.load(f)
