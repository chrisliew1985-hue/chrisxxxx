"""Write appointments into Apple Calendar via iCloud CalDAV.

Uses an app-specific password (appleid.apple.com > Sign-In and Security >
App-Specific Passwords), so it works from any machine, and events sync to the
Calendar app on the Mac, iPhone and iPad.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import caldav
from icalendar import Alarm, Calendar, Event

log = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"


def event_uid(account: str, chat_jid: str, start: str) -> str:
    digest = hashlib.sha1(f"{account}|{chat_jid}|{start}".encode()).hexdigest()[:20]
    return f"wa-crm-{digest}@wa-crm"


def build_ics(
    uid: str,
    title: str,
    start: datetime,
    duration_minutes: int,
    location: str | None,
    description: str,
    alarm_minutes: int | None,
) -> str:
    cal = Calendar()
    cal.add("prodid", "-//wa-crm//WhatsApp appointments//EN")
    cal.add("version", "2.0")
    ev = Event()
    ev.add("uid", uid)
    ev.add("summary", title)
    ev.add("dtstart", start)
    ev.add("dtend", start + timedelta(minutes=max(duration_minutes, 15)))
    ev.add("dtstamp", datetime.now(timezone.utc))
    if location:
        ev.add("location", location)
    ev.add("description", description)
    if alarm_minutes:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", title)
        alarm.add("trigger", timedelta(minutes=-alarm_minutes))
        ev.add_component(alarm)
    cal.add_component(ev)
    return cal.to_ical().decode()


class ICloudCalendar:
    def __init__(self, apple_id: str, app_password: str, calendar_name: str, timezone: str,
                 alarm_minutes: int | None = 60, url: str = ICLOUD_CALDAV_URL):
        self.tz = ZoneInfo(timezone)
        self.alarm_minutes = alarm_minutes
        client = caldav.DAVClient(url=url, username=apple_id, password=app_password)
        principal = client.principal()
        calendars = {c.get_display_name(): c for c in principal.calendars()}
        if calendar_name in calendars:
            self.calendar = calendars[calendar_name]
        else:
            log.info("Creating calendar %r in iCloud", calendar_name)
            self.calendar = principal.make_calendar(name=calendar_name)

    def local(self, iso: str) -> datetime:
        return datetime.fromisoformat(iso).replace(tzinfo=self.tz)

    def upsert(self, uid: str, title: str, start_iso: str, duration_minutes: int,
               location: str | None, description: str) -> None:
        ics = build_ics(uid, title, self.local(start_iso), duration_minutes, location,
                        description, self.alarm_minutes)
        # Same UID -> same resource URL, so re-running overwrites instead of duplicating.
        self.calendar.add_event(ics)

    def delete(self, uid: str) -> None:
        try:
            self.calendar.event_by_uid(uid).delete()
        except caldav.lib.error.NotFoundError:
            log.info("Event %s already gone from calendar", uid)


class DryRunCalendar:
    """Prints what would happen instead of touching iCloud."""

    def upsert(self, uid, title, start_iso, duration_minutes, location, description):
        print(f"  [calendar] ADD/UPDATE {start_iso} ({duration_minutes}m) {title}"
              + (f" @ {location}" if location else ""))

    def delete(self, uid):
        print(f"  [calendar] DELETE {uid}")
