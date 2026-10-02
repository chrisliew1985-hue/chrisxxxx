# Default design system: shadcn/ui

Whenever I ask for any UI — a web page, app, dashboard, landing page, artifact, slide, form, component or mockup — use the **shadcn/ui** design system by default (unless I name a different brand or style).

- Published design system (tokens, type, live components, brand book): https://claude.ai/artifact/4KYA5mM1fXBewhQtxDxq2J — read its `project/README.md` first.
- Local copy in this repo: `design-system/` — `README.md` (rules), `tokens.json` (colors light/dark, type, spacing, radius, shadows), `components/bundle.css` + `components/bundle.js` (plain HTML/React port, `window.Shadcn`), `components/<Name>/README.md` (usage per component).
- In real React/Next.js projects install the original: `npx shadcn@latest init` (style New York, base color Neutral), then `npx shadcn@latest add <component>`.

Key rules: neutral grayscale palette, colour only for meaning (`destructive`, `chart-1…5`); Geist / Geist Mono; 36px controls; radius base 10px; 1px borders over shadows; sentence case; Lucide icons at 16px; support light and dark.
