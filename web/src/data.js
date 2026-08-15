// Single source of truth for site copy. Edit here — the UI reads from this.
export const AGENT = {
  name: 'Chris Liew',
  role: 'PropNex Real Estate Negotiator',
  ren: 'REN 08014',
  city: 'Johor Bahru',
  whatsapp: '+60103698656',
  waLink: 'https://wa.me/60103698656',
}

export const HERO = {
  eyebrow: 'Johor Bahru property · two tracks, one agent',
  title: 'Homes to live in. Factories to grow in.',
  lede:
    'From Medini condos to Iskandar Puteri landed homes, and turnkey factory space across JB — Chris helps Singapore and local buyers move on the right side of the Causeway.',
}

export const TRACKS = [
  {
    key: 'residential',
    tone: 'clay',
    label: 'Residential',
    title: 'Medini & Iskandar Puteri',
    blurb:
      'High-floor condos, landed homes and new launches in JB’s most connected residential belt — walk-to-mall living, minutes from the Second Link.',
    points: ['Condos & landed homes', 'New launches & sub-sales', 'SG-buyer friendly, from 1.xx mil'],
    cta: 'Ask about homes',
  },
  {
    key: 'industrial',
    tone: 'steel',
    label: 'Industrial — MFS',
    title: 'Malaysia Factory Space',
    blurb:
      'Detached and cluster factories, warehouses and industrial land for manufacturers and SMEs relocating or expanding across the border.',
    points: ['Factories & warehouses', 'High power, high ceiling, loading bays', 'Rent or buy — MFS portfolio'],
    cta: 'Ask about factories',
  },
]

export const WHY = {
  title: 'Why buyers look north',
  lede: 'The Causeway is getting shorter. Connectivity is the story behind every deal.',
  stats: [
    { n: 'RTS', l: 'Link opening — 5-min crossing to Woodlands' },
    { n: '2', l: 'crossings: Causeway + Second Link' },
    { n: '2', l: 'tracks covered — you deal with one agent' },
    { n: '08014', l: 'PropNex REN you can verify' },
  ],
}

export const STEPS = [
  { n: '01', t: 'Tell me the brief', d: 'Budget, purpose, timeline — home to live in or space to run a business.' },
  { n: '02', t: 'Curated shortlist', d: 'I filter the noise and send only what fits, with honest pros and cons.' },
  { n: '03', t: 'Viewings & deal', d: 'On-the-ground viewings, negotiation, and paperwork handled end to end.' },
]
