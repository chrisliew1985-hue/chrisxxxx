---
title: JB property landing page
tags: [log, web, marketing]
created: 2026-08-15
updated: 2026-08-15
---

# 2026-08-15 — JB property landing page

Followed a reel's recipe (install Framer Motion → add a UI/UX skill →
use a pro UI prompt) and turned it into something real for the business.

## Done
- Scaffolded `web/` — Vite + React + **Framer Motion** (installed for real).
- Built a two-track animated landing page: residential ([[residential-medini]])
  and industrial ([[industrial-mfs]]), with the [[contact-cta]] WhatsApp button.
- Copy lives in `web/src/data.js`; pricing kept in "1.xx mil" format.
- Added the `ui-ux-pro-max` skill in `.claude/skills/` (the reusable design recipe).
- `npm run build` passes. Live preview published as a Claude artifact.

## Decided
- One site, two sections (not two separate sites).
- System fonts (no webfont CDN) so nothing breaks behind a proxy.

## Open
- Swap the placeholder skyline card for a real JB photo when available.
- Fill real project names / price bands into `web/src/data.js`.
- Decide where to host (Netlify/Vercel/GitHub Pages) if we go live.

## Links
- [[home]] · [[content-style]] · [[contact-cta]]
