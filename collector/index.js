// Always-on WhatsApp collector for the cloud.
//
// Links to each WhatsApp account as a "linked device" (like WhatsApp Web) and
// saves every text message into a SQLite file that the Python daily job reads.
// It never sends anything.
//
// Env:
//   WA_ACCOUNTS=whatsapp,business       account labels (one linked device each)
//   WA_PHONE_WHATSAPP=60123456789        phone for pairing-code login (digits, with country code)
//   WA_PHONE_BUSINESS=60198765432
//   DATA_DIR=/data                       auth sessions + messages.db live here
//   HISTORY_DAYS=45                      how much past history to keep from the first sync

import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  fetchLatestWaWebVersion,
  getContentType,
  isJidBroadcast,
  isJidNewsletter,
  isJidStatusBroadcast,
  isLidUser,
  jidNormalizedUser,
  normalizeMessageContent,
  useMultiFileAuthState,
} from 'baileys'
import pino from 'pino'
import qrcode from 'qrcode-terminal'

const DATA_DIR = process.env.DATA_DIR || '/data'
const ACCOUNTS = (process.env.WA_ACCOUNTS || 'whatsapp,business').split(',').map(s => s.trim()).filter(Boolean)
const HISTORY_DAYS = Number(process.env.HISTORY_DAYS || 45)
const CONNECT_TIMEOUT_MS = Number(process.env.CONNECT_TIMEOUT_MS || 90_000)
const logger = pino({ level: process.env.LOG_LEVEL || 'warn' })

mkdirSync(DATA_DIR, { recursive: true })
const db = openDb(join(DATA_DIR, 'messages.db'))

export function openDb(path) {
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
  return db
}

const stmt = {
  msg: db.prepare(`INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)`),
  contactName: db.prepare(`INSERT INTO contacts (account, jid, name) VALUES (?, ?, ?)
    ON CONFLICT DO UPDATE SET name = excluded.name`),
  contactNotify: db.prepare(`INSERT INTO contacts (account, jid, notify) VALUES (?, ?, ?)
    ON CONFLICT DO UPDATE SET notify = excluded.notify`),
  lid: db.prepare(`INSERT OR REPLACE INTO lid_map VALUES (?, ?, ?)`),
  lidLookup: db.prepare(`SELECT pn FROM lid_map WHERE account = ? AND lid = ?`),
  status: db.prepare(`INSERT OR REPLACE INTO status VALUES (?, ?, ?, ?)`),
}

export function setStatus(account, state, detail = null) {
  stmt.status.run(account, state, detail, Math.floor(Date.now() / 1000))
}

// Prefer phone-number JIDs over anonymous @lid ones so the CRM gets a phone number.
function resolveJid(account, jid, alt) {
  if (!jid) return null
  jid = jidNormalizedUser(jid)
  if (!isLidUser(jid)) return jid
  if (alt && !isLidUser(alt)) {
    stmt.lid.run(account, jid, jidNormalizedUser(alt))
    return jidNormalizedUser(alt)
  }
  return stmt.lidLookup.get(account, jid)?.pn ?? jid
}

const SKIP_TYPES = new Set([
  'protocolMessage', 'reactionMessage', 'senderKeyDistributionMessage',
  'pollUpdateMessage', 'keepInChatMessage', 'messageContextInfo',
])

export function messageText(message) {
  const content = normalizeMessageContent(message)
  if (!content) return null
  const type = getContentType(content)
  if (!type || SKIP_TYPES.has(type)) return null
  const m = content[type]
  switch (type) {
    case 'conversation': return content.conversation
    case 'extendedTextMessage': return m.text
    case 'imageMessage': return m.caption ? `[photo] ${m.caption}` : '[photo]'
    case 'videoMessage': return m.caption ? `[video] ${m.caption}` : '[video]'
    case 'documentMessage':
    case 'documentWithCaptionMessage':
      return `[document] ${m.caption || m.fileName || ''}`.trim()
    case 'audioMessage': return '[voice note]'
    case 'locationMessage':
    case 'liveLocationMessage':
      return `[location] ${[m.name, m.address].filter(Boolean).join(', ')} ` +
        `https://maps.google.com/?q=${m.degreesLatitude},${m.degreesLongitude}`
    case 'contactMessage': return `[contact card] ${m.displayName || ''}`
    case 'buttonsResponseMessage': return m.selectedDisplayText
    case 'listResponseMessage': return m.title
    case 'templateButtonReplyMessage': return m.selectedDisplayText
    default: return '[attachment]'
  }
}

export function saveMessage(account, msg, minTs) {
  const key = msg.key
  if (!key?.remoteJid || !key.id) return
  const raw = key.remoteJid
  if (isJidBroadcast(raw) || isJidStatusBroadcast(raw) || isJidNewsletter(raw)) return
  const ts = Number(msg.messageTimestamp ?? 0)
  if (!ts || ts < minTs) return
  const text = messageText(msg.message)
  if (!text) return

  const chatJid = resolveJid(account, raw, key.remoteJidAlt)
  const fromMe = key.fromMe ? 1 : 0
  if (!fromMe && msg.pushName) {
    const senderJid = resolveJid(account, key.participant || raw, key.participantAlt || key.remoteJidAlt)
    stmt.contactNotify.run(account, senderJid, msg.pushName)
  }
  stmt.msg.run(account, chatJid, key.id, ts, fromMe, fromMe ? 'Me' : (msg.pushName || null), text)
}

export function saveContacts(account, contacts) {
  for (const c of contacts) {
    if (c.lid && c.phoneNumber) stmt.lid.run(account, jidNormalizedUser(c.lid), jidNormalizedUser(c.phoneNumber))
    const jid = resolveJid(account, c.phoneNumber || c.id, null)
    if (!jid) continue
    if (c.name) stmt.contactName.run(account, jid, c.name)
    else if (c.notify || c.verifiedName) stmt.contactNotify.run(account, jid, c.notify || c.verifiedName)
  }
}

