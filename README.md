# WhatsApp Auto-Reply Bot

An auto-responder for property enquiries on WhatsApp. It runs on the official
**Meta WhatsApp Cloud API**, answers common questions from keyword rules you
edit in a JSON file, and falls back to **Claude** for anything the rules don't
cover — handing the chat to you the moment a real human is needed.

It runs in Meta's **coexistence** mode, so you keep using the WhatsApp Business
app on your phone with the same number. When you start typing, the bot stops.

```
customer message
      │
      ▼
 signature check ──✗──▶ 401 (not really from Meta)
      │
      ▼
 you replied from your phone, or
 chat already handed to a human? ──yes──▶ stay silent
      │
      ▼
 keyword rule matches? ──yes──▶ send the canned reply
      │ no
      ▼
 ask Claude ──fails/declines──▶ send fallback + alert you
      │
      ▼
 send reply, save the lead, alert you if a handoff is needed
```

## What it does

- **Keyword rules first.** Greetings, opening hours, areas covered, viewing
  requests — instant, free, and completely predictable. Edited in
  `config/business.json`, no code.
- **Claude for the rest.** Real questions about your listings get a real answer,
  grounded in the listings and FAQ you configure. It is told never to invent a
  price, confirm a booking, or give loan advice.
- **Knows when to get out of the way.** Offers, complaints, contracts, or
  "let me talk to a real person" pause the bot for that chat and send you an
  alert on WhatsApp with what the customer said.
- **Steps aside when you type.** You keep using the WhatsApp Business app on
  your phone. The moment you answer someone yourself, the bot goes quiet in that
  chat and stays quiet while you're in it — no talking over you, nothing to
  switch on or off.
- **After-hours awareness.** Rules can have a separate out-of-hours wording, and
  Claude is told not to promise an immediate call back when you're closed.
- **Lead capture.** Name, budget, area, timeline and viewing interest are pulled
  out of the conversation and appended to `data/leads.jsonl`.
- **Safe by default.** Webhook signature verification, per-contact hourly reply
  caps, de-duplication of Meta's webhook retries, and message bodies kept out of
  the logs.

## Quick start (no WhatsApp account needed)

You can talk to the bot before setting up anything with Meta:

```bash
npm install
npm run dry-run
```

```
customer > hi
bot      > Hi! 👋 This is Chris's assistant at Your Agency Name. Are you
           looking to buy, rent, or sell? Happy to help.
           via rule:greeting
```

Without `ANTHROPIC_API_KEY` set, only the keyword rules run — which is a good
way to check your rules before spending anything. Add the key to `.env` and
unmatched messages start going to Claude.

`/manual <text>` pretends you just replied from your phone, so you can watch the
bot go quiet the way it will in production.

`npm run doctor` checks your config and `.env` at any point and tells you what
is still missing.

## Make it yours

Everything you'd want to change lives in **`config/business.json`**. Nothing in
that file requires touching the code.

| Field | What it's for |
| --- | --- |
| `agentName`, `agency`, `signOff` | How the bot refers to you |
| `timezone`, `businessHours` | Drives after-hours replies. `null` = closed that day |
| `serviceAreas`, `about`, `languages` | Background Claude uses when answering |
| `listings` | The properties the bot may talk about. Only `status: "available"` ones are offered |
| `faq` | Question/answer pairs Claude can quote |
| `rules` | Keyword rules, checked before Claude |
| `alertNumber` | Your own WhatsApp number (E.164, no `+`) for handoff alerts. Leave empty to disable |

### Writing a rule

```json
{
  "id": "parking",
  "keywords": ["parking", "car park", "停车位"],
  "regex": "how many (bays|parking)",
  "reply": "Both units come with 2 parking bays. Which one were you asking about?",
  "afterHoursReply": "Both come with 2 bays — {{agentName}} will confirm details in the morning.",
  "handoff": false,
  "priority": 1
}
```

- `keywords` — single words match on word boundaries, so `"hi"` will **not**
  match inside `"this"`. Multi-word phrases match as a run of words. Non-Latin
  scripts (Chinese, etc.) match as substrings.
