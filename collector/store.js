// SQLite storage shared with the Python job (wa_crm/cloud_store.py reads it).
// Kept separate from the WhatsApp client so it can be tested without a browser.

import { DatabaseSync } from 'node:sqlite'

export function openStore(path) {
  const db = new DatabaseSync(path)
  db.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS messages (
      account TEXT NOT NULL, chat_jid TEXT NOT NULL, msg_id TEXT NOT NULL,
      ts INTEGER NOT NULL, from_me INTEGER NOT NULL, sender TEXT, text TEXT NOT NULL,
      PRIMARY KEY (account, chat_jid, msg_id)
    );
    CREATE INDEX IF NOT EXISTS messages_ts ON messages (account, ts);
    CREATE TABLE IF NOT EXISTS contacts (
      account TEXT NOT NULL, jid TEXT NOT NULL, name TEXT, notify TEXT,
      PRIMARY KEY (account, jid)
    );
    CREATE TABLE IF NOT EXISTS lid_map (
      account TEXT NOT NULL, lid TEXT NOT NULL, pn TEXT NOT NULL,
      PRIMARY KEY (account, lid)
    );
    CREATE TABLE IF NOT EXISTS status (
      account TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT, updated_at INTEGER NOT NULL
    );
  `)
  const stmt = {
    msg: db.prepare(`INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)`),
    name: db.prepare(`INSERT INTO contacts (account, jid, name) VALUES (?, ?, ?)
      ON CONFLICT DO UPDATE SET name = excluded.name`),
    notify: db.prepare(`INSERT INTO contacts (account, jid, notify) VALUES (?, ?, ?)
      ON CONFLICT DO UPDATE SET notify = excluded.notify`),
    lid: db.prepare(`INSERT OR REPLACE INTO lid_map VALUES (?, ?, ?)`),
    lidLookup: db.prepare(`SELECT pn FROM lid_map WHERE account = ? AND lid = ?`),
    status: db.prepare(`INSERT OR REPLACE INTO status VALUES (?, ?, ?, ?)`),
  }

  return {
    db,
    setStatus(account, state, detail = null) {
      stmt.status.run(account, state, detail, Math.floor(Date.now() / 1000))
    },
    saveLid(account, lid, pn) {
      if (lid && pn) stmt.lid.run(account, normalizeJid(lid), normalizeJid(pn))
    },
    lookupLid(account, lid) {
      return stmt.lidLookup.get(account, normalizeJid(lid))?.pn ?? null
    },
    saveName(account, jid, name) {
      if (jid && name) stmt.name.run(account, normalizeJid(jid), name)
    },
    saveNotify(account, jid, notify) {
      if (jid && notify) stmt.notify.run(account, normalizeJid(jid), notify)
    },
    // m: { chatJid, id, ts (unix seconds), fromMe, sender, text }
    saveMessage(account, m) {
      if (!m.chatJid || !m.id || !m.ts || !m.text) return false
      return stmt.msg.run(account, normalizeJid(m.chatJid), m.id, m.ts, m.fromMe ? 1 : 0,
        m.fromMe ? 'Me' : (m.sender || null), m.text).changes > 0
    },
  }
}

// whatsapp-web.js uses 6012...@c.us; the Python side expects 6012...@s.whatsapp.net.
export function normalizeJid(jid) {
  if (!jid) return jid
  return jid.replace(/@c\.us$/, '@s.whatsapp.net').replace(/:\d+(?=@)/, '')
}

export function isIgnoredChat(jid) {
  return !jid || jid === 'status@broadcast' || jid.endsWith('@broadcast') || jid.endsWith('@newsletter')
}

const SKIP_TYPES = new Set([
  'e2e_notification', 'notification', 'notification_template', 'gp2', 'call_log',
  'protocol', 'revoked', 'reaction', 'ciphertext', 'pin_message', 'poll_update',
  'broadcast_notification', 'debug', 'unknown',
])

// Turn a whatsapp-web.js Message into the text we store (null = skip it).
export function messageText(msg) {
  const type = msg.type
  if (!type || SKIP_TYPES.has(type)) return null
  const body = (msg.body || '').trim()
  switch (type) {
    case 'chat': return body || null
    case 'image': return body ? `[photo] ${body}` : '[photo]'
    case 'video':
    case 'gif': return body ? `[video] ${body}` : '[video]'
    case 'ptt':
    case 'audio': return '[voice note]'
    case 'document': return `[document] ${body || msg._data?.filename || ''}`.trim()
    case 'sticker': return null
    case 'location': {
      const l = msg.location || {}
      const label = [l.name, l.address, l.description].filter(Boolean).join(', ')
      return `[location] ${label} https://maps.google.com/?q=${l.latitude},${l.longitude}`.replace('  ', ' ')
    }
    case 'vcard':
    case 'multi_vcard': return `[contact card] ${body.match(/FN:(.*)/)?.[1] || ''}`.trim()
    case 'buttons_response':
    case 'list_response': return body || msg.selectedButtonId || null
    default: return body || '[attachment]'
  }
}
