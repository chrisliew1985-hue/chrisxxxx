"""Read messages from the WhatsApp desktop apps on macOS.

Both the regular WhatsApp app and WhatsApp Business keep their chat history in a
local Core Data SQLite file (`ChatStorage.sqlite`). Reading that file is
read-only, needs no QR login and carries no risk of the number being banned,
unlike unofficial WhatsApp Web bots.

The database is copied (with its -wal/-shm journal files) into a temp folder
before it is opened, so a running WhatsApp app is never locked or disturbed.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Core Data stores dates as seconds since 2001-01-01 UTC.
APPLE_EPOCH_OFFSET = 978307200

DEFAULT_DB_PATHS = {
    "whatsapp": "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite",
    "business": "~/Library/Group Containers/group.net.whatsapp.WhatsAppSMB.shared/ChatStorage.sqlite",
}

SESSION_TYPE_GROUP = 1


@dataclass
class Message:
    timestamp: datetime
    from_me: bool
    sender: str
    text: str


@dataclass
class Chat:
    account: str
    jid: str
    name: str
    is_group: bool
    messages: list[Message] = field(default_factory=list)

    @property
    def phone(self) -> str | None:
        """E.164 phone number for individual chats, if the JID carries one."""
        user, _, server = self.jid.partition("@")
        if server == "s.whatsapp.net" and user.isdigit():
            return "+" + user
        return None

    @property
    def last_timestamp(self) -> datetime | None:
        return self.messages[-1].timestamp if self.messages else None


def _from_apple(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds + APPLE_EPOCH_OFFSET, tz=timezone.utc)


def _to_apple(dt: datetime) -> float:
    return dt.timestamp() - APPLE_EPOCH_OFFSET


def _snapshot(db_path: Path, workdir: Path) -> Path:
    target = workdir / db_path.name
    for suffix in ("", "-wal", "-shm"):
        src = db_path.with_name(db_path.name + suffix)
        if src.exists():
            shutil.copy2(src, target.with_name(target.name + suffix))
    return target


def read_chats(
    account: str,
    db_path: str | Path,
    active_since: datetime,
    history_since: datetime,
    include_groups: bool = False,
    max_messages_per_chat: int = 300,
) -> list[Chat]:
    """Return chats with at least one message after ``active_since``.

    Each chat carries its messages from ``history_since`` onwards, so the model
    sees enough earlier context to tell whether an appointment was confirmed.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        raise FileNotFoundError(
            f"WhatsApp database for '{account}' not found at {db_path}. "
            "Is the WhatsApp desktop app installed and logged in, and does this "
            "process have Full Disk Access?"
        )

    with tempfile.TemporaryDirectory() as tmp:
        conn = sqlite3.connect(_snapshot(db_path, Path(tmp)))
        conn.row_factory = sqlite3.Row
        try:
            return _query_chats(
                conn, account, active_since, history_since, include_groups, max_messages_per_chat
            )
        finally:
            conn.close()


def _query_chats(conn, account, active_since, history_since, include_groups, max_messages):
    sessions = conn.execute(
        """
        SELECT s.Z_PK AS pk, s.ZCONTACTJID AS jid, s.ZPARTNERNAME AS name,
               s.ZSESSIONTYPE AS session_type
        FROM ZWACHATSESSION s
        WHERE s.ZCONTACTJID IS NOT NULL
          AND s.ZCONTACTJID NOT LIKE '%@broadcast'
          AND s.ZCONTACTJID NOT LIKE '%@status'
          AND EXISTS (
            SELECT 1 FROM ZWAMESSAGE m
            WHERE m.ZCHATSESSION = s.Z_PK AND m.ZMESSAGEDATE > ?
          )
        """,
        (_to_apple(active_since),),
    ).fetchall()

    push_name_col = "m.ZPUSHNAME" if _has_column(conn, "ZWAMESSAGE", "ZPUSHNAME") else "NULL"

    chats = []
    for s in sessions:
        is_group = s["session_type"] == SESSION_TYPE_GROUP or s["jid"].endswith("@g.us")
        if is_group and not include_groups:
            continue
        rows = conn.execute(
            f"""
            SELECT * FROM (
              SELECT m.ZMESSAGEDATE AS ts, m.ZISFROMME AS from_me, m.ZTEXT AS text,
                     m.ZMESSAGETYPE AS mtype, {push_name_col} AS push_name
              FROM ZWAMESSAGE m
              WHERE m.ZCHATSESSION = ? AND m.ZMESSAGEDATE > ?
              ORDER BY m.ZMESSAGEDATE DESC
              LIMIT ?
            ) ORDER BY ts ASC
            """,
            (s["pk"], _to_apple(history_since), max_messages),
        ).fetchall()
        name = s["name"] or s["jid"].split("@")[0]
        chat = Chat(account=account, jid=s["jid"], name=name, is_group=is_group)
        for r in rows:
            text = r["text"]
            if not text:
                # Photos, voice notes, documents, locations, etc.
                text = "[attachment]" if r["mtype"] not in (None, 0) else None
            if not text:
                continue
            sender = "Me" if r["from_me"] else (r["push_name"] or name)
            chat.messages.append(
                Message(_from_apple(r["ts"]), bool(r["from_me"]), sender, text)
            )
        if chat.messages:
            chats.append(chat)
    return chats


def _has_column(conn, table, column) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))
