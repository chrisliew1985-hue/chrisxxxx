# wa-crm: WhatsApp → Apple Calendar + CRM

A daily job that **only reads** your WhatsApp and WhatsApp Business chats (it never sends anything), then:

1. **Adds CONFIRMED appointments to Google Calendar**, with a reminder 1 hour before. Examples are viewings, meetings, signing and handover. If you add your Google account on your iPhone/Mac, the events also show in the Apple Calendar app. Writing to iCloud directly is optional.
   - Tentative proposals are skipped. Only clear agreement on a date and time counts.
   - If someone moves an appointment, the old event is replaced. If they cancel it, the event is removed.
   - It reads English, Malay and Chinese.
2. **Updates your Notion CRM**, one row per contact:
   - **Type:** `Client`, `Owner` or `Agent`. Friends, family and vendors stay out.
   - **Role:** Buyer / Tenant / Investor for clients, Seller / Landlord for owners.
   - **Potential:** `Hot` / `Warm` / `Cold`, with a one-line reason.
   - **Other fields:** requirements (budget, area, size…), properties (units listed or viewed), next step, summary, phone, last contact, next appointment, and which WhatsApp the contact uses.

```
Phones ──(linked device)──► Free cloud server ── saves messages 24/7
                                  ▲   │ returns confirmed appointments + contacts
     every day 21:00              │   ▼
     Claude Routine (your plan) ──┴── adds events ──► Google Calendar
                                      updates rows ─► Notion CRM
```

## Option A: Free cloud setup (recommended: no API keys, laptop can be off)

- **Server:** your VPS, or an Oracle Cloud *Always Free* server, keeps both WhatsApps linked as **linked devices**, like WhatsApp Web.
- **AI:** a daily **Claude Routine** on your existing Claude plan reads the new chats. It adds confirmed appointments through your **Google Calendar** connection and updates the CRM through your **Notion** connection.
- **Extra cost:** $0.

> The server runs real WhatsApp Web in a hidden browser ([whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js), the same library many WA tools use) and links it as a device. It only reads, so the risk is low, but WhatsApp does not officially support automation tools. The server stores your chat text, so keep the server account private. You can unlink it any time on your phone under *Settings → Linked devices*.

### 1. Get a server

**Already have a VPS (e.g. Hostinger)?** Use it and skip to step 2:
- Choose an **Ubuntu** (or Debian) template. If you're on a different OS, you can switch it under hPanel → VPS → *OS & Panel*.
- Log in through hPanel's **Browser terminal**, or `ssh root@<VPS IP>`.
- In hPanel → VPS → **Firewall**: if a firewall is enabled, allow TCP ports **80** and **443**.
- If another app already runs **Caddy** on ports 80/443 (a WA blast tool, for example), the installer adds one entry for wa-crm to that Caddy instead of starting a second one (`scripts/share_caddy.sh`). It backs up the config first, checks it before applying, and reloads without restarting, so the other app keeps working. If something other than Caddy holds port 443, the installer stops without changing anything.
- It needs about 500 MB of free RAM. The smallest Hostinger plan is enough.

**No server yet?** Create a free Oracle one (about 15 minutes, one time):
1. Sign up at <https://www.oracle.com/cloud/free/>. It asks for a card to verify you, but *Always Free* resources are never charged.
2. Go to **Compute → Instances → Create instance**:
   - **Image:** Ubuntu 24.04.
   - **Shape:** `VM.Standard.A1.Flex` with 1 OCPU and 6 GB RAM, or `VM.Standard.E2.1.Micro`. Both are marked *Always Free*.
   - **SSH keys:** download the private key.
   - Click **Create**.
3. Allow web traffic: open the instance's **Subnet → Default Security List → Add Ingress Rules**. Add source `0.0.0.0/0` with TCP destination port `80`, and the same again for port `443`.
4. Open **Cloud Shell** (the `>_` icon at the top of the Oracle console). Run `ssh -i <key> ubuntu@<public IP>` there, or use any terminal.

### 2. Install (one command)
On the server (as `root` or a sudo user), run:
```bash
curl -fsSL https://raw.githubusercontent.com/chrisliew1985-hue/chrisxxxx/claude/relaxed-ride-lkxwvs/scripts/setup_server.sh | bash
```
- It asks for your two WhatsApp numbers, e.g. `60123456789`. Local `012…` numbers are accepted too.
- To use Apple Calendar instead of Google, run it with `CALENDAR=apple` (`curl … | CALENDAR=apple bash`). It then also asks for your Apple ID and an iCloud app-specific password. Those are typed on the server only and never go into GitHub or a chat.
- It installs everything, sets up HTTPS, and starts the server.

### 3. Link both WhatsApps (one time)
```bash
sudo docker compose -f ~/wa-crm/docker-compose.yml logs -f wa-crm
```
- Wait for `[whatsapp] PAIRING CODE: ABCD-EFGH`.
- On that phone, go to *Settings → Linked devices → Link a device → Link with phone number instead* and type the code.
- Repeat for `[business]` in the WhatsApp Business app.
- `connected` in the logs means it worked.
- If a code expires, run `sudo docker compose -f ~/wa-crm/docker-compose.yml restart wa-crm` to get a new one.

