# Button

Displays a button or a component that looks like a button. Port of shadcn/ui `button` (new-york-v4).

## Props
- `variant`: `default` · `secondary` · `outline` · `ghost` · `destructive` · `link` (default `default`)
- `size`: `xs` · `sm` · `default` · `lg` · `icon` · `icon-sm` · `icon-lg`
- `href`: renders an `<a>` styled as a button.

## Usage
- One `default` (primary) button per view; pair it with `outline` or `ghost` for secondary actions.
- `destructive` only for irreversible actions, and confirm with a dialog.
- Labels are verbs in sentence case: "Save changes", not "SAVE".
- Icons go before the label at 16px; icon-only buttons need `aria-label`.
- The consumer provides the label and the click handler.
