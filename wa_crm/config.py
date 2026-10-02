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
    accounts: dict[str, str]                 # account label -> ChatStorage.sqlite path (mac)
    source: str = "mac"                      # mac = desktop apps, cloud = collector service
    cloud_db_path: str = "/data/messages.db"
    run_at: str = "21:00"                    # daily run time for `serve` (local time)
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


ENV_PREFIX = "WA_CRM_"
TEXT_FIELDS = {"timezone", "source", "cloud_db_path", "run_at", "calendar_name", "crm_backend",
               "crm_csv_path", "state_path", "model"}


def load_config(path: str | Path | None = None) -> Config:
    """Read config.yaml (optional in the cloud), then apply WA_CRM_<SETTING> env overrides.

    e.g. WA_CRM_TIMEZONE=Asia/Kuala_Lumpur, WA_CRM_SOURCE=cloud, WA_CRM_RUN_AT=21:00.
    WA_ACCOUNTS=whatsapp,business sets the account list.
    """
    path = Path(path or os.environ.get("WA_CRM_CONFIG") or CONFIG_DIR / "config.yaml").expanduser()
    has_env = any(k.startswith(ENV_PREFIX) and k != "WA_CRM_CONFIG" for k in os.environ)
    if not path.exists() and not has_env:
        raise SystemExit(f"Config not found at {path}. Copy config.example.yaml there first.")
    raw = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}

    for key, value in os.environ.items():
        if key.startswith(ENV_PREFIX) and key != "WA_CRM_CONFIG":
            name = key[len(ENV_PREFIX):].lower()
            raw[name] = value if name in TEXT_FIELDS else (yaml.safe_load(value) if value else None)

    if isinstance(raw.get("run_at"), int):   # YAML reads an unquoted 21:00 as 1260 minutes
        raw["run_at"] = f"{raw['run_at'] // 60:02d}:{raw['run_at'] % 60:02d}"

    account_names = raw.pop("accounts", None)
    if os.environ.get("WA_ACCOUNTS"):
        account_names = {a.strip(): None for a in os.environ["WA_ACCOUNTS"].split(",") if a.strip()}
    accounts = {}
    for name, value in (account_names or {"whatsapp": None, "business": None}).items():
        accounts[name] = value or DEFAULT_DB_PATHS.get(name)
        if not accounts[name] and raw.get("source", "mac") == "mac":
            raise SystemExit(f"No database path given for WhatsApp account '{name}'.")

    env = load_env_file(path.parent / ".env")
    known = set(Config.__dataclass_fields__) - {"accounts", "env"}
    unknown = set(raw) - known
    if unknown:
        raise SystemExit(f"Unknown config keys: {', '.join(sorted(unknown))}")
    if "timezone" not in raw:
        raise SystemExit("Set 'timezone' in config.yaml or WA_CRM_TIMEZONE, e.g. Asia/Kuala_Lumpur")
    if raw.get("source", "mac") not in ("mac", "cloud"):
        raise SystemExit("source must be 'mac' or 'cloud'")
    return Config(accounts=accounts, env=env, **raw)
