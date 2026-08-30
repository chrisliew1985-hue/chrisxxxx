#!/usr/bin/env bash
#
# Start the ComfyUI server.
#
# Usage:
#   ./scripts/run.sh                 # listen on 127.0.0.1:8188
#   ./scripts/run.sh --listen 0.0.0.0
#   COMFY_PORT=9000 ./scripts/run.sh
#
# Any extra arguments are forwarded to ComfyUI's main.py verbatim.
#
# Environment overrides:
#   COMFY_DIR   ComfyUI install directory.  (default: $HOME/ComfyUI)
#   COMFY_HOST  Address to bind.            (default: 127.0.0.1)
#   COMFY_PORT  Port to bind.               (default: 8188)
#   COMFY_ACCEL auto|cpu|gpu                (default: auto)

set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
COMFY_HOST="${COMFY_HOST:-127.0.0.1}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_ACCEL="${COMFY_ACCEL:-auto}"
VENV="$COMFY_DIR/venv"

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV/bin/python" ] || die "no virtualenv at $VENV — run ./scripts/setup.sh first"

# Without a working CUDA device ComfyUI must be told to stay on the CPU,
# otherwise it aborts on startup looking for one.
ACCEL_ARGS=()
if [ "$COMFY_ACCEL" = "auto" ]; then
  if "$VENV/bin/python" -c 'import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
    COMFY_ACCEL="gpu"
  else
    COMFY_ACCEL="cpu"
  fi
fi
[ "$COMFY_ACCEL" = "cpu" ] && ACCEL_ARGS+=(--cpu)

printf '\033[1;36m==>\033[0m Starting ComfyUI (%s) on http://%s:%s\n' \
  "$COMFY_ACCEL" "$COMFY_HOST" "$COMFY_PORT"

cd "$COMFY_DIR"
exec "$VENV/bin/python" main.py \
  --listen "$COMFY_HOST" \
  --port "$COMFY_PORT" \
  "${ACCEL_ARGS[@]}" \
  "$@"
