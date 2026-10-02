// Test helper: writes fake whatsapp-web.js messages through the real storage code.
// Usage: DATA_DIR=<dir> node fixture.js <unix-now>
import { join } from 'node:path'
import { messageText, openStore } from './store.js'

const now = Number(process.argv[2])
const store = openStore(join(process.env.DATA_DIR, 'messages.db'))

store.setStatus('whatsapp', 'connected')
store.setStatus('business', 'logged_out', 'Unlinked from the phone.')
store.saveName('whatsapp', '60123456789@c.us', 'Mr Tan (Mont Kiara)')
store.saveName('whatsapp', '1203630@g.us', 'KL Agents Co-broke')
// A contact that only appears under an anonymous @lid id, resolved to their phone.
store.saveLid('whatsapp', '99887766@lid', '60177777777@c.us')

// Same flow as index.js save(): wwebjs message -> text -> store.
const put = (chatJid, m) => {
  const text = messageText(m)
  if (!text) return
  if (!m.fromMe && m._data?.notifyName) store.saveNotify('whatsapp', m.author || chatJid, m._data.notifyName)
  store.saveMessage('whatsapp', { chatJid, id: m.id, ts: m.timestamp, fromMe: m.fromMe,
                                   sender: m._data?.notifyName, text })
}
const tan = '60123456789@c.us'
const lim = store.lookupLid('whatsapp', '99887766@lid')
put(tan, { id: 'a1', type: 'chat', timestamp: now - 10 * 86400, body: 'Looking for 3 room condo, RM1.2m', _data: { notifyName: 'Tan' } })
put(tan, { id: 'a2', type: 'chat', timestamp: now - 5 * 3600, body: 'Can view Saturday 3pm?', _data: { notifyName: 'Tan' } })
put(tan, { id: 'a3', type: 'chat', timestamp: now - 4 * 3600, body: 'Ok confirmed Sat 3pm', fromMe: true })
put(tan, { id: 'a4', type: 'reaction', timestamp: now - 3 * 3600, body: '👍' })
put(tan, { id: 'a3', type: 'chat', timestamp: now - 4 * 3600, body: 'duplicate delivery', fromMe: true })
put(lim, { id: 'b1', type: 'chat', timestamp: now - 2 * 3600, body: 'Hi I am agent Lim, co-broke?', _data: { notifyName: 'Lim PropNex' } })
put(lim, { id: 'b2', type: 'chat', timestamp: now - 3600, body: 'Unit available for viewing' })
put('1203630@g.us', { id: 'g1', type: 'chat', timestamp: now - 3600, body: 'New listing', author: '60188888888@c.us', _data: { notifyName: 'Agent Wong' } })
