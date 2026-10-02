// Always-on WhatsApp collector for the cloud (read-only: it never sends anything).
//
// Each account runs WhatsApp Web in a headless Chromium via whatsapp-web.js (the same
// approach as common WA tools), linked as a "linked device" with a pairing code.
// Text of every message is saved to /data/messages.db for the Python job.
//
// Env:
//   WA_ACCOUNTS=whatsapp,business       account labels (one linked device each)
//   WA_PHONE_WHATSAPP=60123456789        phone for pairing-code login (digits, with country code)
//   WA_PHONE_BUSINESS=60198765432
//   DATA_DIR=/data                       login sessions + messages.db live here
//   HISTORY_DAYS=45                      how far back to load chat history on each start

import { mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import pkg from 'whatsapp-web.js'
import qrcode from 'qrcode-terminal'
import { isIgnoredChat, messageText, normalizeJid, openStore } from './store.js'

const { Client, LocalAuth } = pkg

const DATA_DIR = process.env.DATA_DIR || '/data'
const ACCOUNTS = (process.env.WA_ACCOUNTS || 'whatsapp,business').split(',').map(s => s.trim()).filter(Boolean)
const HISTORY_DAYS = Number(process.env.HISTORY_DAYS || 45)
const HISTORY_PER_CHAT = Number(process.env.HISTORY_PER_CHAT || 150)

mkdirSync(DATA_DIR, { recursive: true })
const store = openStore(join(DATA_DIR, 'messages.db'))

// Prefer phone-number IDs over anonymous @lid ones so the CRM gets a phone number.
async function resolveJid(account, client, jid) {
  if (!jid || !jid.endsWith('@lid')) return normalizeJid(jid)
  const known = store.lookupLid(account, jid)
  if (known) return known
  try {
    const [res] = await client.getContactLidAndPhone([jid])
    if (res?.pn) {
      store.saveLid(account, jid, res.pn)
      return normalizeJid(res.pn)
    }
  } catch {}
  return normalizeJid(jid)
}

async function save(account, client, msg) {
  const raw = msg.fromMe ? msg.to : msg.from
  if (isIgnoredChat(raw)) return
  const text = messageText(msg)
  if (!text) return
  const chatJid = await resolveJid(account, client, raw)
  const notify = msg._data?.notifyName
  if (!msg.fromMe && notify) {
    const senderJid = await resolveJid(account, client, msg.author || msg.from)
    store.saveNotify(account, senderJid, notify)
  }
  store.saveMessage(account, {
    chatJid, id: msg.id?._serialized || msg.id?.id, ts: msg.timestamp,
    fromMe: msg.fromMe, sender: notify, text,
  })
}

const sleep = ms => new Promise(r => setTimeout(r, ms))

// Load recent history (also fills any gap while the server or WhatsApp was down).
// Right after linking, WhatsApp Web is still syncing and getChats() can fail, so retry.
async function backfill(account, client) {
  const since = Date.now() / 1000 - HISTORY_DAYS * 86400
  let chats = null
  for (const wait of [15_000, 30_000, 60_000, 120_000, 300_000]) {
    await sleep(wait)
    try {
      chats = await client.getChats()
      break
    } catch (e) {
      console.log(`[${account}] chat list not ready yet (${e.message || e}); retrying`)
    }
  }
  if (!chats) {
    console.error(`[${account}] could not load chat history; new messages are still saved`)
    return
  }
  let saved = 0
  for (const chat of chats) {
    const id = chat.id?._serialized
    if (isIgnoredChat(id) || !chat.timestamp || chat.timestamp < since) continue
    try {
      const jid = await resolveJid(account, client, id)
      if (chat.name) store.saveName(account, jid, chat.name)
      const msgs = await chat.fetchMessages({ limit: HISTORY_PER_CHAT })
      for (const m of msgs) {
        if (m.timestamp >= since) {
          await save(account, client, m)
          saved++
        }
      }
    } catch (e) {
      console.error(`[${account}] history for ${chat.name || id} failed: ${e.message}`)
    }
  }
  console.log(`[${account}] history loaded: ${saved} messages from ${chats.length} chats`)
}

// A browser that died without shutting down (container restart, crash) leaves lock
// files behind, and the next Chromium refuses to open the profile ("profile appears
// to be in use"). Nothing else uses this profile, so clear them before launching.
function clearProfileLocks(account) {
  const dir = join(DATA_DIR, 'wwebjs-auth', `session-${account}`)
  for (const f of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
    try { rmSync(join(dir, f), { force: true }) } catch {}
  }
}

function start(account, attempt = 0) {
  clearProfileLocks(account)
  const phone = (process.env[`WA_PHONE_${account.toUpperCase()}`] || '').replace(/\D/g, '')
  const client = new Client({
    authStrategy: new LocalAuth({ clientId: account, dataPath: join(DATA_DIR, 'wwebjs-auth') }),
    ...(phone ? { pairWithPhoneNumber: { phoneNumber: phone, showNotification: true } } : {}),
    puppeteer: {
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
             '--disable-gpu', '--no-zygote', '--disable-extensions'],
    },
  })

  client.on('code', code => {
    store.setStatus(account, 'waiting_for_link')
    const pretty = code.length === 8 ? `${code.slice(0, 4)}-${code.slice(4)}` : code
    console.log(`\n[${account}] PAIRING CODE: ${pretty}\n` +
      `  On the phone with this WhatsApp: Settings > Linked devices > Link a device >\n` +
      `  "Link with phone number instead", then enter the code above.\n` +
      `  (A new code appears every few minutes until it's linked.)\n`)
  })
  client.on('qr', qr => {
    if (phone) return
    store.setStatus(account, 'waiting_for_link')
    console.log(`\n[${account}] Scan this QR in WhatsApp > Settings > Linked devices:`)
    qrcode.generate(qr, { small: true })
  })
  client.on('authenticated', () => console.log(`[${account}] linked, loading...`))
  client.on('auth_failure', m => {
    store.setStatus(account, 'logged_out', `Login failed: ${m}`)
    console.error(`[${account}] login failed: ${m}`)
  })
  client.on('ready', () => {
    attempt = 0
    store.setStatus(account, 'connected')
    console.log(`[${account}] connected as ${client.info?.wid?.user || ''}`)
    backfill(account, client).catch(e => console.error(`[${account}] history failed: ${e.message}`))
  })
  // If the full chat list can't be loaded (a known WhatsApp Web quirk), still give
  // Claude context: the first time a chat gets a new message, load that chat's history.
  const loadedChats = new Set()
  async function loadChatHistory(msg) {
    const key = msg.fromMe ? msg.to : msg.from
    if (!key || loadedChats.has(key) || isIgnoredChat(key)) return
    loadedChats.add(key)
    const since = Date.now() / 1000 - HISTORY_DAYS * 86400
    const chat = await msg.getChat()
    const jid = await resolveJid(account, client, key)
    if (chat?.name) store.saveName(account, jid, chat.name)
    for (const m of await chat.fetchMessages({ limit: HISTORY_PER_CHAT })) {
      if (m.timestamp >= since) await save(account, client, m)
    }
  }

  client.on('message_create', msg => {
    save(account, client, msg).catch(e => console.error(`[${account}] save failed: ${e.message}`))
    loadChatHistory(msg).catch(e => console.error(`[${account}] chat history failed: ${e.message || e}`))
  })
  client.on('disconnected', async reason => {
    const loggedOut = String(reason).toUpperCase().includes('LOGOUT')
    store.setStatus(account, loggedOut ? 'logged_out' : 'reconnecting', String(reason))
    console.error(`[${account}] disconnected: ${reason}`)
    try { await client.destroy() } catch {}
    if (loggedOut) {
      // Unlinked (or a pairing attempt was cancelled): start over so a fresh pairing
      // code is shown. The status stays "logged_out" so the daily summary warns.
      console.error(`[${account}] not linked; a new pairing code will follow`)
      setTimeout(() => start(account, 0), 10_000)
      return
    }
    restart(account, attempt + 1)
  })

  store.setStatus(account, 'starting')
  client.initialize().catch(async e => {
    store.setStatus(account, 'reconnecting', e.message)
    console.error(`[${account}] failed to start: ${e.message}`)
    try { await client.destroy() } catch {}
    restart(account, attempt + 1)
  })
}

function restart(account, attempt) {
  const delay = Math.min(300_000, 5_000 * 2 ** Math.min(attempt, 6))
  console.log(`[${account}] retrying in ${Math.round(delay / 1000)}s`)
  setTimeout(() => start(account, attempt), delay)
}

// whatsapp-web.js sometimes throws from inside the browser bridge (e.g. "Execution
// context was destroyed" while WhatsApp Web reloads). Log it instead of crashing the
// whole collector, which would also reset the other account's pairing.
process.on('unhandledRejection', e => console.error('ignored error:', e?.message || e))
process.on('uncaughtException', e => console.error('ignored error:', e?.message || e))

console.log(`WhatsApp collector starting for: ${ACCOUNTS.join(', ')}`)
setInterval(() => {}, 60_000)   // keep the process alive between restarts
// Start one at a time so two browsers don't boot at once on a small server.
ACCOUNTS.forEach((account, i) => setTimeout(() => start(account), i * 20_000))
