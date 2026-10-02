"""Read messages saved by the cloud collector (collector/index.js)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .whatsapp import Chat, Message


def _connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        raise FileNotFoundError(
            f"Collector database not found at {db_path}. Is the WhatsApp collector running?")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def account_status(db_path: str | Path) -> dict[str, dict]:
    with _connect(db_path) as conn:
        return {r["account"]: dict(r) for r in conn.execute("SELECT * FROM status")}


def read_chats(
    account: str,
    db_path: str | Path,
    active_since: datetime,
    history_since: datetime,
    include_groups: bool = False,
    max_messages_per_chat: int = 300,
) -> list[Chat]:
    conn = _connect(db_path)
    try:
        jids = [r[0] for r in conn.execute(
            "SELECT DISTINCT chat_jid FROM messages WHERE account = ? AND ts > ?",
            (account, active_since.timestamp()),
        )]
        chats = []
        for jid in jids:
            is_group = jid.endswith("@g.us")
            if is_group and not include_groups:
                continue
            contact = conn.execute(
                "SELECT name, notify FROM contacts WHERE account = ? AND jid = ?", (account, jid)
            ).fetchone()
            name = (contact and (contact["name"] or contact["notify"])) or jid.split("@")[0]
            rows = conn.execute(
                """
                SELECT * FROM (
                  SELECT ts, from_me, sender, text FROM messages
                  WHERE account = ? AND chat_jid = ? AND ts > ?
                  ORDER BY ts DESC LIMIT ?
                ) ORDER BY ts ASC
                """,
                (account, jid, history_since.timestamp(), max_messages_per_chat),
            ).fetchall()
            chat = Chat(account=account, jid=jid, name=name, is_group=is_group)
            for r in rows:
                sender = "Me" if r["from_me"] else (r["sender"] or name)
                chat.messages.append(Message(
                    datetime.fromtimestamp(r["ts"], tz=timezone.utc), bool(r["from_me"]),
                    sender, r["text"]))
            if chat.messages:
                chats.append(chat)
        return chats
    finally:
        conn.close()
