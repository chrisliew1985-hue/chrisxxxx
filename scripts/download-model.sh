#!/usr/bin/env bash
#
# Download a starter checkpoint into ComfyUI's models/checkpoints directory.
# ComfyUI ships with no weights, so it cannot generate anything until at least
# one checkpoint is present.
#
# Usage:
#   ./scripts/download-model.sh              # list the catalog
#   ./scripts/download-model.sh sd15         # download by name
#   ./scripts/download-model.sh <url> [file] # download an arbitrary URL
#
# Environment overrides:
#   COMFY_DIR  ComfyUI install directory.  (default: $HOME/ComfyUI)
#   HF_TOKEN   Hugging Face token, for gated repos.

set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
DEST="$COMFY_DIR/models/checkpoints"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

HF="https://huggingface.co"

# name|approx size|filename|url
CATALOG="\
sd15|2.0GB|v1-5-pruned-emaonly-fp16.safetensors|$HF/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors
sdxl-turbo|6.9GB|sd_xl_turbo_1.0_fp16.safetensors|$HF/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors
sdxl|6.9GB|sd_xl_base_1.0.safetensors|$HF/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"

usage() {
  echo "Usage: $0 <name|url> [filename]"
  echo
  echo "Catalog:"
  printf '%s\n' "$CATALOG" | while IFS='|' read -r name size file _; do
    printf '  %-12s %-8s %s\n' "$name" "$size" "$file"
  done
  echo
  echo "sd15 is the smallest and the only one that is practical on CPU."
}

[ $# -ge 1 ] || { usage; exit 0; }

ARG="$1"
case "$ARG" in
  http://*|https://*)
    URL="$ARG"
    FILE="${2:-$(basename "${URL%%\?*}")}"
    ;;
  *)
    ENTRY=$(printf '%s\n' "$CATALOG" | grep "^$ARG|" || true)
    [ -n "$ENTRY" ] || { echo "unknown model '$ARG'" >&2; echo >&2; usage >&2; exit 1; }
    FILE=$(printf '%s' "$ENTRY" | cut -d'|' -f3)
    URL=$(printf '%s' "$ENTRY" | cut -d'|' -f4)
    ;;
esac

mkdir -p "$DEST"
OUT="$DEST/$FILE"

if [ -f "$OUT" ]; then
  log "$FILE already present, skipping"
  exit 0
fi

AUTH=()
[ -n "${HF_TOKEN:-}" ] && AUTH=(--header "Authorization: Bearer $HF_TOKEN")

log "Downloading $FILE -> $DEST"
# --continue-at resumes a partial file; download to .part so an interrupted
# transfer is never mistaken for a complete checkpoint.
curl -fL --progress-bar --continue-at - ${AUTH[@]+"${AUTH[@]}"} -o "$OUT.part" "$URL" \
  || die "download failed (is huggingface.co reachable from this network?)"
mv "$OUT.part" "$OUT"

log "Saved $(du -h "$OUT" | cut -f1) to $OUT"
