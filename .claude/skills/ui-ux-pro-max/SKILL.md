---
name: ui-ux-pro-max
description: >-
  Turn a plain UI request into a polished, animated interface. Use when
  building or restyling a web page, landing page, or React/HTML component and
  the goal is a premium, modern look with tasteful motion (Framer Motion / CSS).
  Applies a clear design system — palette, type scale, spacing, motion rules —
  instead of generic AI defaults.
---

# UI/UX Pro Max

A reusable recipe for producing interfaces that look designed, not generated.
Follow it whenever you build or restyle UI in this repo (see `web/`).

## 1. Decide the treatment first
- **Utilitarian** (dashboard, form): restraint, hierarchy, no flashy hero.
- **Editorial** (landing page, marketing): one bold hero, memorable type, motion.
Pick one before writing code. Most business landing pages are editorial-lite.

## 2. Design system (fill these in, then obey them)
- **Palette — 4-6 named hex values.** Choose a *considered* neutral (a grey/cream
  with a slight bias toward the accent), one primary accent, and at most one
  secondary. Never a pure `#808080` grey or an unstyled default blue.
- **Type — 2 roles minimum.** A characterful display face (serif or strong sans)
  used with restraint, plus a clean body face. Set a type scale
  (`clamp()` for fluid sizes) and stay on it. Uppercase labels get letter-spacing.
  Avoid webfont CDNs (they can be blocked) — inline a `@font-face` data URI or use
  a strong system stack.
- **Layout.** Use flex/grid + `gap`, never per-element margins that collapse.
  Keep running text ~65 characters wide. Wide content scrolls in its own
  `overflow-x:auto` box.

## 3. Motion (Framer Motion) — taste over quantity
- Install: `npm install framer-motion`.
- **Entrance:** hero elements fade + rise on load with a stagger
  (`staggerChildren` ~0.09, `y: 24 -> 0`, ease `[0.22, 1, 0.36, 1]`).
- **On scroll:** reveal sections with `whileInView` + `viewport={{ once: true }}`.
- **On hover:** lift cards `whileHover={{ y: -6 }}` with a spring.
- **Ambient:** at most one slow looping accent (e.g. a floating element).
- Always honor `useReducedMotion()` — disable transforms when it returns true.

## 4. Copy is design material
- Buttons say exactly what happens ("Message Chris", not "Submit").
- Active voice, specific over clever, no lorem ipsum — use real content.

## 5. Before shipping
- Both themes legible (or a deliberate single-theme commitment).
- Keyboard focus visible; `prefers-reduced-motion` respected.
- `npm run build` passes with no errors.

## Repo notes
- The reference implementation lives in `web/` (Vite + React + Framer Motion):
  a two-track JB property landing page for Chris Liew.
- Copy content lives in `web/src/data.js` — edit copy there, not in the JSX.
