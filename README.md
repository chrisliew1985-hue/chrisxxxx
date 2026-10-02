# wa-crm: WhatsApp → Apple Calendar + CRM

A daily job on your Mac that:

1. **Reads both WhatsApps.** It reads the regular WhatsApp app and WhatsApp Business from the desktop apps' local chat databases. Access is read-only: no QR bot and no risk of your number being banned.
2. **Finds CONFIRMED appointments** with Claude, which reads English, Malay and Chinese. Examples are viewings, meetings, signing and handover. It adds them to **Apple Calendar** (iCloud), with a reminder 1 hour before.
   - Tentative proposals are skipped. Only clear agreement on a date and time counts.
   - If a client moves an appointment, the old event is removed and the new one is added. If they cancel it, the event is removed.
3. **Updates your CRM.** It keeps one record per contact:
   - **Type:** `Client` or `Agent`. Friends, family and vendors stay out of the CRM unless you turn that on.
   - **Potential:** `Hot` / `Warm` / `Cold`, with a one-line reason.
   - **Client role:** Buyer / Tenant / Owner / Landlord / Investor.
   - **Other fields:** summary, requirements (budget, area, size…), next step, last contact, next appointment, and which WhatsApp the contact uses.

```
WhatsApp + WhatsApp Business (Mac)  ──►  Claude  ──►  iCloud Calendar
                                             └────►  Notion CRM (or contacts.csv)
```

## What you need

- A Mac with the **WhatsApp** and/or **WhatsApp Business** desktop app, logged in. The Mac must be on at the scheduled time.
- An **Anthropic API key**: <https://console.anthropic.com/settings/keys>
- An **iCloud app-specific password**: appleid.apple.com → Sign-In and Security → App-Specific Passwords
- A **Notion** integration token, for the CRM: <https://www.notion.so/my-integrations>. If you'd rather not use Notion, set `crm_backend: csv` to get a spreadsheet instead.

## Setup (about 10 minutes)

```bash
git clone <this repo> ~/wa-crm && cd ~/wa-crm
./scripts/install_mac.sh          # schedules a daily run at 21:00; use e.g. `8 30` for 08:30
```

Then:

1. **Fill in `~/.wa-crm/.env`** with your API key, Apple ID, app password and Notion token. Check `~/.wa-crm/config.yaml`, especially `timezone`.
2. **Create the CRM in Notion.** Make a page and share it with your integration (page `•••` → Connections). Then run:
   ```bash
   ~/.wa-crm/venv/bin/python -m wa_crm setup-notion --parent-page <page-id>
   ```
   Paste the printed `NOTION_DATABASE_ID=…` into `~/.wa-crm/.env`.
3. **Grant Full Disk Access** to the Python binary that the installer printed. Do this in System Settings → Privacy & Security → Full Disk Access. macOS requires it before anything can read WhatsApp's data folder.
4. **Do a dry run.** It shows exactly what would be added and changes nothing:
   ```bash
   ~/.wa-crm/venv/bin/python -m wa_crm run --dry-run
   ```
5. If the dry run looks right, run it for real: `launchctl kickstart gui/$(id -u)/com.wa-crm.daily`

From then on it runs every day by itself. The log is in `~/.wa-crm/run.log`.

## Day-to-day

- Appointments go into a separate calendar called **"WhatsApp Appointments"**, so you can tell them apart or hide them. Titles start with `[Client]` or `[Agent]`. Each event's notes include the contact's details, a `wa.me` link and the potential rating.
- If the AI gets a contact wrong in Notion, fix it and tick **Lock** on that contact. Future runs will then leave its Type, Potential and Role alone.
- Each run only looks at messages that arrived since the last run. Claude also sees up to 30 days of earlier chat as context. Re-running is safe: events are matched by a stable ID, so nothing gets duplicated.
- Group chats are skipped by default. Set `include_groups: true` to include agent co-broke groups.

## Cost

Each run uses Claude (`claude-opus-5-5`) once per chat that has new messages. A typical day of 20–40 active chats costs roughly US$0.50–1.50. To save money, set `model: claude-sonnet-5-5` in `config.yaml`.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

| File | Purpose |
| --- | --- |
| `wa_crm/whatsapp.py` | Reads `ChatStorage.sqlite` from both WhatsApp apps |
| `wa_crm/extract.py` | Claude prompt and structured output (contact type, potential, appointments) |
| `wa_crm/calendar_icloud.py` | iCloud CalDAV events |
| `wa_crm/crm.py` | Notion / CSV CRM |
| `wa_crm/main.py` | Daily runner and CLI |
| `scripts/install_mac.sh` | venv + launchd daily schedule |
