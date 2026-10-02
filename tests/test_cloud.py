import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wa_crm import cloud_store
from wa_crm.config import load_config
from wa_crm.main import next_run

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)

needs_collector = pytest.mark.skipif(
    not shutil.which("node") or not (ROOT / "collector/node_modules").exists(),
    reason="run `npm ci` in collector/ first")


@pytest.fixture
def collector_db(tmp_path):
    subprocess.run(
        ["node", "--disable-warning=ExperimentalWarning", "fixture.js", str(int(NOW.timestamp()))],
        cwd=ROOT / "collector", env={**os.environ, "DATA_DIR": str(tmp_path)}, check=True)
    return tmp_path / "messages.db"


@needs_collector
def test_collector_output_is_readable(collector_db):
    chats = cloud_store.read_chats("whatsapp", collector_db, NOW - timedelta(days=1),
                                   NOW - timedelta(days=30))
    by_name = {c.name: c for c in chats}
    assert set(by_name) == {"Mr Tan (Mont Kiara)", "Lim PropNex"}

    tan = by_name["Mr Tan (Mont Kiara)"]
    assert tan.phone == "+60123456789"
    # Older context included, reactions + duplicate deliveries dropped.
    assert [(m.sender, m.text) for m in tan.messages] == [
        ("Tan", "Looking for 3 room condo, RM1.2m"),
        ("Tan", "Can view Saturday 3pm?"),
        ("Me", "Ok confirmed Sat 3pm"),
    ]

    # @lid contact resolved to a phone number, and later messages follow the mapping.
    lim = by_name["Lim PropNex"]
    assert lim.phone == "+60177777777"
    assert len(lim.messages) == 2


@needs_collector
def test_groups_optional_and_status(collector_db):
    chats = cloud_store.read_chats("whatsapp", collector_db, NOW - timedelta(days=1),
                                   NOW - timedelta(days=30), include_groups=True)
    group = next(c for c in chats if c.is_group)
    assert group.name == "KL Agents Co-broke"
    assert group.messages[0].sender == "Agent Wong"

    status = cloud_store.account_status(collector_db)
    assert status["whatsapp"]["state"] == "connected"
    assert status["business"]["state"] == "logged_out"


def test_next_run_is_today_or_tomorrow():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Kuala_Lumpur")   # NOW is 21:00 local
    assert next_run(NOW, "21:30", tz).isoformat() == "2026-10-02T21:30:00+08:00"
    assert next_run(NOW, "08:00", tz).isoformat() == "2026-10-03T08:00:00+08:00"


def test_config_from_env_only(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_CRM_CONFIG", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("WA_CRM_TIMEZONE", "Asia/Kuala_Lumpur")
    monkeypatch.setenv("WA_CRM_SOURCE", "cloud")
    monkeypatch.setenv("WA_CRM_RUN_AT", "21:00")
    monkeypatch.setenv("WA_CRM_INCLUDE_GROUPS", "true")
    monkeypatch.setenv("WA_ACCOUNTS", "whatsapp,business")
    cfg = load_config()
    assert (cfg.source, cfg.run_at, cfg.include_groups) == ("cloud", "21:00", True)
    assert list(cfg.accounts) == ["whatsapp", "business"]


def test_unquoted_time_in_yaml(tmp_path):
    (tmp_path / "c.yaml").write_text("timezone: Asia/Kuala_Lumpur\nrun_at: 21:00\n")
    assert load_config(tmp_path / "c.yaml").run_at == "21:00"
