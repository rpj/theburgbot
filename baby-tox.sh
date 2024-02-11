#!/bin/bash

poetry run pytest tests/

find ./theburgbot/ -name "*.py" | xargs poetry run pylint --rc-file=./.pylintrc -E
find ./30wmtg/ -name "*.py" | xargs poetry run pylint --rc-file=./.pylintrc -E

poetry run black theburgbot/*.py theburgbot/cmd_handlers/*.py tests/*.py 30wmtg/*.py && \
    poetry run isort theburgbot/*.py theburgbot/cmd_handlers/*.py tests/*.py 30wmtg/*.py
