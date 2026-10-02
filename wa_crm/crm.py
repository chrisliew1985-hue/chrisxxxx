"""CRM backends: a Notion database (recommended) or a local CSV file."""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


@dataclass
class ContactRecord:
    whatsapp_id: str            # chat JID, the unique key
    name: str
    phone: str | None
    type: str                   # Client / Agent / Personal / Other
    client_role: str | None     # Buyer / Tenant / Owner / Landlord / Investor
    potential: str              # Hot / Warm / Cold / None
    potential_reason: str
    summary: str
    requirements: str | None
    next_step: str | None
    last_contact: str           # YYYY-MM-DD
    accounts: list[str]         # which WhatsApp(s) this contact talks to
    next_appointment: str | None  # YYYY-MM-DDTHH:MM local


# ---------------------------------------------------------------- Notion

NOTION_VERSION = "2022-06-28"

TYPE_OPTIONS = [("Client", "green"), ("Agent", "blue"), ("Personal", "gray"), ("Other", "default")]
POTENTIAL_OPTIONS = [("Hot", "red"), ("Warm", "orange"), ("Cold", "blue"), ("None", "gray")]
ROLE_OPTIONS = [("Buyer", "green"), ("Tenant", "yellow"), ("Owner", "purple"),
                ("Landlord", "brown"), ("Investor", "pink"), ("Unknown", "gray")]


def _select(options):
    return {"select": {"options": [{"name": n, "color": c} for n, c in options]}}


NOTION_SCHEMA = {
    "Name": {"title": {}},
    "Type": _select(TYPE_OPTIONS),
    "Potential": _select(POTENTIAL_OPTIONS),
    "Client Role": _select(ROLE_OPTIONS),
    "Phone": {"phone_number": {}},
    "WhatsApp ID": {"rich_text": {}},
    "WhatsApp Account": {"multi_select": {"options": [
        {"name": "whatsapp", "color": "green"}, {"name": "business", "color": "blue"}]}},
    "Potential Reason": {"rich_text": {}},
    "Summary": {"rich_text": {}},
    "Requirements": {"rich_text": {}},
    "Next Step": {"rich_text": {}},
    "Last Contact": {"date": {}},
    "Next Appointment": {"date": {}},
    "Lock": {"checkbox": {}},
}


def _text(value: str | None) -> dict:
    return {"rich_text": [{"text": {"content": (value or "")[:2000]}}]}


class NotionCRM:
    """Upserts one Notion page per WhatsApp contact.

    Tick the "Lock" checkbox on a contact in Notion to stop the tool from
    overwriting its Type / Potential / Client Role (useful after a manual fix).
    """

    def __init__(self, token: str, database_id: str, timezone: str):
        self.database_id = database_id
        self.timezone = timezone
        self.http = httpx.Client(
            base_url="https://api.notion.com/v1/",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
            timeout=30,
        )

    @classmethod
    def create_database(cls, token: str, parent_page_id: str, title: str = "WhatsApp CRM") -> str:
        resp = httpx.post(
            "https://api.notion.com/v1/databases",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
            json={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"text": {"content": title}}],
                "properties": NOTION_SCHEMA,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def _find(self, whatsapp_id: str) -> dict | None:
        resp = self.http.post(
            f"databases/{self.database_id}/query",
            json={"filter": {"property": "WhatsApp ID", "rich_text": {"equals": whatsapp_id}}},
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        return results[0] if results else None

    def upsert(self, rec: ContactRecord) -> str:
        existing = self._find(rec.whatsapp_id)
        locked = bool(existing and existing["properties"].get("Lock", {}).get("checkbox"))

        accounts = set(rec.accounts)
        if existing:
            accounts |= {o["name"] for o in existing["properties"]["WhatsApp Account"]["multi_select"]}

        props = {
            "Name": {"title": [{"text": {"content": rec.name}}]},
            "WhatsApp ID": _text(rec.whatsapp_id),
            "WhatsApp Account": {"multi_select": [{"name": a} for a in sorted(accounts)]},
            "Potential Reason": _text(rec.potential_reason),
            "Summary": _text(rec.summary),
            "Last Contact": {"date": {"start": rec.last_contact}},
        }
        if rec.phone:
            props["Phone"] = {"phone_number": rec.phone}
        if rec.requirements:
            props["Requirements"] = _text(rec.requirements)
        if rec.next_step:
            props["Next Step"] = _text(rec.next_step)
        if rec.next_appointment:
            props["Next Appointment"] = {"date": {"start": rec.next_appointment,
                                                  "time_zone": self.timezone}}
        if not locked:
            props["Type"] = {"select": {"name": rec.type}}
            props["Potential"] = {"select": {"name": rec.potential}}
            if rec.client_role:
                props["Client Role"] = {"select": {"name": rec.client_role}}

        if existing:
            resp = self.http.patch(f"pages/{existing['id']}", json={"properties": props})
            action = "updated"
        else:
            resp = self.http.post("pages", json={"parent": {"database_id": self.database_id},
                                                 "properties": props})
            action = "created"
        resp.raise_for_status()
        return action


# ---------------------------------------------------------------- CSV

class CsvCRM:
    """Simple local CRM: one row per contact, opens in Excel / Numbers."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.columns = [f.name for f in fields(ContactRecord)]

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        with self.path.open(newline="", encoding="utf-8") as f:
            return {row["whatsapp_id"]: row for row in csv.DictReader(f)}

    def upsert(self, rec: ContactRecord) -> str:
        rows = self._load()
        row = asdict(rec)
        old = rows.get(rec.whatsapp_id)
        accounts = set(rec.accounts)
        if old:
            accounts |= set(filter(None, old.get("accounts", "").split(";")))
            for key in ("requirements", "next_step", "next_appointment", "phone"):
                row[key] = row[key] or old.get(key) or None
        row["accounts"] = ";".join(sorted(accounts))
        rows[rec.whatsapp_id] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.columns)
            writer.writeheader()
            for r in sorted(rows.values(), key=lambda r: (r["type"], r["name"])):
                writer.writerow({k: r.get(k) or "" for k in self.columns})
        return "updated" if old else "created"


class DryRunCRM:
    def upsert(self, rec: ContactRecord) -> str:
        print(f"  [crm] {rec.type:<8} {rec.potential:<5} {rec.name} {rec.phone or ''} "
              f"- {rec.potential_reason}")
        return "dry-run"
