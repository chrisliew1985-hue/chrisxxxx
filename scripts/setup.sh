#!/usr/bin/env bash
#
# Install ComfyUI into a self-contained directory with its own virtualenv.
#
# Usage:
#   ./scripts/setup.sh
#
# Environment overrides:
#   COMFY_DIR    Where ComfyUI is installed.       (default: $HOME/ComfyUI)
#   COMFY_ACCEL  Torch build: auto|cpu|cu124|cu128 (default: auto)
#   COMFY_REF    Git ref/tag to check out.         (default: repo default branch)
#
# The script is idempotent: re-running it updates the checkout and re-syncs
# dependencies without recreating the virtualenv.

set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
COMFY_ACCEL="${COMFY_ACCEL:-auto}"
COMFY_REPO="https://github.com/comfyanonymous/ComfyUI.git"
VENV="$COMFY_DIR/venv"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- pick a torch build -------------------------------------------------------
OS="$(uname -s)"

if [ "$COMFY_ACCEL" = "auto" ]; then
  if [ "$OS" = "Darwin" ]; then
    if [ "$(uname -m)" = "arm64" ]; then
      COMFY_ACCEL="mps"
      log "Apple Silicon detected, using the Metal-capable torch build"
    else
      COMFY_ACCEL="cpu"
      log "Intel Mac detected, using CPU torch build (Metal needs Apple Silicon)"
    fi
  elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    COMFY_ACCEL="cu124"
    log "NVIDIA GPU detected, using CUDA 12.4 torch build"
  else
    COMFY_ACCEL="cpu"
    log "No NVIDIA GPU detected, using CPU-only torch build"
  fi
fi

# An empty TORCH_INDEX means "install from PyPI".
case "$COMFY_ACCEL" in
  mps)   TORCH_INDEX="" ;;
  cpu)   TORCH_INDEX="https://download.pytorch.org/whl/cpu" ;;
  cu124) TORCH_INDEX="https://download.pytorch.org/whl/cu124" ;;
  cu128) TORCH_INDEX="https://download.pytorch.org/whl/cu128" ;;
  *)     die "COMFY_ACCEL must be one of: auto, cpu, mps, cu124, cu128 (got '$COMFY_ACCEL')" ;;
esac

# macOS wheels on PyPI already carry Metal support, and PyTorch's own index has
# no macOS builds to offer, so never send a Mac to the CPU index.
if [ "$OS" = "Darwin" ]; then
  TORCH_INDEX=""
fi

# --- checks -------------------------------------------------------------------
command -v git >/dev/null 2>&1 || die "git is required but not installed"
command -v curl >/dev/null 2>&1 || die "curl is required but not installed"
py_ok() {
  command -v "$1" >/dev/null 2>&1 &&
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

if [ -n "${PYTHON:-}" ]; then
  command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON not found"
  py_ok "$PYTHON" || die "$PYTHON is $("$PYTHON" -V 2>&1), but ComfyUI needs 3.10 or newer"
else
  # macOS still ships 3.9 as python3, which is below ComfyUI's minimum. Rather
  # than failing, fall through to any newer interpreter that is installed.
  PYTHON=""
  for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
    if py_ok "$candidate"; then PYTHON="$candidate"; break; fi
  done
  if [ -z "$PYTHON" ]; then
    found=$(python3 -V 2>&1 || echo "none")
    die "no Python 3.10+ on PATH (python3 is: $found)
  macOS:  brew install python@3.12
  Debian: sudo apt install python3.12 python3.12-venv
  Then re-run, or point at it directly: PYTHON=/path/to/python3.12 $0"
  fi
fi
log "Using $PYTHON ($("$PYTHON" -V 2>&1))"

# --- fetch source -------------------------------------------------------------
if [ -d "$COMFY_DIR/.git" ]; then
  log "Updating existing checkout at $COMFY_DIR"
  git -C "$COMFY_DIR" fetch --depth 1 origin "${COMFY_REF:-HEAD}"
  git -C "$COMFY_DIR" checkout --force FETCH_HEAD
else
  log "Cloning ComfyUI into $COMFY_DIR"
  git clone --depth 1 "$COMFY_REPO" "$COMFY_DIR"
  if [ -n "${COMFY_REF:-}" ]; then
    git -C "$COMFY_DIR" fetch --depth 1 origin "$COMFY_REF"
    git -C "$COMFY_DIR" checkout --force FETCH_HEAD
  fi
fi

# --- virtualenv ---------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "Creating virtualenv at $VENV"
  "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
log "Upgrading pip"
"$PIP" install --quiet --upgrade pip wheel

# Some sandboxed/corporate networks allow PyPI but block download.pytorch.org.
# Probe it first and fall back to PyPI rather than failing the whole install.
# The PyPI wheel bundles CUDA, so it is larger but runs fine on a CPU-only host.
if [ -z "$TORCH_INDEX" ]; then
  log "Installing torch ($COMFY_ACCEL) from PyPI"
  "$PIP" install torch torchvision torchaudio
elif curl -fsI --max-time 20 "$TORCH_INDEX/torch/" >/dev/null 2>&1; then
  log "Installing torch ($COMFY_ACCEL) from $TORCH_INDEX"
  "$PIP" install --index-url "$TORCH_INDEX" torch torchvision torchaudio
else
  log "$TORCH_INDEX is unreachable, falling back to PyPI"
  [ "$COMFY_ACCEL" = "cpu" ] && \
    log "note: the PyPI wheel bundles CUDA (~3GB); it still runs on CPU"
  "$PIP" install torch torchvision torchaudio
fi

log "Installing ComfyUI dependencies"
"$PIP" install -r "$COMFY_DIR/requirements.txt"

# --- report -------------------------------------------------------------------
log "Verifying install"
"$VENV/bin/python" - <<'CHECK'
import torch
mps = getattr(torch.backends, "mps", None)
if torch.cuda.is_available():
    device = "cuda"
elif mps is not None and mps.is_available():
    device = "mps (Metal)"
else:
    device = "cpu"
print(f"  torch          {torch.__version__}")
print(f"  device         {device}")
CHECK
printf '  comfyui        %s\n' "$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$COMFY_DIR/comfyui_version.py")"

log "Done. Start the server with:  ./scripts/run.sh"
