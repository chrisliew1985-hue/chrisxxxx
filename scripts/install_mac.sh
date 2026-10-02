#!/bin/bash
# Installs wa-crm on this Mac and schedules it to run every day.
#   ./scripts/install_mac.sh            # runs daily at 21:00
#   ./scripts/install_mac.sh 8 30       # runs daily at 08:30
set -euo pipefail

HOUR="${1:-21}"
MINUTE="${2:-0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME/.wa-crm"
VENV="$HOME_DIR/venv"
LABEL="com.wa-crm.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO/requirements.txt"

[ -f "$HOME_DIR/config.yaml" ] || cp "$REPO/config.example.yaml" "$HOME_DIR/config.yaml"
if [ ! -f "$HOME_DIR/.env" ]; then
  cp "$REPO/.env.example" "$HOME_DIR/.env"
  chmod 600 "$HOME_DIR/.env"
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>-m</string>
    <string>wa_crm</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key><string>$HOME_DIR/run.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/run.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

REAL_PY="$("$VENV/bin/python" -c 'import os,sys; print(os.path.realpath(sys.executable))')"
cat <<MSG

Installed. wa-crm will run every day at $(printf '%02d:%02d' "$HOUR" "$MINUTE").

Next steps:
  1. Fill in $HOME_DIR/.env and check $HOME_DIR/config.yaml
  2. Give Python Full Disk Access so it can read WhatsApp's chat database:
       System Settings > Privacy & Security > Full Disk Access > + >
       press Cmd+Shift+G and paste:  $REAL_PY
     (also add Terminal if you run it by hand)
  3. Try it without changing anything:
       cd "$REPO" && "$VENV/bin/python" -m wa_crm run --dry-run
  4. Run it for real now (otherwise it waits for the schedule):
       launchctl kickstart "gui/$(id -u)/$LABEL"
  Logs: $HOME_DIR/run.log
MSG
