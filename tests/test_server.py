import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer

import pytest

from wa_crm.config import Config
from wa_crm.server import Api, load_token, make_handler
from wa_crm.state import State

from .test_cloud import NOW, needs_collector, collector_db  # noqa: F401
from .test_pipeline import FakeCalendar


def analysis(contact_type, appointments=()):
    return {
        "contact_type": contact_type, "role": "buyer" if contact_type == "client" else None,
        "potential": "hot", "potential_reason": "Viewing booked", "summary": "s",
        "requirements": "3 rooms", "next_step": None, "properties": None,
        "appointments": list(appointments),
    }


@pytest.fixture
def api(tmp_path, collector_db):  # noqa: F811
    cfg = Config(timezone="Asia/Kuala_Lumpur", accounts={"whatsapp": None, "business": None},
                 source="cloud", cloud_db_path=str(collector_db),
                 state_path=str(tmp_path / "state.db"))
    calendar = FakeCalendar()
    return Api(cfg, State(cfg.state_path), lambda: calendar), calendar


@needs_collector
def test_pending_then_results_round_trip(api):
    api, calendar = api
    batch = api.pending(now=NOW)
    names = [c["name"] for c in batch["chats"]]
    assert sorted(names) == ["Lim PropNex", "Mr Tan (Mont Kiara)"]
    assert batch["remaining"] == 0
    assert batch["whatsapp_status"] == {"whatsapp": "connected", "business": "logged_out"}
    assert "confirmed" in batch["instructions"]
    assert "contact_type" in batch["result_schema"]["properties"]
    tan = next(c for c in batch["chats"] if c["name"].startswith("Mr Tan"))
    assert "===== NEW MESSAGES =====" in tan["transcript"]

    # A chat that's already in an open batch isn't handed out twice.
    assert api.pending(now=NOW)["chats"] == []

    lim = next(c for c in batch["chats"] if c["name"] == "Lim PropNex")
    appt = {"status": "confirmed", "title": "Viewing Mont Kiara", "start": "2026-10-03T15:00",
            "duration_minutes": 60, "location": None, "notes": None, "replaces_start": None}
    reply = api.results({"batch_id": batch["batch_id"], "results": [
        {"id": tan["id"], "analysis": analysis("client", [appt])},
        {"id": lim["id"], "analysis": analysis("agent")},
    ]}, now=NOW)

    assert reply["errors"] == [] and reply["unanswered"] == []
    [action] = reply["calendar"]
    assert (action["action"], action["title"], action["start"], action["end"]) == (
        "upsert", "[Client] Viewing Mont Kiara", "2026-10-03T15:00:00+08:00",
        "2026-10-03T16:00:00+08:00")
    assert reply["calendar_mode"] == "apple"
    rows = {r["name"]: r for r in reply["crm"]}
    assert rows["Mr Tan (Mont Kiara)"]["type"] == "Client"
    assert rows["Mr Tan (Mont Kiara)"]["next_appointment"] == "2026-10-03T15:00"
    assert rows["Lim PropNex"]["type"] == "Agent"
    assert rows["Lim PropNex"]["phone"] == "+60177777777"
    assert list(calendar.events.values())[0][1] == "2026-10-03T15:00"

    # Done: nothing new next time.
    assert api.pending(now=NOW + timedelta(hours=1))["chats"] == []


@needs_collector
def test_bad_analysis_is_reported_and_retried(api):
    api, _ = api
    batch = api.pending(now=NOW, limit=1)
    assert len(batch["chats"]) == 1 and batch["remaining"] == 1
    reply = api.results({"batch_id": batch["batch_id"], "results": [
        {"id": batch["chats"][0]["id"], "analysis": {"contact_type": "alien"}}]}, now=NOW)
    assert "does not match schema" in reply["errors"][0]["error"]
    assert reply["unanswered"] == ["1"]
    with pytest.raises(KeyError):
        api.results({"batch_id": "nope", "results": []})


@needs_collector
def test_http_requires_token(api, tmp_path):
    api, _ = api
    token = load_token(tmp_path, None)
    assert token == load_token(tmp_path, None)          # persisted
    server = HTTPServer(("127.0.0.1", 0), make_handler(api, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert json.load(urllib.request.urlopen(f"{base}/health")) == {"ok": True}
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(
                f"{base}/pending", headers={"Authorization": "Bearer wrong"}))
        assert e.value.code == 401
        ok = urllib.request.urlopen(urllib.request.Request(
            f"{base}/pending", headers={"Authorization": f"Bearer {token}"}))
        assert "batch_id" in json.load(ok)
    finally:
        server.shutdown()


@needs_collector
def test_google_mode_remembers_event_ids(tmp_path, collector_db):  # noqa: F811
    import sqlite3
    cfg = Config(timezone="Asia/Kuala_Lumpur", accounts={"whatsapp": None}, source="cloud",
                 cloud_db_path=str(collector_db), state_path=str(tmp_path / "state.db"))
    api = Api(cfg, State(cfg.state_path))           # no iCloud -> Google mode
    batch = api.pending(now=NOW)
    assert batch["calendar_mode"] == "google"
    tan = next(c for c in batch["chats"] if c["name"].startswith("Mr Tan"))
    appt = {"status": "confirmed", "title": "Viewing", "start": "2026-10-03T15:00",
            "duration_minutes": 60, "location": "Mont Kiara", "notes": None, "replaces_start": None}
    reply = api.results({"batch_id": batch["batch_id"], "results": [
        {"id": tan["id"], "analysis": analysis("client", [appt])}]}, now=NOW)
    [created] = reply["calendar"]
    assert created["event_id"] is None              # new: the Routine creates it
    api.calendar_ids({"ids": {created["uid"]: "gcal123"}})

    # A new message moves the viewing; the Routine is told which Google event to remove.
    db = sqlite3.connect(collector_db)
    db.execute("INSERT INTO messages VALUES ('whatsapp', '60123456789@s.whatsapp.net', 'x9', ?,"
               " 0, 'Tan', 'Can change to Sunday 11am?')", (int(NOW.timestamp()) + 3600,))
    db.commit()
    db.close()
    later = NOW + timedelta(hours=2)
    batch = api.pending(now=later)
    tan = next(c for c in batch["chats"] if c["name"].startswith("Mr Tan"))
    assert "2026-10-03T15:00 [Client] Viewing" in tan["transcript"]   # Claude sees the old time
    moved = dict(appt, start="2026-10-04T11:00", replaces_start="2026-10-03T15:00")
    reply = api.results({"batch_id": batch["batch_id"], "results": [
        {"id": tan["id"], "analysis": analysis("client", [moved])}]}, now=later)
    delete, upsert = reply["calendar"]
    assert (delete["action"], delete["event_id"]) == ("delete", "gcal123")
    assert (upsert["action"], upsert["start"]) == ("upsert", "2026-10-04T11:00:00+08:00")
