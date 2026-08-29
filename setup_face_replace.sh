#!/usr/bin/env bash
# One-time setup for face_replace.py: ffmpeg, python deps, and the four models.
set -euo pipefail
cd "$(dirname "$0")"
M=models; mkdir -p "$M"

if ! command -v ffmpeg >/dev/null; then
  echo "installing ffmpeg..."
  if   command -v apt-get >/dev/null; then sudo apt-get update && sudo apt-get install -y --no-install-recommends ffmpeg
  elif command -v brew    >/dev/null; then brew install ffmpeg
  else echo "install ffmpeg yourself, then re-run" >&2; exit 1; fi
fi

python3 -m pip install --upgrade numpy opencv-python-headless onnxruntime insightface

FF=https://github.com/facefusion/facefusion-assets/releases/download
IF=https://github.com/deepinsight/insightface/releases/download

fetch () {  # fetch <url> <dest>
  [ -f "$2" ] && { echo "have $(basename "$2")"; return; }
  echo "downloading $(basename "$2")..."; curl -L --retry 3 -o "$2" "$1"
}

fetch "$FF/models-3.0.0/inswapper_128.onnx" "$M/inswapper_128.onnx"   # the swap
fetch "$FF/models-3.1.0/xseg_1.onnx"        "$M/xseg_1.onnx"          # occlusion mask
fetch "$FF/models-3.0.0/gfpgan_1.4.onnx"    "$M/gfpgan_1.4.onnx"      # optional restore

if [ ! -d "$M/buffalo_l" ]; then
  echo "downloading buffalo_l (detector + ArcFace)..."
  curl -L --retry 3 -o "$M/buffalo_l.zip" "$IF/v0.7/buffalo_l.zip"
  python3 -c "import zipfile;zipfile.ZipFile('$M/buffalo_l.zip').extractall('$M/buffalo_l')"
  rm -f "$M/buffalo_l.zip"
fi

echo
echo "ready. run:"
echo "  python3 face_replace.py -i input_video.mp4 \\"
echo "      --person-a person_A.png --person-b person_B.png \\"
echo "      --models models --map 1:A,0:B -o final_replace.mp4"
