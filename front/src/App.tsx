import { useEffect, useState } from 'react'
import { Chat } from './components/Chat'
import { Icon } from './components/Icon'
import { Orb } from './components/Orb'
import { phaseLabels, type ChatPhase } from './lib/chat'

export default function App() {
  const [phase, setPhase] = useState<ChatPhase>('idle')
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const connected = () => { setOnline(true); setPhase((current) => current === 'offline' ? 'idle' : current) }
    const disconnected = () => setOnline(false)
    window.addEventListener('online', connected)
    window.addEventListener('offline', disconnected)
    return () => { window.removeEventListener('online', connected); window.removeEventListener('offline', disconnected) }
  }, [])
  const effectivePhase = online ? phase : 'offline'

  return (
    <div className="app-shell">
      <a className="skip-link" href="#mensaje">Ir al chat</a>
      <header className="site-header">
        <a className="brand" href="/" aria-label="AndesAtiende, inicio"><span className="brand-mark" aria-hidden="true">A<span /></span><span>andes<span className="brand-accent">atiende</span><span className="brand-period">.</span></span></a>
        <div className="header-caption"><span className="tiny-dot" /> TECNOLOGÍA QUE TE ACERCA</div>
        <a className="header-link" href="#alcance">Sobre esta demo <Icon name="arrow" size={15} /></a>
      </header>
      <main className="main-layout">
        <section className="intro" aria-labelledby="intro-title">
          <div className="eyebrow"><span /> CONECTAMOS CONTIGO</div>
          <h1 id="intro-title">Tu mundo conectado.<br /><span>Tu atención,</span><br /><span className="headline-accent">más simple.</span></h1>
          <p className="intro-description">Una nueva forma de resolver tus dudas de telecomunicaciones. Cuéntanos qué necesitas; empecemos por escucharte.</p>
          <div className="orb-container">
            <Orb phase={effectivePhase} />
            <div className="orb-caption"><span className={`status-dot ${effectivePhase}`} /><span>{phaseLabels[effectivePhase]}</span></div>
            <span className="orb-footnote">ASISTENCIA IMPULSADA POR MACHINE LEARNING</span>
          </div>
          <div className="intro-features"><span><Icon name="chat" size={16} /> Lenguaje natural</span><span><Icon name="signal" size={16} /> Clasificación de intención</span></div>
        </section>
        <Chat online={online} phase={effectivePhase} onPhaseChange={setPhase} />
      </main>
      <footer className="site-footer" id="alcance">
        <div><span className="footer-title">Personas primero. Tecnología al servicio.</span><p>Prototipo académico · EP2 · Equipo 05</p></div>
        <p className="scope-note">Demo sin autenticación ni acceso a cuentas reales. No realiza operaciones comerciales ni conecta con Genesys. La confianza indica la clasificación del modelo, no la certeza de una solución.</p>
      </footer>
    </div>
  )
}