// Group subjects (and some contact names) arrive on chat objects.
export function saveChatNames(account, chats) {
  for (const c of chats) {
    if (!c.id || !c.name) continue
    const jid = resolveJid(account, c.id, c.pnJid)
    if (jid.endsWith('@g.us')) stmt.contactName.run(account, jid, c.name)
    else stmt.contactNotify.run(account, jid, c.name)
  }
}

// WhatsApp rejects clients that announce an outdated WhatsApp Web version (the socket
// closes straight away with "Connection Terminated"), so ask for the current one.
// WA_VERSION=2,3000,1012345678 overrides it if ever needed.
let waVersion
async function currentWaVersion() {
  if (process.env.WA_VERSION) return process.env.WA_VERSION.split(',').map(Number)
  if (waVersion) return waVersion
  for (const fetcher of [fetchLatestWaWebVersion, fetchLatestBaileysVersion]) {
    try {
      const { version, error } = await fetcher()
      if (version && !error) {
        waVersion = version
        console.log(`Using WhatsApp Web version ${version.join('.')}`)
        return waVersion
      }
    } catch {}
  }
  console.log('Could not look up the current WhatsApp Web version; using the built-in one')
  return undefined
}

async function connect(account, attempt = 0) {
  const { state, saveCreds } = await useMultiFileAuthState(join(DATA_DIR, 'auth', account))
  const phone = (process.env[`WA_PHONE_${account.toUpperCase()}`] || '').replace(/\D/g, '')

  const version = await currentWaVersion()
  const sock = makeWASocket({
    ...(version ? { version } : {}),
    auth: state,
    logger,
    browser: Browsers.macOS('Desktop'),   // "Desktop" gets a fuller history sync on first link
    syncFullHistory: true,
    markOnlineOnConnect: false,           // don't show you as "online" or affect phone notifications
  })
  sock.ev.on('creds.update', saveCreds)

  // Baileys can hang in "connecting" forever on a bad network, so give up and
  // retry if the link isn't open in time (unless we're waiting for you to link it).
  let opened = false
  let waitingForLink = false
  const watchdog = setTimeout(() => {
    if (!opened && !waitingForLink) sock.end(new Error('connect timeout'))
  }, CONNECT_TIMEOUT_MS)

  let pairingRequested = false
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      waitingForLink = true
      setStatus(account, 'waiting_for_link')
      if (phone && !pairingRequested) {
        pairingRequested = true
        try {
          const code = await sock.requestPairingCode(phone)
          console.log(`\n[${account}] PAIRING CODE: ${code}\n` +
            `  On the phone with this WhatsApp: Settings > Linked devices > Link a device >\n` +
            `  "Link with phone number instead", then enter the code above.\n`)
        } catch (e) {
          console.error(`[${account}] could not get pairing code: ${e.message}`)
        }
      } else if (!phone) {
        console.log(`\n[${account}] Scan this QR in WhatsApp > Settings > Linked devices:`)
        qrcode.generate(qr, { small: true })
      }
    }
    if (connection === 'open') {
      opened = true
      clearTimeout(watchdog)
      attempt = 0
      setStatus(account, 'connected')
      console.log(`[${account}] connected as ${sock.user?.id}`)
    }
    if (connection === 'close') {
      clearTimeout(watchdog)
      const code = lastDisconnect?.error?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        setStatus(account, 'logged_out', 'Unlinked from the phone. Delete the auth folder and re-link.')
        console.error(`[${account}] LOGGED OUT. Remove ${join(DATA_DIR, 'auth', account)} and restart to re-link.`)
        return
      }
      const reason = `${lastDisconnect?.error?.message || 'closed'} (code ${code})`
      setStatus(account, 'reconnecting', reason)
      if (code === 405 || code === 426) waVersion = undefined   // version rejected: look it up again
      console.log(`[${account}] disconnected (${reason}); retrying`)
      const delay = Math.min(60_000, 2_000 * 2 ** attempt)
      setTimeout(() => connect(account, attempt + 1).catch(console.error), delay)
    }
  })

  const historyMin = () => Math.floor(Date.now() / 1000) - HISTORY_DAYS * 86400

  sock.ev.on('lid-mapping.update', ({ lid, pn }) => stmt.lid.run(account, jidNormalizedUser(lid), jidNormalizedUser(pn)))
  sock.ev.on('contacts.upsert', contacts => saveContacts(account, contacts))
  sock.ev.on('contacts.update', contacts => saveContacts(account, contacts))
  sock.ev.on('chats.upsert', chats => saveChatNames(account, chats))
  sock.ev.on('messaging-history.set', ({ chats, contacts, messages, lidPnMappings }) => {
    for (const { lid, pn } of lidPnMappings || []) stmt.lid.run(account, jidNormalizedUser(lid), jidNormalizedUser(pn))
    saveContacts(account, contacts || [])
    saveChatNames(account, chats || [])
    const min = historyMin()
    for (const m of messages || []) saveMessage(account, m, min)
    console.log(`[${account}] history sync: ${messages?.length || 0} messages`)
  })
  sock.ev.on('messages.upsert', ({ messages }) => {
    for (const m of messages) saveMessage(account, m, 0)
  })
}

if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(`WhatsApp collector starting for: ${ACCOUNTS.join(', ')}`)
  setInterval(() => {}, 60_000)   // keep the process alive between reconnects
  for (const account of ACCOUNTS) {
    setStatus(account, 'starting')
    connect(account).catch(e => {
      console.error(`[${account}] failed to start:`, e)
      setStatus(account, 'error', e.message)
    })
  }
}
