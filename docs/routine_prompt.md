# Daily Claude Routine prompt

This prompt is what the daily Claude Routine runs (on your Claude plan, no API key).
The Routine's cloud environment needs:

- **Environment variables:** `WA_SERVER_URL` (e.g. `https://141-147-12-34.sslip.io`) and
  `WA_SERVER_TOKEN` (from `sudo cat ~/wa-crm/data/server_token` on the server).
- **Network access:** your server's domain (e.g. `141-147-12-34.sslip.io`) added to the allowed domains.
- **Connector:** Notion.

---

```
Daily WhatsApp → Apple Calendar + Notion CRM sync. You only READ chats; never send WhatsApp messages.
Never print or echo $WA_SERVER_TOKEN.

Server: $WA_SERVER_URL   Auth header: "Authorization: Bearer $WA_SERVER_TOKEN"
Notion CRM data source: collection://bc45d57f-35f9-407f-8992-2ff6df80fd26  ("WhatsApp CRM")

Repeat up to 10 rounds:
1. curl -sf -H "Authorization: Bearer $WA_SERVER_TOKEN" "$WA_SERVER_URL/pending?limit=15" -o batch.json
   If "chats" is empty, stop looping.
2. Read batch.json. Follow its "instructions" exactly. For every chat, read the whole "transcript"
   and write an analysis that matches "result_schema". Be strict: an appointment is "confirmed"
   only with clear agreement on a specific date AND time.
3. Write {"batch_id": ..., "results": [{"id": ..., "analysis": {...}}, ...]} to results.json and
   curl -sf -X POST -H "Authorization: Bearer $WA_SERVER_TOKEN" -H "Content-Type: application/json"
        --data @results.json "$WA_SERVER_URL/results" -o reply.json
   The server writes confirmed appointments to Apple Calendar itself.
   If reply.json has "errors", fix those analyses and POST just those ids again (same batch_id).
4. For each row in reply.json "crm", upsert into the Notion CRM:
   - Find the page whose "WhatsApp ID" equals whatsapp_id.
   - Set Name, Phone, WhatsApp ID, Summary, Potential Reason, Last Contact (date only),
     Requirements / Properties / Next Step (only if not null), Next Appointment
     (datetime, Asia/Kuala_Lumpur, only if not null), and add the row's accounts to "WhatsApp Account"
     (keep existing values).
   - Set Type, Potential and Role only if the page's "Lock" checkbox is NOT ticked.
   - Create the page if none exists.

Finish with a short summary: appointments added / removed (title + time), contacts updated by type
(Client / Owner / Agent) with Hot ones listed first, and a warning if "whatsapp_status" shows any
account that is not "connected" (it needs re-linking on the server).
```
