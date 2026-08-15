import { motion, useReducedMotion } from 'framer-motion'
import { AGENT, HERO, TRACKS, WHY, STEPS } from './data.js'

const WaIcon = () => (
  <svg className="wa-ico" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M17.5 14.4c-.3-.2-1.7-.8-2-.9-.3-.1-.5-.2-.7.2-.2.3-.7.9-.9 1.1-.2.2-.3.2-.6.1-1.7-.9-2.9-1.6-4-3.6-.3-.5.3-.5.8-1.6.1-.2 0-.4 0-.5 0-.2-.7-1.6-.9-2.2-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.5s1.1 2.9 1.2 3.1c.2.2 2.1 3.3 5.2 4.6 2 .9 2.7.9 3.7.8.6-.1 1.7-.7 2-1.4.2-.7.2-1.2.2-1.4-.1-.1-.3-.2-.6-.3M12 2a10 10 0 0 0-8.6 15l-1.3 4.8L7 20.5A10 10 0 1 0 12 2" />
  </svg>
)

// Shared scroll-reveal helpers (respect reduced-motion via the `motion` prop below)
const reveal = {
  hidden: { opacity: 0, y: 26 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
}
const stagger = { show: { transition: { staggerChildren: 0.09 } } }

function Reveal({ children, className, as: Tag = motion.div, ...rest }) {
  return (
    <Tag
      className={className}
      variants={reveal}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-60px' }}
      {...rest}
    >
      {children}
    </Tag>
  )
}

export default function App() {
  const noMotion = useReducedMotion()

  return (
    <>
      {/* NAV */}
      <nav className="nav">
        <div className="wrap">
          <div className="brand">
            <span className="mark">CL</span>
            <span>
              {AGENT.name}
              <small>{AGENT.ren} · {AGENT.city}</small>
            </span>
          </div>
          <a className="btn btn-wa" href={AGENT.waLink} target="_blank" rel="noreferrer">
            <WaIcon /> WhatsApp
          </a>
        </div>
      </nav>

      {/* HERO */}
      <header className="hero">
        <div className="wrap">
          <div className="hero-grid">
            <motion.div
              initial={noMotion ? false : 'hidden'}
              animate="show"
              variants={stagger}
            >
              <motion.p className="eyebrow" variants={reveal}>{HERO.eyebrow}</motion.p>
              <motion.h1 className="display" variants={reveal} style={{ margin: '16px 0 20px' }}>
                {HERO.title}
              </motion.h1>
              <motion.p className="lede" variants={reveal}>{HERO.lede}</motion.p>
              <motion.div className="hero-cta" variants={reveal}>
                <a className="btn btn-wa" href={AGENT.waLink} target="_blank" rel="noreferrer">
                  <WaIcon /> Message Chris
                </a>
                <a className="btn btn-ghost" href="#tracks">See both tracks</a>
              </motion.div>
              <motion.div className="hero-tag" variants={reveal}>
                <b>{AGENT.role}</b> · {AGENT.ren}
              </motion.div>
            </motion.div>

            {/* Animated skyline card */}
            <motion.div
              className="viz"
              initial={noMotion ? false : { opacity: 0, scale: 0.94, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
            >
              <div className="sky" />
              <motion.div
                className="sun"
                animate={noMotion ? {} : { y: [0, -8, 0] }}
                transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
              />
              <div className="badge">
                <div>
                  <div className="k">Johor Bahru</div>
                  <div className="s">Live · work · invest</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="k">2 tracks</div>
                  <div className="s">homes + factories</div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </header>

      {/* TRACKS */}
      <section id="tracks">
        <div className="wrap">
          <Reveal className="sec-head" as={motion.div}>
            <p className="eyebrow">What Chris covers</p>
            <h2>One agent, both sides of the market</h2>
            <p className="lede">Most agents pick a lane. Chris runs two — so whether you want a home or a factory, you get local, on-the-ground help.</p>
          </Reveal>

          <motion.div
            className="tracks"
            variants={stagger}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-60px' }}
          >
            {TRACKS.map((t) => (
              <motion.article
                key={t.key}
                className={`track ${t.tone}`}
                variants={reveal}
                whileHover={noMotion ? {} : { y: -6 }}
                transition={{ type: 'spring', stiffness: 260, damping: 22 }}
              >
                <div className="tlabel">{t.label}</div>
                <h3>{t.title}</h3>
                <p>{t.blurb}</p>
                <ul>
                  {t.points.map((p) => (
                    <li key={p}><span className="tick">✓</span>{p}</li>
                  ))}
                </ul>
                <a className="btn btn-dark" href={AGENT.waLink} target="_blank" rel="noreferrer">
                  <WaIcon /> {t.cta}
                </a>
              </motion.article>
            ))}
          </motion.div>
        </div>
      </section>

      {/* WHY / STATS */}
      <section className="why">
        <div className="wrap">
          <Reveal className="sec-head" as={motion.div}>
            <p className="eyebrow">The connectivity story</p>
            <h2>{WHY.title}</h2>
            <p className="lede">{WHY.lede}</p>
          </Reveal>
          <motion.div
            className="stats"
            variants={stagger}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-40px' }}
          >
            {WHY.stats.map((s) => (
              <motion.div className="stat" key={s.l} variants={reveal}>
                <div className="n">{s.n}</div>
                <div className="l">{s.l}</div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* STEPS */}
      <section>
        <div className="wrap">
          <Reveal className="sec-head" as={motion.div}>
            <p className="eyebrow">How it works</p>
            <h2>From first message to keys</h2>
          </Reveal>
          <motion.div
            className="steps"
            variants={stagger}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-40px' }}
          >
            {STEPS.map((s) => (
              <motion.div className="step" key={s.n} variants={reveal}>
                <div className="num">{s.n}</div>
                <h3>{s.t}</h3>
                <p>{s.d}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* CONTACT */}
      <section>
        <div className="wrap">
          <Reveal className="contact" as={motion.div}>
            <p className="eyebrow" style={{ color: 'var(--gold-soft)' }}>Let’s talk</p>
            <h2>Tell Chris what you’re looking for</h2>
            <p>Home in Medini, or factory space through MFS — one WhatsApp is all it takes to start.</p>
            <a className="btn btn-wa" href={AGENT.waLink} target="_blank" rel="noreferrer">
              <WaIcon /> WhatsApp {AGENT.name}
            </a>
            <div className="num">{AGENT.whatsapp}</div>
          </Reveal>
        </div>
      </section>

      <footer>
        <div className="wrap">
          <div className="brand" style={{ justifyContent: 'center' }}>
            <span className="mark">CL</span>
            <span>{AGENT.name}</span>
          </div>
          {AGENT.role} · {AGENT.ren} · {AGENT.city}
          <div style={{ marginTop: 6 }}>Built with React + Framer Motion</div>
        </div>
      </footer>
    </>
  )
}
