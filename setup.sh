#!/usr/bin/env bash
# One-time setup: ffmpeg, python deps, and the Depth Anything V2 weights.
set -euo pipefail

MODEL_DIR="$(dirname "$0")/models"
MODEL="$MODEL_DIR/depth_anything_v2_vits.onnx"
MODEL_URL="https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/v2.0.0/depth_anything_v2_vits.onnx"

if ! command -v ffmpeg >/dev/null; then
  echo "installing ffmpeg..."
  if command -v apt-get >/dev/null; then
    sudo apt-get update && sudo apt-get install -y --no-install-recommends ffmpeg
  elif command -v brew >/dev/null; then
    brew install ffmpeg
  else
    echo "install ffmpeg yourself, then re-run" >&2; exit 1
  fi
fi

python3 -m pip install --upgrade numpy opencv-python-headless onnxruntime

mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL" ]; then
  echo "downloading Depth Anything V2 ViT-S (~95 MB)..."
  curl -L --retry 3 -o "$MODEL" "$MODEL_URL"
fi

echo "ready. try: python3 depth_video.py -i your_clip.mp4 -o out"
