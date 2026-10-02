"""Daily job: WhatsApp -> Claude -> Apple Calendar + CRM.

    python -m wa_crm run              # normal daily run
    python -m wa_crm run --dry-run    # show what would happen, change nothing
    python -m wa_crm serve            # cloud: stay running and do a run every day at run_at
    python -m wa_crm setup-notion --parent-page <page id>
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic

from .calendar_icloud import DryRunCalendar, ICloudCalendar, event_uid
from .config import Config, load_config
from .crm import ContactRecord, CsvCRM, DryRunCRM, NotionCRM
from .extract import ChatAnalysis, Extractor
from . import cloud_store, whatsapp
from .state import State
from .whatsapp import Chat

log = logging.getLogger("wa_crm")

TYPE_LABEL = {"client": "Client", "agent": "Agent", "personal": "Personal", "other": "Other"}


class Runner:
    def __init__(self, cfg: Config, extractor, calendar, crm, state: State, dry_run: bool = False):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.extractor = extractor
        self.calendar = calendar
        self.crm = crm
        self.state = state
        self.dry_run = dry_run
        self.stats = {"chats": 0, "events_added": 0, "events_removed": 0, "contacts": 0, "errors": 0}

    def run(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if self.cfg.source == "cloud":
            self.check_collector()
        for account, db_path in self.cfg.accounts.items():
            try:
                self.run_account(account, db_path, now)
            except FileNotFoundError as e:
                log.error("%s", e)
                self.stats["errors"] += 1
        return self.stats

    def check_collector(self) -> None:
        """Warn loudly when a WhatsApp account is no longer linked in the cloud."""
        try:
            status = cloud_store.account_status(self.cfg.cloud_db_path)
        except FileNotFoundError as e:
            log.error("%s", e)
            return
        for account in self.cfg.accounts:
            state = status.get(account, {}).get("state", "never started")
            if state != "connected":
                self.stats["errors"] += 1
                log.error("WhatsApp '%s' is %s - messages may be missing. %s", account, state,
                          status.get(account, {}).get("detail") or "")

    def run_account(self, account: str, db_path: str, now: datetime) -> None:
        since = self.state.account_watermark(account) or (
            now - timedelta(days=self.cfg.first_run_lookback_days))
        if self.cfg.source == "cloud":
            read_chats, db_path = cloud_store.read_chats, self.cfg.cloud_db_path
        else:
            read_chats = whatsapp.read_chats
        chats = read_chats(account, db_path, active_since=since,
                           history_since=since - timedelta(days=self.cfg.context_days),
                           include_groups=self.cfg.include_groups)
        log.info("[%s] %d chats with new messages since %s", account, len(chats),
                 since.astimezone(self.tz).strftime("%Y-%m-%d %H:%M"))

        failed = False
        for chat in chats:
            new_since = max(since, self.state.chat_watermark(account, chat.jid) or since)
            if chat.last_timestamp <= new_since:
                continue
            try:
                self.process_chat(chat, new_since, now)
                if not self.dry_run:
                    self.state.set_chat_watermark(account, chat.jid, chat.last_timestamp)
            except (anthropic.APIError, OSError, ValueError) as e:
                failed = True
                self.stats["errors"] += 1
                log.exception("[%s] failed on chat %s: %s", account, chat.name, e)

        # Only move the account watermark when every chat succeeded, so a failed
        # chat is retried next run (finished chats are skipped by their own watermark).
        if not failed and not self.dry_run:
            self.state.set_account_watermark(account, now)

    def process_chat(self, chat: Chat, new_since: datetime, now: datetime) -> None:
        self.stats["chats"] += 1
        now_local = now.astimezone(self.tz).strftime("%Y-%m-%dT%H:%M")
        known = self.state.upcoming(chat.jid, now_local, account=chat.account)
        print(f"\n{chat.account} | {chat.name} {chat.phone or ''}")

        analysis = self.extractor.analyze(chat, new_since, known)
        if analysis is None:
            return

        self.sync_appointments(chat, analysis)

        if analysis.contact_type in ("client", "agent") or self.cfg.crm_include_personal:
            upcoming = self.state.upcoming(chat.jid, now_local)
            record = ContactRecord(
                whatsapp_id=chat.jid,
                name=chat.name,
                phone=chat.phone,
                type=TYPE_LABEL[analysis.contact_type],
                client_role=(analysis.client_role or "unknown").capitalize()
                if analysis.contact_type == "client" else None,
                potential=analysis.potential.capitalize(),
                potential_reason=analysis.potential_reason,
                summary=analysis.summary,
                requirements=analysis.requirements,
                next_step=analysis.next_step,
                last_contact=chat.last_timestamp.astimezone(self.tz).date().isoformat(),
                accounts=[chat.account],
                next_appointment=upcoming[0]["start"] if upcoming else None,
            )
            self.crm.upsert(record)
            self.stats["contacts"] += 1

    def sync_appointments(self, chat: Chat, analysis: ChatAnalysis) -> None:
        label = TYPE_LABEL[analysis.contact_type]
        for appt in analysis.appointments:
            if appt.status == "tentative":
                print(f"  [skip] tentative: {appt.start} {appt.title}")
                continue

            if appt.replaces_start:
                old_uid = event_uid(chat.account, chat.jid, appt.replaces_start)
                if self.state.get(old_uid):
                    self.calendar.delete(old_uid)
                    self.stats["events_removed"] += 1
                    if not self.dry_run:
                        old = self.state.get(old_uid)
                        self.state.save_appointment(old_uid, chat.account, chat.jid,
                                                    old["start"], old["title"], "cancelled")

            uid = event_uid(chat.account, chat.jid, appt.start)
            if appt.status == "cancelled":
                if not appt.replaces_start and self.state.get(uid):
                    self.calendar.delete(uid)
                    self.stats["events_removed"] += 1
                    if not self.dry_run:
                        self.state.save_appointment(uid, chat.account, chat.jid, appt.start,
                                                    appt.title, "cancelled")
                continue

            title = f"[{label}] {appt.title}" if label in ("Client", "Agent") else appt.title
            description = "\n".join(filter(None, [
                f"Contact: {chat.name}" + (f" ({chat.phone})" if chat.phone else ""),
                f"WhatsApp: https://wa.me/{chat.phone.lstrip('+')}" if chat.phone else None,
                f"Via: {chat.account}",
                f"Type: {label}" + (f" / {analysis.client_role}" if analysis.client_role else ""),
                f"Potential: {analysis.potential}",
                appt.notes and f"\n{appt.notes}",
                "\nAdded automatically from WhatsApp by wa-crm.",
            ]))
            self.calendar.upsert(uid, title, appt.start, appt.duration_minutes,
                                 appt.location, description)
            self.stats["events_added"] += 1
            if not self.dry_run:
                self.state.save_appointment(uid, chat.account, chat.jid, appt.start, title,
                                            "confirmed")


def build_runner(cfg: Config, dry_run: bool) -> Runner:
    extractor = Extractor(
        cfg.timezone,
        client=anthropic.Anthropic(api_key=cfg.secret("ANTHROPIC_API_KEY", required=False)),
        model=cfg.model,
    )
    if dry_run:
        calendar, crm = DryRunCalendar(), DryRunCRM()
    else:
        calendar = ICloudCalendar(cfg.secret("ICLOUD_APPLE_ID"), cfg.secret("ICLOUD_APP_PASSWORD"),
                                  cfg.calendar_name, cfg.timezone, cfg.alarm_minutes)
        if cfg.crm_backend == "notion":
            crm = NotionCRM(cfg.secret("NOTION_TOKEN"), cfg.secret("NOTION_DATABASE_ID"),
                            cfg.timezone)
        elif cfg.crm_backend == "csv":
            crm = CsvCRM(cfg.crm_csv_path)
        else:
            raise SystemExit(f"Unknown crm_backend {cfg.crm_backend!r} (use notion or csv)")
    return Runner(cfg, extractor, calendar, crm, State(cfg.state_path), dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wa_crm")
    parser.add_argument("--config", help="Path to config.yaml (default ~/.wa-crm/config.yaml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Process new WhatsApp messages")
    run.add_argument("--dry-run", action="store_true",
                     help="Print what would be added; don't touch calendar, CRM or state")
    serve_p = sub.add_parser("serve", help="Run forever, processing once a day at run_at (cloud)")
    serve_p.add_argument("--run-now", choices=["dry", "real"],
                         help="Also do one run immediately on start (dry = preview only)")
    notion = sub.add_parser("setup-notion", help="Create the CRM database in Notion")
    notion.add_argument("--parent-page", required=True, help="ID of the Notion page to put it in")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.cmd == "setup-notion":
        db_id = NotionCRM.create_database(cfg.secret("NOTION_TOKEN"), args.parent_page)
        print(f"Created Notion database. Add this line to ~/.wa-crm/.env:\nNOTION_DATABASE_ID={db_id}")
        return 0

    if args.cmd == "serve":
        if args.run_now:
            try:
                run_once(cfg, dry_run=args.run_now == "dry")
            except Exception:
                log.exception("Start-up run failed")
        serve(cfg)
        return 0

    stats = run_once(cfg, args.dry_run)
    return 1 if stats["errors"] else 0


def run_once(cfg: Config, dry_run: bool = False) -> dict:
    stats = build_runner(cfg, dry_run).run()
    print(f"\nDone: {stats['chats']} chats read, {stats['events_added']} appointments "
          f"added/updated, {stats['events_removed']} removed, {stats['contacts']} CRM contacts "
          f"updated, {stats['errors']} errors.", flush=True)
    return stats


def next_run(now: datetime, run_at: str, tz: ZoneInfo) -> datetime:
    hour, minute = (int(x) for x in run_at.split(":"))
    local = now.astimezone(tz)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target = (local + timedelta(days=1)).replace(hour=hour, minute=minute, second=0,
                                                     microsecond=0)
    return target


def serve(cfg: Config) -> None:
    tz = ZoneInfo(cfg.timezone)
    while True:
        target = next_run(datetime.now(timezone.utc), cfg.run_at, tz)
        log.info("Next run at %s", target.strftime("%Y-%m-%d %H:%M %Z"))
        while (remaining := (target - datetime.now(timezone.utc)).total_seconds()) > 0:
            time.sleep(min(remaining, 300))
        try:
            run_once(cfg)
        except Exception:
            # Keep the service alive; the next day's run picks up anything missed.
            log.exception("Daily run failed")


if __name__ == "__main__":
    sys.exit(main())
