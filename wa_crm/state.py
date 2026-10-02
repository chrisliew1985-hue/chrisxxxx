"""Small SQLite store that remembers what has already been processed."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_watermark (
    account TEXT PRIMARY KEY,
    processed_until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_watermark (
    account TEXT, chat_jid TEXT, processed_until TEXT NOT NULL,
    PRIMARY KEY (account, chat_jid)
);
CREATE TABLE IF NOT EXISTS appointments (
    uid TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    chat_jid TEXT NOT NULL,
    start TEXT NOT NULL,          -- local YYYY-MM-DDTHH:MM
    title TEXT NOT NULL,
    status TEXT NOT NULL          -- confirmed / cancelled
);
"""


class State:
    def __init__(self, path: str | Path):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def account_watermark(self, account: str) -> datetime | None:
        row = self.db.execute(
            "SELECT processed_until FROM account_watermark WHERE account = ?", (account,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_account_watermark(self, account: str, ts: datetime) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO account_watermark VALUES (?, ?)", (account, ts.isoformat())
        )
        self.db.commit()

    def chat_watermark(self, account: str, jid: str) -> datetime | None:
        row = self.db.execute(
            "SELECT processed_until FROM chat_watermark WHERE account = ? AND chat_jid = ?",
            (account, jid),
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_chat_watermark(self, account: str, jid: str, ts: datetime) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO chat_watermark VALUES (?, ?, ?)", (account, jid, ts.isoformat())
        )
        self.db.commit()

    def upcoming(self, chat_jid: str, after_local: str, account: str | None = None) -> list[dict]:
        sql = "SELECT * FROM appointments WHERE chat_jid = ? AND status = 'confirmed' AND start >= ?"
        args: list = [chat_jid, after_local]
        if account:
            sql += " AND account = ?"
            args.append(account)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY start", args)]

    def get(self, uid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM appointments WHERE uid = ?", (uid,)).fetchone()
        return dict(row) if row else None

    def save_appointment(self, uid, account, chat_jid, start, title, status) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO appointments VALUES (?, ?, ?, ?, ?, ?)",
            (uid, account, chat_jid, start, title, status),
        )
        self.db.commit()
