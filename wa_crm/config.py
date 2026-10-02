"""Configuration: non-secret settings in config.yaml, secrets in .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .whatsapp import DEFAULT_DB_PATHS

CONFIG_DIR = Path("~/.wa-crm").expanduser()


@dataclass
class Config:
    timezone: str
    accounts: dict[str, str]                 # account label -> ChatStorage.sqlite path
    include_groups: bool = False
    first_run_lookback_days: int = 3
    context_days: int = 30
    calendar_name: str = "WhatsApp Appointments"
    alarm_minutes: int | None = 60
    crm_backend: str = "notion"              # notion | csv
    crm_csv_path: str = "~/.wa-crm/contacts.csv"
    crm_include_personal: bool = False
    state_path: str = "~/.wa-crm/state.db"
    model: str = "claude-opus-5-5"
    env: dict[str, str] = field(default_factory=dict)

    def secret(self, name: str, required: bool = True) -> str | None:
        value = os.environ.get(name) or self.env.get(name)
        if required and not value:
            raise SystemExit(f"Missing {name}. Put it in ~/.wa-crm/.env (see .env.example).")
        return value


def load_env_file(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path).expanduser() if path else CONFIG_DIR / "config.yaml"
    if not path.exists():
        raise SystemExit(f"Config not found at {path}. Copy config.example.yaml there first.")
    raw = yaml.safe_load(path.read_text()) or {}

    accounts = {}
    for name, value in (raw.pop("accounts", None) or {"whatsapp": None, "business": None}).items():
        accounts[name] = value or DEFAULT_DB_PATHS.get(name)
        if not accounts[name]:
            raise SystemExit(f"No database path given for WhatsApp account '{name}'.")

    env = load_env_file(path.parent / ".env")
    known = set(Config.__dataclass_fields__) - {"accounts", "env"}
    unknown = set(raw) - known
    if unknown:
        raise SystemExit(f"Unknown config keys: {', '.join(sorted(unknown))}")
    if "timezone" not in raw:
        raise SystemExit("config.yaml must set 'timezone', e.g. Asia/Kuala_Lumpur")
    return Config(accounts=accounts, env=env, **raw)
