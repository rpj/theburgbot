import os
from pathlib import Path

import pytest

from theburgbot import constants
from theburgbot.db import TheBurgBotDB

TEST_DB_PATH = Path(__file__).resolve().parent / "__test__.sqlite3"
APPENDED_SCHEMAS = []


def append_schema_for_test(db: TheBurgBotDB, schema_num: str, schema: str):
    global APPENDED_SCHEMAS
    s_path = db.schema_path / f"{schema_num}.sql"
    with open(s_path, "w+") as f:
        f.write(schema)
    APPENDED_SCHEMAS.append(s_path)


@pytest.fixture(autouse=True)
def auto_remove_on_both_ends():
    global APPENDED_SCHEMAS
    try:
        os.remove(TEST_DB_PATH)
    except FileNotFoundError:
        pass
    yield
    try:
        os.remove(TEST_DB_PATH)
        for appended_schema in APPENDED_SCHEMAS:
            os.remove(appended_schema)
    except FileNotFoundError:
        pass
    finally:
        APPENDED_SCHEMAS = []


@pytest.mark.asyncio
async def test_db_upgrade():
    db = TheBurgBotDB(TEST_DB_PATH)
    await db.initialize()
    ver_rows = await db._direct_exec(
        f"select version from {constants.INTERNAL_VERSION_TABLE_NAME}"
    )
    assert len(ver_rows) == constants.DB_EXPECT_TOTAL_VERS
    assert ver_rows[-1][0] == constants.DB_CUR_EXPECTED_VER

    append_schema_for_test(
        db,
        "9997",
        "create table TEST_ONE (foobar text not null);\n\n"
        + 'insert into TEST_ONE values ("baz");',
    )

    db2 = TheBurgBotDB(TEST_DB_PATH)
    await db2.initialize()

    ver_rows = await db2._direct_exec(
        f"select version from {constants.INTERNAL_VERSION_TABLE_NAME}"
    )
    assert len(ver_rows) == constants.DB_EXPECT_TOTAL_VERS + 1
    assert ver_rows[-1][0] == "9997"

    check_rows = await db2._direct_exec("select * from TEST_ONE")
    assert len(check_rows) == 1
    assert len(check_rows[0]) == 1
    assert check_rows[0][0] == "baz"

    try:
        os.remove(f"{TEST_DB_PATH}__v{constants.DB_CUR_EXPECTED_VER}.backup")
        assert True
    except FileNotFoundError:
        assert False


@pytest.mark.asyncio
async def test_register_user_flux():
    db = TheBurgBotDB(TEST_DB_PATH)
    await db.initialize()
    await db.register_user_flux("-1", "foo", "FooBar", "TEST_ACTION")
    rows = await db._direct_exec("select * from user_flux")
    assert len(rows) == 1
    (_ts, user_id, name, gname, action) = rows[0]
    assert user_id == "-1"
    assert name == "foo"
    assert gname == "FooBar"
    assert action == "TEST_ACTION"
