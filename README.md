# wa-crm: WhatsApp → Apple Calendar + CRM

A daily job that:

1. **Reads both WhatsApps.** It reads your regular WhatsApp and WhatsApp Business. It runs **in the cloud**, so your laptop can be off. A Mac-only mode is also available.
2. **Finds CONFIRMED appointments** with Claude, which reads English, Malay and Chinese. Examples are viewings, meetings, signing and handover. It adds them to **Apple Calendar** (iCloud), with a reminder 1 hour before.
   - Tentative proposals are skipped. Only clear agreement on a date and time counts.
   - If a client moves an appointment, the old event is removed and the new one is added. If they cancel it, the event is removed.
3. **Updates your CRM.** It keeps one record per contact:
   - **Type:** `Client` or `Agent`. Friends, family and vendors stay out of the CRM unless you turn that on.
   - **Potential:** `Hot` / `Warm` / `Cold`, with a one-line reason.
   - **Client role:** Buyer / Tenant / Owner / Landlord / Investor.
   - **Other fields:** summary, requirements (budget, area, size…), next step, last contact, next appointment, and which WhatsApp the contact uses.

```
Phone ──(linked device)──► Cloud server: collector saves messages 24/7
                                       └─ every day 21:00 ─► Claude ─► iCloud Calendar
                                                                  └──► Notion CRM
```

## Option A: Cloud (recommended — laptop can be off)

The server links to each WhatsApp as a **linked device**, exactly like WhatsApp Web. It only reads and never sends anything. Your phone keeps working as normal. You'll see the server under *Settings → Linked devices*, and you can remove it there at any time.

> Linking a server as a device uses an unofficial WhatsApp Web library ([Baileys](https://github.com/WhiskeySockets/Baileys)). It is read-only and behaves like a normal WhatsApp Web session, so the risk is low, but WhatsApp does not officially support it. The server also stores your chat text, so keep the hosting account private.

### 1. Get the keys
- **Anthropic API key**: <https://console.anthropic.com/settings/keys>
- **iCloud app-specific password**: appleid.apple.com → Sign-In and Security → App-Specific Passwords
- **Notion integration token**: <https://www.notion.so/my-integrations>. Then create a page in Notion and share it with the integration (page `•••` → Connections).

### 2. Deploy on Railway (about US$5/month)
1. Sign in at <https://railway.com> with GitHub, then choose **New Project → Deploy from GitHub repo** and pick this repo. It builds from the `Dockerfile` automatically.
2. In the service, open **Settings → Volumes → Add Volume** and set the mount path to `/data`. **This is required**: it keeps your WhatsApp login and messages across restarts.
3. Under **Variables**, add every line from [`.env.example`](.env.example) with your values. Leave `NOTION_DATABASE_ID` empty for now. `WA_PHONE_WHATSAPP` / `WA_PHONE_BUSINESS` are your two numbers with country code, digits only, e.g. `60123456789`.
4. Deploy, then open **Deployments → View logs**.

### 3. Link both WhatsApps (one time)
The logs show a code for each account, like:
```
[whatsapp] PAIRING CODE: ABCD-EFGH
```
On the phone with **that** WhatsApp, go to *Settings → Linked devices → Link a device → Link with phone number instead* and type the code. Do the same for `[business]` in the WhatsApp Business app. When it works, the logs show `connected`. The first link also imports recent chat history for context.

If a code expires, just restart the deployment to get a new one.

### 4. Create the CRM table in Notion (one time)
In Railway, open the service's **⋯ → Shell** (or use `railway ssh`) and run:
```bash
python -m wa_crm setup-notion --parent-page <your Notion page id>
```
Copy the printed `NOTION_DATABASE_ID` into Railway's Variables. Railway redeploys, and your WhatsApp links are kept because they live on the volume.

### 5. Check it
Set `RUN_ON_START=dry` and redeploy. The logs will show exactly which appointments and contacts it *would* add. When the output looks right, clear that variable. From then on it runs automatically every day at `WA_CRM_RUN_AT`.

**If a WhatsApp gets unlinked**, the daily log says so (`WhatsApp 'business' is logged_out`). To fix it, delete `/data/auth/business` in the Shell and restart, then link again.

### Any other host
The same container runs anywhere Docker does: a VPS from Hetzner, DigitalOcean or Lightsail, Fly.io, and so on:
```bash
cp .env.example .env   # fill it in
docker compose up -d
docker compose logs -f # pairing codes appear here
```

## Option B: Mac only

This option reads the WhatsApp desktop apps' local databases directly, with no linked device. The Mac must be on at the scheduled time.

1. Run `./scripts/install_mac.sh`. It schedules a daily run at 21:00; pass e.g. `8 30` for 08:30.
2. Fill in `~/.wa-crm/.env` (see `.env.example`) and check `~/.wa-crm/config.yaml`, especially `timezone`.
3. Run `~/.wa-crm/venv/bin/python -m wa_crm setup-notion --parent-page <page-id>` and put the printed ID in `.env`.
4. Give Python **Full Disk Access**. The installer prints the path; add it under System Settings → Privacy & Security.
5. Preview with `~/.wa-crm/venv/bin/python -m wa_crm run --dry-run`, then run it for real with `launchctl kickstart gui/$(id -u)/com.wa-crm.daily`.

## Day-to-day

- Appointments go into a separate calendar called **"WhatsApp Appointments"**, so you can tell them apart or hide them. Titles start with `[Client]` or `[Agent]`. Each event's notes include the contact's details, a `wa.me` link and the potential rating.
- If the AI gets a contact wrong in Notion, fix it and tick **Lock** on that contact. Future runs will then leave its Type, Potential and Role alone.
- Each run only looks at messages that arrived since the last run. Claude also sees up to 30 days of earlier chat as context. Re-running is safe: events are matched by a stable ID, so nothing gets duplicated.
- Group chats are skipped by default. To include agent co-broke groups, set `WA_CRM_INCLUDE_GROUPS=true` in the cloud, or `include_groups: true` in `config.yaml` on a Mac.
- Any setting in `config.example.yaml` can be set in the cloud as `WA_CRM_<NAME>`, e.g. `WA_CRM_ALARM_MINUTES=30`.

## Cost

Hosting is about US$5/month on Railway. On top of that, each run uses Claude (`claude-opus-5-5`) once per chat that has new messages. A typical day of 20–40 active chats costs roughly US$0.50–1.50. To save money, set `WA_CRM_MODEL=claude-sonnet-5-5` in the cloud, or `model: claude-sonnet-5-5` in `config.yaml` on a Mac.

## Development

```bash
pip install -r requirements-dev.txt
(cd collector && npm ci)
pytest
```

| File | Purpose |
| --- | --- |
| `collector/index.js` | Cloud: always-on linked-device collector, saves messages to `/data/messages.db` |
| `wa_crm/cloud_store.py` | Cloud: reads the collector's database |
| `wa_crm/whatsapp.py` | Mac: reads `ChatStorage.sqlite` from both WhatsApp desktop apps |
| `wa_crm/extract.py` | Claude prompt and structured output (contact type, potential, appointments) |
| `wa_crm/calendar_icloud.py` | iCloud CalDAV events |
| `wa_crm/crm.py` | Notion / CSV CRM |
| `wa_crm/main.py` | Daily runner, `serve` scheduler and CLI |
| `Dockerfile`, `scripts/start_cloud.sh` | Cloud container (collector + daily job) |
| `scripts/install_mac.sh` | Mac: venv + launchd daily schedule |
