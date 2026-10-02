import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import anthropic
import httpx2
import pytest

from wa_crm.calendar_icloud import build_ics, event_uid
from wa_crm.config import Config
from wa_crm.crm import ContactRecord, CsvCRM
from wa_crm.extract import Appointment, ChatAnalysis, Extractor
from wa_crm.main import Runner
from wa_crm.state import State
from wa_crm.whatsapp import APPLE_EPOCH_OFFSET, read_chats

NOW = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)


def apple(dt):
    return dt.timestamp() - APPLE_EPOCH_OFFSET


def make_whatsapp_db(path, chats):
    """chats: list of (jid, name, session_type, [(datetime, from_me, text, msg_type)])"""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT,
            ZPARTNERNAME TEXT, ZSESSIONTYPE INTEGER);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER,
            ZISFROMME INTEGER, ZMESSAGEDATE REAL, ZTEXT TEXT, ZMESSAGETYPE INTEGER,
            ZPUSHNAME TEXT);
    """)
    for pk, (jid, name, stype, msgs) in enumerate(chats, 1):
        db.execute("INSERT INTO ZWACHATSESSION VALUES (?,?,?,?)", (pk, jid, name, stype))
        for ts, from_me, text, mtype in msgs:
            db.execute("INSERT INTO ZWAMESSAGE (ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT,"
                       " ZMESSAGETYPE) VALUES (?,?,?,?,?)", (pk, from_me, apple(ts), text, mtype))
    db.commit()
    db.close()


@pytest.fixture
def wa_db(tmp_path):
    path = tmp_path / "ChatStorage.sqlite"
    make_whatsapp_db(path, [
        ("60123456789@s.whatsapp.net", "Mr Tan", 0, [
            (NOW - timedelta(days=10), 0, "Looking for 3 room condo in Mont Kiara, RM1.2m", 0),
            (NOW - timedelta(hours=5), 0, "Can view Saturday 3pm?", 0),
            (NOW - timedelta(hours=4), 1, "Ok confirmed Sat 3pm, see you", 0),
            (NOW - timedelta(hours=3), 0, None, 1),  # photo
        ]),
        ("60199999999@s.whatsapp.net", "Old contact", 0, [
            (NOW - timedelta(days=20), 0, "hi", 0),
        ]),
        ("1203630@g.us", "KL Agents Co-broke", 1, [
            (NOW - timedelta(hours=1), 0, "New listing", 0),
        ]),
    ])
    return path


def test_read_chats_only_active_and_skips_groups(wa_db):
    chats = read_chats("whatsapp", wa_db, active_since=NOW - timedelta(days=1),
                       history_since=NOW - timedelta(days=30))
    assert [c.name for c in chats] == ["Mr Tan"]
    tan = chats[0]
    assert tan.phone == "+60123456789"
    assert [m.text for m in tan.messages] == [
        "Looking for 3 room condo in Mont Kiara, RM1.2m",
        "Can view Saturday 3pm?",
        "Ok confirmed Sat 3pm, see you",
        "[attachment]",
    ]
    assert tan.messages[2].sender == "Me"


def test_read_chats_includes_groups_when_asked(wa_db):
    chats = read_chats("whatsapp", wa_db, NOW - timedelta(days=1), NOW - timedelta(days=30),
                       include_groups=True)
    assert {c.name for c in chats} == {"Mr Tan", "KL Agents Co-broke"}


def test_missing_db_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Full Disk Access"):
        read_chats("business", tmp_path / "nope.sqlite", NOW, NOW)


# ------------------------------------------------------------------ runner


class FakeExtractor:
    def __init__(self, analyses):
        self.analyses = list(analyses)
        self.calls = []

    def analyze(self, chat, new_since, known):
        self.calls.append((chat.name, new_since, known))
        return self.analyses.pop(0)


class FakeCalendar:
    def __init__(self):
        self.events, self.deleted = {}, []

    def upsert(self, uid, title, start_iso, duration, location, description):
        self.events[uid] = (title, start_iso, location)

    def delete(self, uid):
        self.deleted.append(uid)
        self.events.pop(uid, None)


class FakeCRM:
    def __init__(self):
        self.records = []

    def upsert(self, rec):
        self.records.append(rec)
        return "created"


def analysis(contact_type="client", appointments=(), potential="hot"):
    return ChatAnalysis(
        contact_type=contact_type,
        role={"client": "buyer", "owner": "landlord"}.get(contact_type),
        potential=potential, potential_reason="Viewing booked, budget clear",
        summary="Buyer for Mont Kiara condo", requirements="3 rooms, RM1.2m",
        next_step="Prepare viewing", appointments=list(appointments))


def make_runner(tmp_path, wa_db, analyses):
    cfg = Config(timezone="Asia/Kuala_Lumpur", accounts={"whatsapp": str(wa_db)},
                 state_path=str(tmp_path / "state.db"))
    ext, cal, crm = FakeExtractor(analyses), FakeCalendar(), FakeCRM()
    return Runner(cfg, ext, cal, crm, State(cfg.state_path)), ext, cal, crm


def test_confirmed_appointment_goes_to_calendar_and_crm(tmp_path, wa_db):
    appt = Appointment(status="confirmed", title="Viewing Mont Kiara w/ Mr Tan",
                       start="2026-10-03T15:00", duration_minutes=60, location="Mont Kiara")
    tentative = Appointment(status="tentative", title="Maybe 2nd viewing",
                            start="2026-10-05T11:00", duration_minutes=60)
    runner, ext, cal, crm = make_runner(tmp_path, wa_db, [analysis(appointments=[appt, tentative])])
    stats = runner.run(now=NOW)

    uid = event_uid("whatsapp", "60123456789@s.whatsapp.net", "2026-10-03T15:00")
    assert cal.events == {uid: ("[Client] Viewing Mont Kiara w/ Mr Tan", "2026-10-03T15:00",
                                "Mont Kiara")}
    rec = crm.records[0]
    assert (rec.type, rec.potential, rec.role) == ("Client", "Hot", "Buyer")
    assert rec.phone == "+60123456789"
    assert rec.next_appointment == "2026-10-03T15:00"
    assert stats == {"chats": 1, "events_added": 1, "events_removed": 0, "contacts": 1,
                     "errors": 0}

    # Second run with no new messages does nothing.
    runner.run(now=NOW + timedelta(hours=1))
    assert len(ext.calls) == 1


def test_reschedule_replaces_old_event(tmp_path, wa_db):
    first = Appointment(status="confirmed", title="Viewing", start="2026-10-03T15:00",
                        duration_minutes=60)
    runner, ext, cal, crm = make_runner(tmp_path, wa_db, [analysis(appointments=[first])])
    runner.run(now=NOW)

    # New message arrives, appointment moved to Sunday.
    db = sqlite3.connect(wa_db)
    db.execute("INSERT INTO ZWAMESSAGE (ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT,"
               " ZMESSAGETYPE) VALUES (1, 0, ?, 'Can change to Sunday 11am?', 0)",
               (apple(NOW + timedelta(hours=2)),))
    db.commit()
    db.close()
    moved = Appointment(status="confirmed", title="Viewing", start="2026-10-04T11:00",
                        duration_minutes=60, replaces_start="2026-10-03T15:00")
    ext.analyses.append(analysis(appointments=[moved]))
    runner.run(now=NOW + timedelta(hours=3))

    # Claude was told about the existing appointment.
    assert ext.calls[1][2][0]["start"] == "2026-10-03T15:00"
    old_uid = event_uid("whatsapp", "60123456789@s.whatsapp.net", "2026-10-03T15:00")
    assert cal.deleted == [old_uid]
    assert [v[1] for v in cal.events.values()] == ["2026-10-04T11:00"]
    assert crm.records[-1].next_appointment == "2026-10-04T11:00"


def test_personal_contacts_stay_out_of_crm(tmp_path, wa_db):
    runner, _, _, crm = make_runner(tmp_path, wa_db, [analysis("personal", potential="none")])
    runner.run(now=NOW)
    assert crm.records == []


def test_agent_is_labelled_agent(tmp_path, wa_db):
    runner, _, _, crm = make_runner(tmp_path, wa_db, [analysis("agent", potential="warm")])
    runner.run(now=NOW)
    assert (crm.records[0].type, crm.records[0].role) == ("Agent", None)


def test_owner_is_labelled_owner(tmp_path, wa_db):
    appt = Appointment(status="confirmed", title="Handover keys", start="2026-10-04T10:00",
                       duration_minutes=30)
    runner, _, cal, crm = make_runner(tmp_path, wa_db, [analysis("owner", [appt], "warm")])
    runner.run(now=NOW)
    assert (crm.records[0].type, crm.records[0].role) == ("Owner", "Landlord")
    assert [v[0] for v in cal.events.values()] == ["[Owner] Handover keys"]


def test_failed_chat_is_retried_next_run(tmp_path, wa_db):
    class Boom(FakeExtractor):
        def analyze(self, chat, new_since, known):
            if not self.calls:
                self.calls.append(chat.name)
                raise anthropic.APIConnectionError(request=httpx2.Request("POST", "http://x"))
            return super().analyze(chat, new_since, known)

    cfg = Config(timezone="Asia/Kuala_Lumpur", accounts={"whatsapp": str(wa_db)},
                 state_path=str(tmp_path / "state.db"))
    ext = Boom([analysis()])
    runner = Runner(cfg, ext, FakeCalendar(), FakeCRM(), State(cfg.state_path))
    assert runner.run(now=NOW)["errors"] == 1
    assert runner.state.account_watermark("whatsapp") is None
    runner.run(now=NOW + timedelta(hours=1))
    assert len(ext.calls) == 2


# ------------------------------------------------------------------ pieces


def test_ics_has_uid_alarm_and_local_time():
    from zoneinfo import ZoneInfo
    ics = build_ics("abc@wa-crm", "Viewing", datetime(2026, 10, 3, 15, 0,
                    tzinfo=ZoneInfo("Asia/Kuala_Lumpur")), 45, "Mont Kiara", "notes", 60)
    assert "UID:abc@wa-crm" in ics
    assert "DTSTART;TZID=Asia/Kuala_Lumpur:20261003T150000" in ics
    assert "DTEND;TZID=Asia/Kuala_Lumpur:20261003T154500" in ics
    assert "BEGIN:VALARM" in ics and "TRIGGER:-PT1H" in ics


def test_csv_crm_upserts_and_merges_accounts(tmp_path):
    crm = CsvCRM(tmp_path / "contacts.csv")
    rec = ContactRecord("1@s.whatsapp.net", "Mr Tan", "+1", "Client", "Buyer", "Warm", "r", "s",
                        "3 rooms", None, "2026-10-01", ["whatsapp"], None)
    assert crm.upsert(rec) == "created"
    rec.accounts, rec.potential, rec.requirements = ["business"], "Hot", None
    assert crm.upsert(rec) == "updated"
    rows = list(csv.DictReader((tmp_path / "contacts.csv").open()))
    assert len(rows) == 1
    assert rows[0]["potential"] == "Hot"
    assert rows[0]["accounts"] == "business;whatsapp"
    assert rows[0]["requirements"] == "3 rooms"   # kept from earlier run


def test_extractor_sends_valid_request_and_parses_response(wa_db):
    captured = {}
    result = analysis(appointments=[Appointment(status="confirmed", title="Viewing",
                                                start="2026-10-03T15:00", duration_minutes=60)])

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["beta"] = request.headers.get("anthropic-beta")
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": result.model_dump_json()}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    client = anthropic.Anthropic(api_key="test",
                                 http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    chat = read_chats("whatsapp", wa_db, NOW - timedelta(days=1), NOW - timedelta(days=30))[0]
    out = Extractor("Asia/Kuala_Lumpur", client=client).analyze(
        chat, NOW - timedelta(hours=6), [{"start": "2026-10-01T10:00", "title": "Old"}])

    assert out == result
    body = captured["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in captured["beta"]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    prompt = body["messages"][0]["content"]
    assert "===== NEW MESSAGES =====" in prompt
    assert prompt.index("Looking for 3 room") < prompt.index("NEW MESSAGES") < prompt.index("Can view")
    assert "- 2026-10-01T10:00 Old" in prompt
