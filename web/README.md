# JB Property Landing (`web/`)

Animated landing page for Chris Liew — two tracks in one site:
**Residential (Medini / Iskandar Puteri)** and **Industrial (Malaysia Factory Space)**.
Built with **Vite + React + Framer Motion**.

## Run it
```bash
cd web
npm install        # installs react, react-dom, framer-motion, vite
npm run dev        # local dev server → http://localhost:5173
npm run build      # production build → dist/
npm run preview    # preview the production build
```

## Edit the content
All copy lives in **`src/data.js`** (agent details, hero text, the two tracks,
stats, steps). Change wording there — you don't need to touch the JSX.

- WhatsApp CTA: `+60103698656` (set in `src/data.js` → `AGENT.waLink`)
- Pricing follows the vault rule: shown as `1.xx mil`, never exact.

## How it's built
- `src/App.jsx` — the page, with Framer Motion scroll-reveals, staggered hero
  entrance, hover lift on cards, and a reduced-motion fallback.
- `src/index.css` — the design system (palette, type scale, layout).
- Design recipe: see the `ui-ux-pro-max` skill in `.claude/skills/`.
