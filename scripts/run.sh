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
#   COMFY_ACCEL auto|cpu|gpu|mps            (default: auto)

set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
COMFY_HOST="${COMFY_HOST:-127.0.0.1}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_ACCEL="${COMFY_ACCEL:-auto}"
VENV="$COMFY_DIR/venv"

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV/bin/python" ] || die "no virtualenv at $VENV — run ./scripts/setup.sh first"

# Ask torch what it can actually use. Checking CUDA alone would misreport an
# Apple Silicon Mac as CPU-only and hand ComfyUI --cpu, quietly throwing away
# the GPU.
if [ "$COMFY_ACCEL" = "auto" ]; then
  COMFY_ACCEL=$("$VENV/bin/python" - <<'PY'
import torch
mps = getattr(torch.backends, "mps", None)
if torch.cuda.is_available():
    print("gpu")
elif mps is not None and mps.is_available():
    print("mps")
else:
    print("cpu")
PY
) || die "could not query torch — is the install complete?"
fi

# Empty arrays are expanded with the ${x[@]+"${x[@]}"} guard throughout: under
# `set -u`, bash 3.2 (still the /bin/bash on macOS) treats a bare "${x[@]}" on an
# empty array as an unbound variable and aborts.
ACCEL_ARGS=()
case "$COMFY_ACCEL" in
  cpu) ACCEL_ARGS+=(--cpu) ;;
  mps)
    # Not every torch op has a Metal kernel; without this an unimplemented op
    # aborts the run instead of quietly falling back to the CPU for that step.
    export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"
    ;;
  gpu) ;;
  *) die "COMFY_ACCEL must be one of: auto, cpu, gpu, mps (got '$COMFY_ACCEL')" ;;
esac

printf '\033[1;36m==>\033[0m Starting ComfyUI (%s) on http://%s:%s\n' \
  "$COMFY_ACCEL" "$COMFY_HOST" "$COMFY_PORT"

cd "$COMFY_DIR"
exec "$VENV/bin/python" main.py \
  --listen "$COMFY_HOST" \
  --port "$COMFY_PORT" \
  ${ACCEL_ARGS[@]+"${ACCEL_ARGS[@]}"} \
  "$@"
