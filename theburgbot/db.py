import datetime
import functools
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import chevron
import nanoid

from theburgbot import constants

LOGGER = logging.getLogger("discord")


def reduce_by_empty_newline(a: List[List[Any]], x) -> List[List[Any]]:
    a[-1].append(x)
    if len(x) == 1 and x == "\n":
        a.append([])
    return a


# https://stackoverflow.com/questions/42043226/using-a-coroutine-as-decorator
def audit_log_start_end_async(event_name_prefix, db_path):
    _db = TheBurgBotDB(db_path)

    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            await _db.audit_log_event(event=f"{event_name_prefix}__START")
            result = await func(*args, **kwargs)
            await _db.audit_log_event(event=f"{event_name_prefix}__END")
            return result

        return wrapped

    return wrapper


class TheBurgBotDB:
    db_path: str
    schema_path: str

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).resolve()
        self.schema_path = Path(__file__).resolve().parent / "schema"

    async def _initialize_schemas(self, schema_dirents: List[os.DirEntry]):
        new_ver = None
        async with aiosqlite.connect(self.db_path) as db:
            for dirent in schema_dirents:
                try:
                    with open(dirent.path, "r") as scf:
                        lines = scf.readlines()
                        exec_lists = functools.reduce(
                            reduce_by_empty_newline, lines, [[]]
                        )
                        for exec_list in exec_lists:
                            exec_str = "".join(exec_list)
                            await db.execute(exec_str)
                        await db.commit()
                        LOGGER.info(f"{len(exec_lists)} statements in {dirent.name}")

                        new_ver = schema_dirents[-1].name.strip(".sql")
                        now = datetime.datetime.now()
                        await db.execute(
                            "insert into "
                            + constants.INTERNAL_VERSION_TABLE_NAME
                            + " values (?, ?, ?)",
                            (new_ver, now, now),
                        )
                        await db.commit()
                except:
                    raise Exception(f"_initialize_schemas at {dirent}")
            return new_ver

    async def initialize(self):
        schema_dirents: List[os.DirEntry] = list(
            filter(
                lambda o: o.name.endswith(".sql"),
                sorted(
                    os.scandir(path=self.schema_path),
                    key=lambda o: o.name,
                ),
            )
        )

        if not os.path.exists(self.db_path):
            LOGGER.info(f"Creating database...")
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute(
                        """create table """
                        + constants.INTERNAL_VERSION_TABLE_NAME
                        + """(version text not null,
                            created date not null,
                            updated date not null
                        )"""
                    )
                    await db.commit()

                new_ver = await self._initialize_schemas(schema_dirents)
                LOGGER.info(f"Created database v{new_ver} at {self.db_path}")
            except:
                LOGGER.critical(f"DB init failed", exc_info=True)
                os.remove(self.db_path)
                sys.exit(-1)
        else:
            ver_rows = await self._direct_exec(
                f"select version from {constants.INTERNAL_VERSION_TABLE_NAME}"
            )

            if len(ver_rows) > len(schema_dirents):
                raise Exception(
                    f"DB is newer than schema! {ver_rows} vs {schema_dirents}"
                )

            if len(ver_rows) == len(schema_dirents):
                if ver_rows[-1][0] != schema_dirents[-1].name.strip(".sql"):
                    raise Exception(
                        f"DB version mismatch! {ver_rows[-1][0]} vs. {schema_dirents[-1].name}"
                    )
                return

            cur_ver = ver_rows[-1][0]
            shutil.copyfile(self.db_path, f"{self.db_path}__v{cur_ver}.backup")
            num_vers_to_update = len(schema_dirents) - len(ver_rows)
            update_schemas = schema_dirents[-num_vers_to_update:]
            new_ver = await self._initialize_schemas(update_schemas)
            LOGGER.info(
                f"Updated DB to v{new_ver} with {len(update_schemas)} additional schemas: {', '.join([i.name for i in update_schemas])}"
            )

    async def _direct_exec(self, sql, p_tuple=()):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, p_tuple)
            await db.commit()
            return await cursor.fetchall()

    async def register_user_flux(
        self, user_id: str, name: str, global_name: str, action: str
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "insert into user_flux values (?, ?, ?, ?, ?)",
                (datetime.datetime.now(), user_id, name, global_name, action),
            )
            await db.commit()

    async def get_http_static(self, url_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "select * from http_static where pub_id = ?", (url_id,)
            )
            await db.commit()
            return await cursor.fetchall()

    async def get_http_static_rendered(self, url_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "select rendered from http_static where pub_id = ?", (url_id,)
            )
            await db.commit()
            rows = await cursor.fetchall()
            if len(rows) > 1:
                LOGGER.warning(f"HTTP static ID collision?! {url_id}")
                print(rows)
            return None if len(rows) == 0 else rows[0][0]

    async def get_users_http_statics(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "select created, updated, pub_id, from_command, title from http_static where from_user_id = ?",
                (user_id,),
            )
            await db.commit()
            return await cursor.fetchall()

    async def add_http_static(
        self,
        from_user_id,
        from_command,
        template,
        src_obj,
        title,
    ) -> str:
        now = datetime.datetime.now()
        tmpl_path = (
            Path(__file__).resolve().parent / ".." / "templates" / f"{template}.html"
        )
        with open(tmpl_path) as tmpl_f:
            async with aiosqlite.connect(self.db_path) as db:
                new_id = nanoid.generate()
                await db.execute(
                    "insert into http_static values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        None,
                        new_id,
                        from_user_id,
                        from_command,
                        chevron.render(tmpl_f, src_obj),
                        template,
                        json.dumps(src_obj),
                        title,
                    ),
                )
                await db.commit()
                return new_id

    async def cmd_use_log(self, command: str, user_id: int, display_name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "insert into cmd_use_log values (?, ?, ?, ?)",
                (
                    command,
                    user_id,
                    display_name,
                    datetime.datetime.now(),
                ),
            )
            await db.commit()

    # pylint: disable=missing-kwoa
    async def audit_log_event_json(
        self,
        message_json: Optional[Dict[Any, Any]] = None,
        **kwargs,
    ):
        return await self.audit_log_event(json.dumps(message_json), **kwargs)

    async def audit_log_event(
        self,
        message: Optional[str] = None,
        *,
        event: str,
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "insert into audit_log values (?, ?, ?)",
                (
                    event,
                    message,
                    datetime.datetime.now(),
                ),
            )
            await db.commit()

    async def log_message(
        self,
        channel_id: str,
        channel_name: str,
        author_id: str,
        author_name: str,
        message_id: str,
        content: str,
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "insert into message_log values (?, ?, ?, ?, ?, ?, ?)",
                (
                    channel_id,
                    channel_name,
                    author_id,
                    author_name,
                    message_id,
                    content,
                    datetime.datetime.now(),
                ),
            )
            await db.commit()

    async def _passphrase_exists(self, db, passphrase: str) -> bool:
        async with db.execute(
            "select * from invites where passphrase = ?", (passphrase,)
        ) as cursor:
            rows = await cursor.fetchall()
            return (len(rows) == 1, rows[0] if len(rows) else [])

    async def passphrase_exists(self, passphrase: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            return (await self._passphrase_exists(db, passphrase))[0]

    async def add_new_invite(
        self, passphrase: str, requestor_name: str, requestor_id: str, invite_for: str
    ):
        async with aiosqlite.connect(self.db_path) as db:
            new_id = nanoid.generate()
            await db.execute(
                "insert into invites values (?, ?, NULL, NULL, ?, ?, ?, ?)",
                (
                    passphrase,
                    datetime.datetime.now(),
                    requestor_name,
                    requestor_id,
                    invite_for,
                    new_id,
                ),
            )
            await db.commit()
            if db.total_changes != 1:
                raise BaseException()
            return new_id

    def _can_redeem_cond(self, exists, row) -> bool:
        return exists and len(row) > 4 and row[2] is None and row[3] is None

    async def can_redeem_invite(self, passphrase: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            (exists, row) = await self._passphrase_exists(db, passphrase)
            return self._can_redeem_cond(exists, row)

    async def try_redeem_invite(self, passphrase: str, code) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            (exists, row) = await self._passphrase_exists(db, passphrase)
            if self._can_redeem_cond(exists, row):
                await db.execute(
                    "update invites set discord_code = ?, redeemed_at = ? where passphrase = ?",
                    (code, datetime.datetime.now(), passphrase),
                )
                await db.commit()
                return code
            return None

    async def get_invites(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "select * from invites",
            )
            await db.commit()
            return await cursor.fetchall()
