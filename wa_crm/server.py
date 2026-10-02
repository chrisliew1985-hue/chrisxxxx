"""Small HTTPS-behind-Caddy API so a daily Claude Routine can do the AI part.

The Routine (running on the user's Claude plan, no API key) calls:

  GET  /pending?limit=15   -> new chats to read, plus the rules and the answer format
  POST /results            -> Claude's analysis per chat. The server works out the
                              calendar changes and CRM rows and returns them; the
                              Routine applies them to Google Calendar and Notion via
                              its connectors (or, with iCloud credentials set, the
                              server writes Apple Calendar itself).
  POST /calendar-ids       -> {"ids": {"<uid>": "<Google event id>"}} after creating
                              events, so later moves/cancellations hit the same event.

Every request needs  Authorization: Bearer <token>.  The token is generated on
first start, saved in /data/server_token and printed in the logs.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from . import cloud_store
from .calendar_icloud import ICloudCalendar
from .config import Config
from .extract import SYSTEM_PROMPT, ChatAnalysis, _format_chat
from .main import Runner
from .state import State

log = logging.getLogger("wa_crm.server")

BATCH_TTL = timedelta(hours=6)

RESULT_INSTRUCTIONS = """For EACH chat in `chats`, read its `transcript` and produce one JSON \
object matching `result_schema` (the analysis). Then POST to /results:
{"batch_id": "<batch_id>", "results": [{"id": "<chat id>", "analysis": {...}}, ...]}
Dates in `start` / `replaces_start` are local time, format YYYY-MM-DDTHH:MM."""


class RecordingCalendar:
    """Records calendar changes for the reply, and forwards them to iCloud if configured.

    In Google mode (inner is None) the Routine applies the changes itself, using
    `event_id` to update or delete the event it created earlier.
    """

    def __init__(self, inner, state: State, tz: ZoneInfo):
        self.inner, self.state, self.tz, self.actions = inner, state, tz, []

    def upsert(self, uid, title, start_iso, duration_minutes, location, description):
        if self.inner:
            self.inner.upsert(uid, title, start_iso, duration_minutes, location, description)
        start = datetime.fromisoformat(start_iso).replace(tzinfo=self.tz)
        end = start + timedelta(minutes=max(duration_minutes, 15))
        self.actions.append({
            "action": "upsert", "uid": uid, "event_id": self.state.calendar_id(uid),
            "title": title, "start": start.isoformat(), "end": end.isoformat(),
            "location": location, "description": description,
        })

    def delete(self, uid):
        if self.inner:
            self.inner.delete(uid)
        self.actions.append({"action": "delete", "uid": uid, "event_id": self.state.calendar_id(uid)})


class NullCRM:
    """The Routine writes to Notion itself; the server only returns the rows."""

    def upsert(self, rec):
        return "returned"


class Api:
    def __init__(self, cfg: Config, state: State, calendar_factory=None):
        """calendar_factory: returns an ICloudCalendar, or None for Google mode."""
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.state = state
        self.calendar_factory = calendar_factory
        self.calendar_mode = "apple" if calendar_factory else "google"
        self.batches: dict[str, dict] = {}

    def pending(self, limit: int = 15, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        self._expire(now)
        # Chats handed out but not answered yet aren't handed out twice.
        in_flight = {(c.account, c.jid) for b in self.batches.values() for c in b["chats"].values()}

        candidates = []
        for account in self.cfg.accounts:
            since = self.state.account_watermark(account) or (
                now - timedelta(days=self.cfg.first_run_lookback_days))
            chats = cloud_store.read_chats(
                account, self.cfg.cloud_db_path, active_since=since,
                history_since=since - timedelta(days=self.cfg.context_days),
                include_groups=self.cfg.include_groups)
            for chat in chats:
                new_since = max(since, self.state.chat_watermark(account, chat.jid) or since)
                if chat.last_timestamp > new_since and (account, chat.jid) not in in_flight:
                    candidates.append((chat, new_since))

        candidates.sort(key=lambda c: c[0].last_timestamp)
        picked, remaining = candidates[:limit], len(candidates) - min(limit, len(candidates))

        batch_id = secrets.token_hex(8)
        now_local = now.astimezone(self.tz).strftime("%Y-%m-%dT%H:%M")
        items, entries = [], {}
        for i, (chat, new_since) in enumerate(picked, 1):
            known = self.state.upcoming(chat.jid, now_local, account=chat.account)
            entries[str(i)] = chat
            items.append({
                "id": str(i), "account": chat.account, "name": chat.name, "phone": chat.phone,
                "is_group": chat.is_group,
                "transcript": _format_chat(chat, new_since, self.tz, known),
            })
        self.batches[batch_id] = {
            "created": now, "chats": entries,
            # When this batch covers everything, finishing it moves the account watermark.
            "scan_time": now if remaining == 0 else None,
        }
        return {
            "batch_id": batch_id,
            "calendar_mode": self.calendar_mode,
            "instructions": SYSTEM_PROMPT + "\n\n" + RESULT_INSTRUCTIONS,
            "result_schema": ChatAnalysis.model_json_schema(),
            "whatsapp_status": self._status(),
            "chats": items,
            "remaining": remaining,
        }

    def results(self, body: dict, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        batch = self.batches.get(body.get("batch_id", ""))
        if batch is None:
            raise KeyError("Unknown or expired batch_id - call /pending again.")

        inner = self.calendar_factory() if self.calendar_factory else None
        calendar = RecordingCalendar(inner, self.state, self.tz)
        runner = Runner(self.cfg, None, calendar, NullCRM(), self.state)
        crm_rows, errors = [], []
        for item in body.get("results", []):
            chat = batch["chats"].get(str(item.get("id")))
            if chat is None:
                errors.append({"id": item.get("id"), "error": "unknown chat id"})
                continue
            try:
                analysis = ChatAnalysis.model_validate(item.get("analysis"))
                record = runner.apply_analysis(chat, analysis, now)
            except ValidationError as e:
                errors.append({"id": item["id"], "error": f"analysis does not match schema: {e}"})
                continue
            except Exception as e:   # calendar/network problems: keep going, retry next run
                log.exception("Failed applying chat %s", chat.name)
                errors.append({"id": item["id"], "error": str(e)})
                continue
            self.state.set_chat_watermark(chat.account, chat.jid, chat.last_timestamp)
            batch["chats"].pop(str(item["id"]))
            if record:
                crm_rows.append(asdict(record))

        if not batch["chats"]:
            if batch["scan_time"]:
                for account in self.cfg.accounts:
                    self.state.set_account_watermark(account, batch["scan_time"])
            self.batches.pop(body["batch_id"], None)

        return {"calendar_mode": self.calendar_mode, "calendar": calendar.actions,
                "crm": crm_rows, "errors": errors, "unanswered": sorted(batch["chats"])}

    def calendar_ids(self, body: dict) -> dict:
        ids = body.get("ids") or {}
        if not isinstance(ids, dict):
            raise ValueError('expected {"ids": {"<uid>": "<event id>"}}')
        for uid, event_id in ids.items():
            if event_id:
                self.state.set_calendar_id(str(uid), str(event_id))
        return {"saved": len(ids)}

    def _status(self) -> dict:
        try:
            status = cloud_store.account_status(self.cfg.cloud_db_path)
        except FileNotFoundError:
            status = {}
        return {a: status.get(a, {}).get("state", "never started") for a in self.cfg.accounts}

    def _expire(self, now: datetime) -> None:
        for bid in [b for b, v in self.batches.items() if now - v["created"] > BATCH_TTL]:
            del self.batches[bid]


def load_token(data_dir: Path, env_token: str | None) -> str:
    if env_token:
        return env_token
    path = data_dir / "server_token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()


def make_handler(api: Api, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if given and hmac.compare_digest(given, token):
                return True
            time.sleep(1)   # slow down guessing
            self._send(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/health":
                return self._send(200, {"ok": True})
            if not self._authorized():
                return
            if url.path == "/pending":
                limit = int(parse_qs(url.query).get("limit", ["15"])[0])
                return self._send(200, api.pending(limit=max(1, min(limit, 50))))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return
            path = urlparse(self.path).path
            if path not in ("/results", "/calendar-ids"):
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                self._send(200, api.results(body) if path == "/results" else api.calendar_ids(body))
            except KeyError as e:
                self._send(409, {"error": str(e.args[0])})
            except (json.JSONDecodeError, ValueError) as e:
                self._send(400, {"error": f"bad request: {e}"})

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def serve_api(cfg: Config, port: int = 8080) -> None:
    data_dir = Path(cfg.cloud_db_path).parent
    token = load_token(data_dir, cfg.secret("WA_SERVER_TOKEN", required=False))

    calendar_factory = None   # Google Calendar: the Routine writes events via its connector
    if cfg.secret("ICLOUD_APP_PASSWORD", required=False):
        def calendar_factory():
            return ICloudCalendar(cfg.secret("ICLOUD_APPLE_ID"), cfg.secret("ICLOUD_APP_PASSWORD"),
                                  cfg.calendar_name, cfg.timezone, cfg.alarm_minutes)

    api = Api(cfg, State(cfg.state_path), calendar_factory)
    print(f"Calendar: {api.calendar_mode}", flush=True)
    print(f"API listening on :{port}. Token for the Claude Routine is saved in "
          f"{data_dir / 'server_token'} (show it with: docker compose exec wa-crm cat /data/server_token)",
          flush=True)
    # Single-threaded on purpose: requests are rare and SQLite stays on one thread.
    HTTPServer(("0.0.0.0", port), make_handler(api, token)).serve_forever()
