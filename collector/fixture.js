// Test helper: writes fake WhatsApp events through the real collector code.
// Usage: DATA_DIR=<dir> node fixture.js <unix-now>
const now = Number(process.argv[2])
const c = await import('./index.js')

c.setStatus('whatsapp', 'connected')
c.setStatus('business', 'logged_out', 'Unlinked from the phone.')
c.saveContacts('whatsapp', [{ id: '60123456789@s.whatsapp.net', name: 'Mr Tan (Mont Kiara)' }])
c.saveChatNames('whatsapp', [{ id: '1203630@g.us', name: 'KL Agents Co-broke' }])

const msg = (id, jid, ts, message, extra = {}) => ({
  key: { remoteJid: jid, id, fromMe: false, ...extra.key },
  messageTimestamp: ts, message, pushName: extra.pushName,
})
const tan = '60123456789@s.whatsapp.net'
for (const m of [
  msg('a1', tan, now - 10 * 86400, { conversation: 'Looking for 3 room condo, RM1.2m' }, { pushName: 'Tan' }),
  msg('a2', tan, now - 5 * 3600, { conversation: 'Can view Saturday 3pm?' }, { pushName: 'Tan' }),
  msg('a3', tan, now - 4 * 3600, { conversation: 'Ok confirmed Sat 3pm' }, { key: { fromMe: true } }),
  msg('a4', tan, now - 3 * 3600, { reactionMessage: { text: '👍' } }),
  msg('a3', tan, now - 4 * 3600, { conversation: 'duplicate delivery' }, { key: { fromMe: true } }),
  // Contact who appears under an anonymous @lid id, with the phone number as the alt JID.
  msg('b1', '99887766@lid', now - 2 * 3600, { conversation: 'Hi I am agent Lim, co-broke?' },
      { key: { remoteJidAlt: '60177777777@s.whatsapp.net' }, pushName: 'Lim PropNex' }),
  msg('b2', '99887766@lid', now - 3600, { conversation: 'Unit available for viewing' }),
  msg('g1', '1203630@g.us', now - 3600, { conversation: 'New listing' },
      { key: { participant: '60188888888@s.whatsapp.net' }, pushName: 'Agent Wong' }),
  msg('s1', 'status@broadcast', now - 3600, { conversation: 'my status' }),
]) c.saveMessage('whatsapp', m, 0)
