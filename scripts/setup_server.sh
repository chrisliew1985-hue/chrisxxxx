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

echo "== Checking web ports 80/443 are free =="
if command -v ss >/dev/null && ss -ltnH '( sport = :80 or sport = :443 )' | grep -q .; then
  if ! sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -q caddy; then
    echo "Something else (probably a website) is already using port 80 or 443 on this server:"
    ss -ltnp '( sport = :80 or sport = :443 )' || true
    echo "Stop it, or ask for the 'shared web server' setup instead. Nothing was changed."
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

echo "== Opening web ports 80/443 on this machine's firewall =="
# Oracle's Ubuntu images block everything except SSH by default; ufw is common elsewhere.
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
fi
for port in 80 443; do
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
if [ -f .env ] && ! grep -q '^ICLOUD_APP_PASSWORD=.' .env; then rm -f .env; fi
if [ ! -f .env ]; then
  echo "== Settings (stored only in $DIR/.env on this server) =="
  IP="$(curl -fsS https://api.ipify.org)"
  # Read answers from the keyboard, not from the piped script (curl ... | bash).
  read -rp "Apple ID email for iCloud Calendar: " APPLE_ID </dev/tty
  read -rsp "iCloud app-specific password (hidden): " APPLE_PW </dev/tty; echo
  read -rp "First WhatsApp number, e.g. 60123456789: " PHONE_WA </dev/tty
  read -rp "Second WhatsApp number, e.g. 60198765432: " PHONE_BIZ </dev/tty
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