### 4. Set up the daily Claude Routine (one time)
In your Claude cloud environment settings (environment menu → **Edit**):
- **Environment variables:**
  - `WA_SERVER_URL`: the `https://…sslip.io` address the installer printed.
  - `WA_SERVER_TOKEN`: the output of `sudo cat ~/wa-crm/data/server_token` on the server. Type it into the settings; don't paste it into a chat.
- **Network access:** add the `…sslip.io` domain to the allowed domains.

Then create a daily Routine at 21:00 with the Notion and Google Calendar connectors and the prompt in [`docs/routine_prompt.md`](docs/routine_prompt.md). Claude can create it for you once the server is running.

**If a WhatsApp gets unlinked**, the Routine's daily summary will warn you. To fix it, run `sudo rm -rf ~/wa-crm/data/auth/business`, restart the container, and link again.

## Option B: Mac only

This option reads the WhatsApp desktop apps' local databases directly, with no linked device. The Mac must be on at the scheduled time.

1. Run `./scripts/install_mac.sh`. It schedules a daily run at 21:00; pass e.g. `8 30` for 08:30.
2. Fill in `~/.wa-crm/.env` (see `.env.example`) and check `~/.wa-crm/config.yaml`, especially `timezone`.
3. Run `~/.wa-crm/venv/bin/python -m wa_crm setup-notion --parent-page <page-id>` and put the printed ID in `.env`.
4. Give Python **Full Disk Access**. The installer prints the path; add it under System Settings → Privacy & Security.
5. Preview with `~/.wa-crm/venv/bin/python -m wa_crm run --dry-run`, then run it for real with `launchctl kickstart gui/$(id -u)/com.wa-crm.daily`.

## Option C: Fully automatic with an Anthropic API key

If you set `ANTHROPIC_API_KEY` in `.env`, the server calls Claude itself every day at `WA_CRM_RUN_AT`, and no Routine is needed. In that mode it writes to Notion with `NOTION_TOKEN` / `NOTION_DATABASE_ID` (create the table with `python -m wa_crm setup-notion --parent-page <id>`). Install it the same way as Option A, with the installer or `docker compose up -d`. Claude costs roughly US$0.50–1.50/day.

## Day-to-day

- Appointments go into your main Google Calendar, or into a separate **"WhatsApp Appointments"** calendar in Apple mode. Titles start with `[Client]`, `[Owner]` or `[Agent]`. Each event's notes include the contact's details, a `wa.me` link and the potential rating.
- If the AI gets a contact wrong in Notion, fix it and tick **Lock** on that contact. Future runs will then leave its Type, Potential and Role alone.
- Each run only looks at messages that arrived since the last run. Claude also sees up to 30 days of earlier chat as context. Re-running is safe: events are matched by a stable ID, so nothing gets duplicated.
- Group chats are skipped by default. To include agent co-broke groups, set `WA_CRM_INCLUDE_GROUPS=true` in the cloud, or `include_groups: true` in `config.yaml` on a Mac.
- Any setting in `config.example.yaml` can be set in the cloud as `WA_CRM_<NAME>`, e.g. `WA_CRM_ALARM_MINUTES=30`.

## Cost

- **Option A:** $0 extra. The Oracle server is Always Free, and the Routine uses your existing Claude plan's usage.
- **Option C:** your server, plus roughly US$0.50–1.50/day for Claude.

## Development

```bash
pip install -r requirements-dev.txt
(cd collector && npm ci)
pytest
node collector/test.mjs
```

| File | Purpose |
| --- | --- |
| `collector/index.js`, `collector/store.js` | Cloud: always-on collector (whatsapp-web.js + headless Chromium in its own container), saves messages to `/data/messages.db` |
| `wa_crm/cloud_store.py` | Cloud: reads the collector's database |
| `wa_crm/whatsapp.py` | Mac: reads `ChatStorage.sqlite` from both WhatsApp desktop apps |
| `wa_crm/extract.py` | Claude prompt and structured output (contact type, potential, appointments) |
| `wa_crm/calendar_icloud.py` | iCloud CalDAV events |
| `wa_crm/crm.py` | Notion / CSV CRM |
| `wa_crm/main.py` | Daily runner, `serve` scheduler and CLI |
| `wa_crm/server.py` | Option A: API the daily Claude Routine calls |
| `docs/routine_prompt.md` | Option A: the Routine's prompt |
| `scripts/setup_server.sh`, `docker-compose.yml`, `Caddyfile` | Option A: one-command server install, HTTPS on port 443 only |
| `Dockerfile`, `scripts/start_cloud.sh` | Cloud: Python container (API for the Routine, or the daily job in API-key mode) |
| `scripts/install_mac.sh` | Mac: venv + launchd daily schedule |
