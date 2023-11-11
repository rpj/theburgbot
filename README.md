## Setup

1. Setup a reverse proxy to `constants.DEFAULT_PORT` to plumb the HTTP API endpoints.
1. Set required environment variables:
    1. `THEBURGBOT_DISCORD_TOKEN`: bot's Discord token
    1. `OPENAI_API_KEY`: OpenAPI secret key for [/gpt](./theburgbot/cmd_handlers/gpt.py)
    1. `TWITCH_APP_ID`: Twitch Application ID for [/igdb]()
    1. `TWITCH_APP_SECRET`: Twitch Application secret for [/igdb]()
1. Create a Discord IDs JSON file and set all required IDs.
    1. Set environment variable `THEBURGBOT_DISCORD_IDS_JSON_PATH` to control the path, or create it at the [default path](./theburgbot/config.py#L29)
1. Create a Reaction/Roles mapping JSON file.
    1. `THEBURGBOT_REACTION_ROLES_JSON_PATH` controls the path, or [the default](./theburgbot/config.py#L47)
1. `poetry install` (poetry version >=1.5)

## Running

```
poetry run main
```

If you change or update slash command definitions and want them to be reflected on Discord, use `--sync_commands`. Do not over-use this option as the action is (heavily) rate-limited!

## Development

### Test

```shell
poetry run pytest tests/
```

### Lint

```shell
find ./theburgbot/ -name "*.py" | xargs poetry run pylint --rc-file=./.pylintrc
```

### Fix style

```shell
poetry run black theburgbot/*.py theburgbot/cmd_handlers/*.py tests/*.py && \
    poetry run isort theburgbot/*.py theburgbot/cmd_handlers/*.py tests/*.py 
```