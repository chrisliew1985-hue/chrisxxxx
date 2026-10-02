#!/bin/bash
# One-time setup on a fresh Ubuntu server (e.g. Oracle Cloud Always Free).
#   curl -fsSL https://raw.githubusercontent.com/chrisliew1985-hue/chrisxxxx/claude/relaxed-ride-lkxwvs/scripts/setup_server.sh | bash
# It asks for your settings and passwords here on the server, so they never
# go into GitHub or a chat.
set -euo pipefail

REPO_URL="https://github.com/chrisliew1985-hue/chrisxxxx.git"
BRANCH="${BRANCH:-claude/relaxed-ride-lkxwvs}"
DIR="$HOME/wa-crm"

echo "== Installing Docker =="
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "== Opening web ports 80/443 on this machine's firewall =="
# Oracle's Ubuntu images block everything except SSH by default.
for port in 80 443; do
  if ! sudo iptables -C INPUT -m state --state NEW -p tcp --dport $port -j ACCEPT 2>/dev/null; then
    # Insert just before Oracle's catch-all REJECT rule (or at the top if there isn't one).
    pos="$(sudo iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')"
    sudo iptables -I INPUT "${pos:-1}" -m state --state NEW -p tcp --dport $port -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi

echo "== Downloading wa-crm =="
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone -b "$BRANCH" "$REPO_URL" "$DIR"; fi
cd "$DIR"

if [ ! -f .env ]; then
  echo "== Settings (stored only in $DIR/.env on this server) =="
  IP="$(curl -fsS https://api.ipify.org)"
  read -rp "Apple ID email for iCloud Calendar: " APPLE_ID
  read -rsp "iCloud app-specific password (hidden): " APPLE_PW; echo
  read -rp "Regular WhatsApp number, e.g. 60123456789: " PHONE_WA
  read -rp "WhatsApp Business number, e.g. 60198765432: " PHONE_BIZ
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
sudo docker compose up -d --build

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
