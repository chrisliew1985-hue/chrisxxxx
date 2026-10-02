#!/bin/bash
# Serve the wa-crm API through a Caddy that another app on this server already runs
# (e.g. a WA blast tool holding ports 80/443), instead of starting a second Caddy.
#
# It only APPENDS one site block for the wa-crm domain to that Caddy's Caddyfile:
#   - backs the file up first
#   - validates the new config inside the running Caddy, and restores the backup if invalid
#   - reloads Caddy gracefully (no restart, the other app keeps running)
#
#   bash /root/wa-crm/scripts/share_caddy.sh
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then sudo() { command sudo "$@"; }; else sudo() { "$@"; }; fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="$(grep '^DOMAIN=' "$DIR/.env" | cut -d= -f2)"
UPSTREAM="127.0.0.1:8090"     # wa-crm API, published on localhost only (docker-compose.yml)
MARK="# wa-crm API (added by wa-crm share_caddy.sh)"

# The other app's Caddy: a running caddy container that isn't ours.
CADDY="${CADDY_CONTAINER:-$(sudo docker ps --format '{{.Names}} {{.Image}}' \
  | awk '$2 ~ /(^|\/)caddy(:|$)/ && $1 !~ /^wa-crm-/ {print $1; exit}')}"
[ -n "$CADDY" ] || { echo "No other Caddy container found."; exit 1; }

NET="$(sudo docker inspect -f '{{.HostConfig.NetworkMode}}' "$CADDY")"
[ "$NET" = "host" ] || {
  echo "$CADDY is not on the host network ($NET); it can't reach $UPSTREAM. Nothing changed."
  exit 1
}

# Host path of its Caddyfile (mounted as a file, or as the /etc/caddy folder).
FILE="$(sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$CADDY")"
if [ -z "$FILE" ]; then
  D="$(sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy"}}{{.Source}}{{end}}{{end}}' "$CADDY")"
  [ -n "$D" ] && FILE="$D/Caddyfile"
fi
[ -n "$FILE" ] && sudo test -f "$FILE" || {
  echo "Couldn't find $CADDY's Caddyfile on this server. Nothing changed."
  exit 1
}
echo "Using $CADDY with config $FILE"

if sudo grep -qF "$MARK" "$FILE"; then
  echo "Already added earlier."
else
  BACKUP="$FILE.bak-wa-crm-$(date +%Y%m%d%H%M%S)"
  sudo cp -p "$FILE" "$BACKUP"
  echo "Backup saved: $BACKUP"
  # Append (not rewrite) so a single-file bind mount keeps working.
  printf '\n%s\n%s {\n\treverse_proxy %s\n}\n' "$MARK" "$DOMAIN" "$UPSTREAM" | sudo tee -a "$FILE" >/dev/null
  if ! sudo docker exec "$CADDY" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    sudo docker exec "$CADDY" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile || true
    sudo sh -c "cat '$BACKUP' > '$FILE'"
    echo "The new config was not valid, so the original was restored. Nothing changed."
    exit 1
  fi
fi

sudo docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "Done: https://$DOMAIN now reaches wa-crm through $CADDY (the first request may take"
echo "~30 seconds while the certificate is issued)."
