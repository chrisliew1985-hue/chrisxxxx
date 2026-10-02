# shadcn/ui

Beautifully designed components that you can copy and paste into your apps. Accessible. Customizable. Open source.

This system is built from **[shadcn-ui/ui](https://github.com/shadcn-ui/ui)** — the most-starred design system on GitHub (100k+ ★) — using its v4 **New York** style and **Neutral** base color, exactly as `npx shadcn@latest init` ships it. Use it as the default look for any UI, page, app, dashboard or artifact unless a brand says otherwise.

## Content fundamentals

- **Voice:** plain, calm, developer-friendly. Say what a thing does, then stop. "Deploy your new project in one click."
- **Case:** sentence case everywhere — titles, buttons, tabs, menu items. Never ALL CAPS.
- **Buttons are verbs:** "Save changes", "Create account", "Continue". Destructive buttons name the loss: "Delete project".
- **Descriptions** sit under titles in `muted-foreground`, one sentence, ending with a period.
- No emoji in UI chrome. Numbers as digits.

## Visual foundations

- **Neutral first.** The palette is grayscale (`oklch(L 0 0)`): `background`, `foreground`, `primary`, `secondary`, `muted`, `accent`, `border`, `input`, `ring`. Colour appears only for meaning — `destructive` for errors and irreversible actions, `chart-1…5` for data.
- **Semantic pairs.** Every surface token has a `-foreground` partner (`card` / `card-foreground`, `primary` / `primary-foreground`). Always use the pair; never put text colour on a surface it wasn't paired with.
- **Light and dark** are the same tokens with different values; nothing is hard-coded. In dark, `border` and `input` are translucent white (10% / 15%).
- **Borders over shadows.** 1px `border` defines structure; shadows are small (`shadow-xs` on controls, `shadow-sm` on cards, `shadow-md` on popovers, `shadow-lg` on dialogs).
- **Radius** derives from one base, `radius` = 10px: `radius-sm` 6, `radius-md` 8 (buttons, inputs), `radius-lg` 10 (alerts, popovers), `radius-xl` 14 (cards, dialogs), `radius-full` (badges, avatars, switches).
- **Spacing** is the Tailwind 4px scale: `space-2` (8) inside controls, `space-4` (16) between fields, `space-6` (24) card padding, `space-8`+ between sections.
- **Controls** are 36px tall (`control-md`); `sm` 32, `lg` 40, `xs` 24.
- **Focus** is always visible: border becomes `ring` plus a 3px `ring` halo at 50%.
- **Type** is Geist (sans) and Geist Mono, from Google Fonts. UI text is 14px/500 (`ui`); body 16px/28px (`p`); headings tight (−0.025em) at 600–800.

## Iconography

shadcn/ui uses **[Lucide](https://lucide.dev)** icons: 24×24 grid, 2px stroke, round caps and joins, `currentColor`. Inside buttons and menus they render at 16px (`size-4`), 12px in `xs` controls. Icons inherit the text colour of their container; never colour them independently.

## Using it

- **React + Tailwind (real apps):** `npx shadcn@latest init` then `npx shadcn@latest add button card input …`. Pick base color *Neutral*. The tokens here match the generated `globals.css`.
- **Plain HTML / artifacts:** load `tokens.css`, `components/bundle.css`, React 18 and `components/bundle.js`, then use `window.Shadcn.Button`, `Shadcn.Card`, … (or just the `sc-*` CSS classes, e.g. `<button class="sc-btn sc-btn--outline">`).
- Toggle dark mode with `data-theme="dark"` on `<html>`.

## Components

Button, Badge, Input, Textarea, Label, Card, Alert, Checkbox, Switch, Tabs, Avatar, Separator, Skeleton, Progress, Kbd. The upstream registry has ~60 (Dialog, Dropdown Menu, Select, Popover, Tooltip, Table, Sidebar, Sonner, Calendar, Chart…) — install them with the CLI in code; follow the same tokens.
