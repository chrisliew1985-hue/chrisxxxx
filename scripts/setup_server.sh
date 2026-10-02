#!/bin/bash
# One-time setup on an Ubuntu/Debian server (Hostinger VPS, Oracle Cloud Always Free, ...).
#   curl -fsSL https://raw.githubusercontent.com/chrisliew1985-hue/chrisxxxx/claude/relaxed-ride-lkxwvs/scripts/setup_server.sh | bash
# It asks for your settings and passwords here on the server, so they never
# go into GitHub or a chat.
set -euo pipefail

REPO_URL="https://github.com/chrisliew1985-hue/chrisxxxx.git"
BRANCH="${BRANCH:-claude/relaxed-ride-lkxwvs}"
DIR="$HOME/wa-crm"

# Works both as root (Hostinger) and as a normal sudo user (Oracle "ubuntu").
if [ "$(id -u)" -eq 0 ]; then sudo() { "$@"; }; fi

echo "== Checking web port 443 is free (port 80 is left alone for other apps) =="
# Anything other than our own Caddy container listening on 443 (Docker-published ports
# show up as docker-proxy in ss, so those are checked via `docker ps` instead).
others_443="$( {
  ss -ltnpH 2>/dev/null | awk '$4 ~ /[:.]443$/' | grep -v docker-proxy
  docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E ':443->' | grep -v '^wa-crm-caddy'
} || true )"
HTTPS_MODE="own"
if [ -n "$others_443" ]; then
  if echo "$others_443" | grep -q caddy; then
    # Another app's Caddy (e.g. a WA blast tool) already serves 80/443: share it.
    HTTPS_MODE="shared"
    echo "Port 443 is used by another app's Caddy; wa-crm will be added to it (that app keeps working)."
  else
    echo "Port 443 is already used by another app on this server:"
    echo "$others_443"
    echo "Nothing was changed. Send this output to get a setup that shares the port."
    exit 1
  fi
fi

echo "== Installing Docker =="
if ! command -v docker >/dev/null; then
  # Docker's script can lag behind brand-new Ubuntu releases; fall back to Ubuntu's own packages.
  curl -fsSL https://get.docker.com | sudo sh \
    || { sudo apt-get update -qq && sudo apt-get install -y -qq docker.io docker-compose-v2; }
  sudo systemctl enable --now docker
  [ "$(id -u)" -eq 0 ] || sudo usermod -aG docker "$USER"
fi

if ! sudo docker compose version >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-v2 \
    || sudo apt-get install -y -qq docker-compose-plugin
fi

echo "== Opening web port 443 on this machine's firewall =="
# Oracle's Ubuntu images block everything except SSH by default; ufw is common elsewhere.
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 443/tcp
fi
for port in 443; do
  if ! sudo iptables -C INPUT -m state --state NEW -p tcp --dport $port -j ACCEPT 2>/dev/null; then
    # Insert just before Oracle's catch-all REJECT rule (or at the top if there isn't one).
    pos="$(sudo iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')"
    sudo iptables -I INPUT "${pos:-1}" -m state --state NEW -p tcp --dport $port -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi
command -v git >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq git; }

echo "== Downloading wa-crm =="
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone -b "$BRANCH" "$REPO_URL" "$DIR"; fi
cd "$DIR"

# A half-written .env from an interrupted run is redone.
if [ -f .env ] && ! grep -Eq '^WA_PHONE_BUSINESS=[0-9]{8,15}$' .env; then rm -f .env; fi
if [ ! -f .env ]; then
  echo "== Settings (stored only in $DIR/.env on this server) =="
  IP="$(curl -fsS https://api.ipify.org)"
  # Read answers from the keyboard, not from the piped script (curl ... | bash).
  ask_number() {   # keeps asking until it gets digits only, e.g. 60123456789
    local n
    while true; do
      read -rp "$1" n </dev/tty
      n="${n//[^0-9]/}"
      [[ "$n" == 0* ]] && n="6$n"          # Malaysian 01x... -> 601x...
      [[ "$n" =~ ^[0-9]{8,15}$ ]] && { echo "$n"; return; }
      echo "  Please enter digits only, with country code, e.g. 60123456789" >/dev/tty
    done
  }
  PHONE_WA="$(ask_number "First WhatsApp number, e.g. 60123456789: ")"
  PHONE_BIZ="$(ask_number "Second WhatsApp number, e.g. 60198765432: ")"
  # Calendar: Google by default (written by the Claude Routine). Run with CALENDAR=apple
  # to have this server write Apple Calendar instead (asks for an iCloud app password).
  APPLE_ID=""; APPLE_PW=""
  if [ "${CALENDAR:-google}" = "apple" ]; then
    read -rp "Apple ID email for iCloud Calendar: " APPLE_ID </dev/tty
    read -rsp "iCloud app-specific password (hidden): " APPLE_PW </dev/tty; echo
  fi
  cat > .env <<ENV
DOMAIN=${IP//./-}.sslip.io
WA_CRM_TIMEZONE=Asia/Kuala_Lumpur
WA_ACCOUNTS=whatsapp,business
WA_PHONE_WHATSAPP=${PHONE_WA}
WA_PHONE_BUSINESS=${PHONE_BIZ}
ICLOUD_APPLE_ID=${APPLE_ID}
ICLOUD_APP_PASSWORD=${APPLE_PW}
ENV
  chmod 600 .env
fi

echo "== Starting =="
if [ "$HTTPS_MODE" = "own" ]; then
  sudo docker compose --profile own-https up -d --build --remove-orphans
else
  sudo docker compose rm -sf caddy >/dev/null 2>&1 || true   # a failed earlier attempt
  sudo docker compose up -d --build --remove-orphans
  bash "$DIR/scripts/share_caddy.sh"
fi

DOMAIN="$(grep '^DOMAIN=' .env | cut -d= -f2)"
for _ in $(seq 1 30); do
  sudo test -f data/server_token && break
  sleep 2
done
cat <<MSG

==================================================================
 Running. Now link both WhatsApps:
   sudo docker compose -f $DIR/docker-compose.yml logs -f wa-crm
 Look for "PAIRING CODE", then on each phone:
   Settings > Linked devices > Link a device > Link with phone number instead

 For the Claude Routine (enter these in your Claude environment settings,
 never paste them into a chat):
   WA_SERVER_URL   = https://$DOMAIN
   WA_SERVER_TOKEN = run:  sudo cat $DIR/data/server_token
   Allowed domain  = $DOMAIN
==================================================================
MSG
