#!/usr/bin/env bash
# Renders the vertical (Reels / WhatsApp status) and landscape cuts for CL8656.
set -euo pipefail
cd "$(dirname "$0")"

COMMON=(
  --shotlist listings/the-woodlands-horizon-hills.json
  --title "The Woodlands @ Horizon Hills"
  --subtitle "全新双层 Cluster · 4+1 房 · 永久地契"
  --spec "土地 面积=35' x 80'|建筑面积=约 3,144 sqft|房 间=4+1 房 · 5 浴室|地 契=永久地契 · 非土著|状 态=全新空屋 · 保安区"
  --spec-note "RM 1.98 mil"
  --end-card "想看这间房?|WhatsApp 我，今天就安排"
  --agent-photo assets/agent_chris.jpg
  --agent-name "Chris Liew"
  --agent-tag "PropNex Realty · REN 08014"
  --agent-phone "+60 10-369 8656"
  --spec-at 2
  --grade warm
  --accent "#E8C37A"
)

python3 walkthrough.py "${COMMON[@]}" -o out/woodlands_reel_9x16.mp4 \
    --aspect 9:16 --height 1920 --fit smart "$@"

python3 walkthrough.py "${COMMON[@]}" -o out/woodlands_16x9.mp4 \
    --aspect 16:9 --height 1080 --fit cover "$@"