- `regex` — optional extra trigger, case-insensitive.
- `afterHoursReply` — optional; `reply` is used when it's absent.
- `handoff: true` — pause the bot in that chat and alert you.
- `priority` — tie-breaker. The rule with the longest keyword hit normally wins,
  so `"book a viewing"` beats `"hi"` in the same message without any priority.

Available placeholders in replies: `{{agentName}}`, `{{agency}}`, `{{hours}}`,
`{{areas}}`, `{{languages}}`, `{{signOff}}`, `{{name}}` (the customer's WhatsApp
profile name).

After editing, check your work with `npm run dry-run`.

## Connecting it to WhatsApp

**You can keep using the WhatsApp Business app on your phone.** Meta's
*coexistence* mode connects your existing Business app number to the Cloud API
without taking it over: you carry on chatting from your phone, and the API
handles the same number alongside you. It is available in every country.

What coexistence needs:

- The **WhatsApp Business app** (not regular WhatsApp), version 2.24.17 or newer,
  with the number already active in it.
- A Facebook **Business Page** you are an admin of.
- The app **opened at least once every 13 days**, or Meta deactivates the pairing.
- Your existing linked devices (WhatsApp Web, desktop) are unlinked during setup.
  Re-link them afterwards.

1. **Create the app.** At [developers.facebook.com](https://developers.facebook.com/apps)
   create an app of type *Business*, then add the **WhatsApp** product.
2. **Onboard your number in coexistence mode.** Run Meta's Embedded Signup and
   choose to connect an existing WhatsApp Business app number. It shows a QR
   code — scan it from your phone in *WhatsApp Business → Settings → Linked
   devices*. You'll be asked whether to sync up to 6 months of chat history and
   your contacts; you have 24 hours after onboarding to complete that sync.
   Then copy the **Phone number ID** from *WhatsApp → API Setup* (a long number,
   not the phone number itself) into `WHATSAPP_PHONE_NUMBER_ID`.

   To try things out first, Meta also gives you a free test number that needs no
   coexistence setup at all.
3. **Get a permanent token.** The token on the API Setup screen expires in 24
   hours. For production, create a **System User** under *Business settings →
   Users → System users*, give it access to your WhatsApp app, and generate a
   token with the `whatsapp_business_messaging` and
   `whatsapp_business_management` permissions. That goes in
   `WHATSAPP_ACCESS_TOKEN`.
4. **Get the App Secret.** *App settings → Basic → App Secret* →
   `WHATSAPP_APP_SECRET`. This is what proves incoming webhooks really came from
   Meta; the bot rejects anything that fails the check.
5. **Fill in `.env`.**
   ```bash
   cp .env.example .env
   # then edit .env
   ```
   Invent any long random string for `WHATSAPP_VERIFY_TOKEN` — you'll type the
   same value into Meta in the next step.
6. **Check your setup.** Before going near the webhook form:
   ```bash
   npm run doctor              # config and .env
   npm run doctor -- --live    # confirms the token and number with Meta
   ```
   It names the exact problem and the fix for each one.
7. **Expose the server.** Meta needs a public HTTPS URL. For local testing:
   ```bash
   npm run dev
   npx ngrok http 3000     # in a second terminal
   ```
   Then test the deployment the way Meta will:
   ```bash
   npm run doctor -- --url https://your-ngrok-url
   ```
   This runs the verification handshake, a correctly signed POST, and an
   unsigned one that must be rejected — so you know the URL works before Meta
   tries it. It sends a delivery-status payload, so nothing is messaged to
   anyone.
8. **Register the webhook.** In *WhatsApp → Configuration → Webhook*, set the
   callback URL to `https://your-domain/webhook` and the verify token to the
   value from step 5, then click Verify and Save. Subscribe to **`messages`**
   and — this is the one people miss — **`smb_message_echoes`**, which is what
   tells the bot you've replied from your phone. Meta calls `GET /webhook` once
   to verify; you'll see `Webhook verified by Meta` in the logs.
9. **Send yourself a message.** Message the number from another phone. The reply
   should arrive in a second or two.

### Deploying

```bash
npm run build
npm start
```

Any host that gives you a public HTTPS URL works (Railway, Render, Fly, a small
VPS). Set the same environment variables there. Two things to keep in mind:

- **State lives on disk** in `data/`. Mount it as a persistent volume, or the
  bot forgets active handoffs on redeploy. If you ever run more than one
  instance, replace the read/write pair in `src/store.ts` with Redis — that's
  the only place that would need to change.
- **Keep the Graph version current.** Meta retires versions roughly yearly; bump
  `GRAPH_API_VERSION` when they do.

## Settings

All optional, in `.env`:

| Variable | Default | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | *(unset)* | Leave blank to run on rules only, at no API cost |
| `CLAUDE_MODEL` | `claude-opus-5` | Model used for the fallback |
| `MAX_REPLIES_PER_HOUR` | `12` | Bot goes quiet after this many replies to one contact in an hour |
| `HANDOFF_PAUSE_HOURS` | `12` | How long the bot stays out of a chat after handing it over |
| `MANUAL_REPLY_PAUSE_HOURS` | `4` | How long the bot stays out after *you* reply from your phone. Each manual reply extends it |
| `HISTORY_TURNS` | `12` | Conversation turns remembered per contact |
| `LOG_MESSAGE_BODIES` | `false` | Set `true` only while debugging — it writes customer messages to your logs |
| `PORT` | `3000` | |

## Things worth knowing

- **The 24-hour window.** Meta only allows free-form messages within 24 hours of
  the customer's last message. Every reply here is a reply to an inbound
  message, so it's always inside the window. Messaging someone first, or after
  24 hours of silence, requires a pre-approved message template — this bot
  doesn't do that.
- **Handoff alerts are subject to that same window.** The alert to your
  `alertNumber` is a free-form message, so it only arrives if you've messaged
  the bot's number within the last 24 hours. Send it a "hi" now and then, or
  watch the logs instead — a handoff is always logged whether or not the alert
  gets through.
- **Taking a chat back.** A handoff pauses auto-replies for
  `HANDOFF_PAUSE_HOURS`. It resumes on its own after that. To resume sooner,
  call `store.clearHandoff(number)` — worth wiring to an admin route if you find
  yourself doing it often.
- **The bot won't confirm bookings.** By design: it collects a preferred time
  and tells the customer you'll confirm. Confirming slots means integrating your
  actual calendar, which is a different job.
- **Photos and voice notes** get a polite acknowledgement — the bot can't read
  them.
- **Keep opening the app.** Coexistence needs the WhatsApp Business app opened
  at least once every 13 days or Meta deactivates the pairing. Normal daily use
  covers this; a long holiday might not.
- **App replies are free, API replies are not.** Anything you send from your
  phone costs nothing. The bot's replies go through the Cloud API and are
  billed at Meta's rates.

## Development

```bash
npm run dev         # server with reload
npm run doctor      # check config, .env, Meta connection, deployed webhook
npm run dry-run     # chat with the bot in your terminal
npm test            # 37 tests, no network calls
npm run typecheck
```

| File | What's in it |
| --- | --- |
| `src/index.ts` | Express server, webhook verification and routing |
| `src/brain.ts` | The decision: rule, Claude, canned, or silence |
| `src/rules.ts` | Keyword matching and `{{placeholder}}` rendering |
| `src/claude.ts` | Claude prompt, structured output, error handling |
| `src/whatsapp.ts` | Cloud API calls, inbound and echo payload parsing |
| `src/store.ts` | Per-contact state, de-duplication, rate limits, leads |
| `src/hours.ts` | Business-hours logic |
| `src/signature.ts` | Meta webhook HMAC verification |
| `src/doctor.ts` | Setup checker (`npm run doctor`) |

`decide()` in `src/brain.ts` never touches the network — it takes a message and
returns a decision, which is why the whole reply path is testable offline.
