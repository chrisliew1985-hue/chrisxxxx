// node collector/test.mjs  — unit checks for message parsing.
import assert from 'node:assert/strict'
import { isIgnoredChat, messageText, normalizeJid } from './store.js'

assert.equal(messageText({ type: 'chat', body: 'ok sat 3pm' }), 'ok sat 3pm')
assert.equal(messageText({ type: 'image', body: 'unit plan' }), '[photo] unit plan')
assert.equal(messageText({ type: 'image', body: '' }), '[photo]')
assert.equal(messageText({ type: 'ptt' }), '[voice note]')
assert.equal(messageText({ type: 'reaction', body: '👍' }), null)
assert.equal(messageText({ type: 'e2e_notification' }), null)
assert.equal(messageText({ type: 'sticker' }), null)
assert.equal(messageText({ type: 'document', body: '', _data: { filename: 'SPA.pdf' } }), '[document] SPA.pdf')
assert.match(messageText({ type: 'location', location: { latitude: 3.1, longitude: 101.6, name: 'KLCC' } }),
             /^\[location\] KLCC https:\/\/maps\.google\.com\/\?q=3\.1,101\.6$/)
assert.equal(messageText({ type: 'vcard', body: 'BEGIN:VCARD\nFN:Ah Seng\nEND:VCARD' }), '[contact card] Ah Seng')
assert.equal(normalizeJid('60123456789@c.us'), '60123456789@s.whatsapp.net')
assert.equal(normalizeJid('60123456789:12@c.us'), '60123456789@s.whatsapp.net')
assert.equal(normalizeJid('1203630@g.us'), '1203630@g.us')
assert.ok(isIgnoredChat('status@broadcast'))
assert.ok(!isIgnoredChat('60123456789@c.us'))
console.log('collector tests passed')
