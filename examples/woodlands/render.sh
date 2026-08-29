#!/usr/bin/env bash
# The Woodlands @ Horizon Hills (CL8656) - vertical listing reel.
# Run from the repository root:  bash examples/woodlands/render.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"

cd "$root"
python3 -m broll "$here/photos" \
  --preset property \
  --captions "$here/captions.txt" \
  --title "THE WOODLANDS" \
  --subtitle "Horizon Hills  ·  Brand New Cluster Home" \
  --end-card "RM 1.98 mil" \
  --end-card-sub "CL8656  ·  Freehold  ·  Non-Bumi\n\nChris Liew   REN 08014\nPropNex Realty\n+60 10-369 8656" \
  --grade cinematic \
  --out "${1:-$here/woodlands-vertical.mp4}" \
  "${@:2}"
