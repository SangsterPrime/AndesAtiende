import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ChatError, phaseLabels, sendChat, type ChatPhase, type ChatResponse } from '../lib/chat'
import { useReducedMotion } from '../hooks/useReducedMotion'
import { ResponseDetails } from './ResponseDetails'
import { Icon } from './Icon'

type Message = { id: number; role: 'user'; text: string } | { id: number; role: 'assistant'; data: ChatResponse }
const suggestions = [
  ['Sin internet', 'Me quedé sin internet'],
  ['Mi factura', 'Quiero revisar mi factura'],
  ['Cambiar de plan', 'Quiero cambiarme a otro plan'],
  ['Atención humana', 'Quiero hablar con una persona real'],
] as const

export function Chat({ online, phase, onPhaseChange }: { online: boolean; phase: ChatPhase; onPhaseChange: (phase: ChatPhase) => void }) {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<{ message: string; query: string } | null>(null)
  const [validation, setValidation] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const request = useRef<AbortController | null>(null)
  const nextId = useRef(1)
  const reducedMotion = useReducedMotion()

  useEffect(() => () => request.current?.abort(), [])
  useEffect(() => {
    log.current?.scrollTo?.({ top: log.current.scrollHeight, behavior: reducedMotion ? 'instant' : 'smooth' })
  }, [messages, pending, failure, reducedMotion])

  async function submit(query: string, retry = false) {
    const text = query.trim()
    if (request.current || !online) return
    if (text.length < 3 || text.length > 1200) {
      setValidation('Escribe entre 3 y 1200 caracteres, sin contar espacios al inicio o al final.')
      input.current?.focus()
      return
    }
    setValidation('')
    setFailure(null)
    setPending(true)
    onPhaseChange('loading')
    if (!retry) {
      const id = nextId.current++
      setMessages((current) => [...current, { id, role: 'user', text }])
      setDraft('')
    }
    const controller = new AbortController()
    request.current = controller
    try {
      const data = await sendChat(text, controller.signal)
      if (controller.signal.aborted) return
      const id = nextId.current++
      setMessages((current) => [...current, { id, role: 'assistant', data }])
      onPhaseChange('success')
    } catch (error) {
      if (controller.signal.aborted) return
      setFailure({ message: error instanceof ChatError ? error.message : 'No se pudo completar la consulta.', query: text })
      onPhaseChange(error instanceof ChatError && error.kind === 'network' ? 'offline' : 'error')
    } finally {
      if (!controller.signal.aborted) {
        setPending(false)
        request.current = null
      }
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void submit(draft)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit(draft)
    }
  }

  return (
    <section id="conversacion" className="chat-panel" aria-label="Conversación con AndesAtiende">
      <header className="chat-header">
        <div className="flex items-center gap-3"><span className="assistant-avatar"><Icon name="spark" /></span><div><h2>AndesAtiende</h2><p>Asistente de telecomunicaciones</p></div></div>
        <span className="demo-tag">DEMO EP2</span>
      </header>
      <div className="chat-status" role="status"><span className={`status-dot ${phase}`} /><span>{phaseLabels[phase]}</span><span className="status-protocol">POST /api/chat</span></div>
      <div className="messages" role="log" aria-label="Mensajes de la conversación" aria-live="polite" aria-relevant="additions" aria-busy={pending} ref={log} tabIndex={0}>
        <article className="message assistant-message">
          <span className="message-label">ANDESATIENDE</span>
          <p>Hola, qué bueno tenerte aquí <span aria-hidden="true">✦</span></p>
          <p>Soy tu asistente de Andesnet. Cuéntame qué necesitas y te ayudaré a orientar tu consulta.</p>
          <p className="welcome-note">Puedes preguntar por tu conexión, facturación o planes, o solicitar atención humana.</p>
        </article>
        {messages.map((message) => (
          <article key={message.id} className={`message ${message.role === 'user' ? 'user-message' : 'assistant-message'}`}>
            <span className="message-label">{message.role === 'user' ? 'TÚ' : 'ANDESATIENDE'}</span>
            <p>{message.role === 'user' ? message.text : message.data.respuesta}</p>
            {message.role === 'assistant' && <>
              <p className={`handoff-note ${message.data.derivar_humano ? 'requested' : ''}`}>{message.data.derivar_humano ? 'Derivación registrada. Esta demo no conecta con Genesys ni con un ejecutivo.' : 'Derivación humana: no solicitada.'}</p>
              <ResponseDetails data={message.data} />
            </>}
          </article>
        ))}
        {pending && <div className="loading-message"><span className="loading-dots" aria-hidden="true">•••</span> Consultando el clasificador…</div>}
      </div>
      {failure && <div className="error-notice" role="alert"><p>{failure.message}</p><p>No se reenvió automáticamente; la consulta pudo haberse registrado.</p><button type="button" onClick={() => void submit(failure.query, true)} disabled={!online || pending}>Reenviar consulta <span aria-hidden="true">↗</span></button></div>}
      {!online && <p className="offline-notice" role="alert">No hay conexión de red. Tu conversación sigue aquí; podrás enviar cuando se restablezca.</p>}
      <div className="composer-area">
        <div className="suggestions" aria-label="Consultas sugeridas">
          {suggestions.map(([label, query]) => <button key={label} type="button" disabled={pending} onClick={() => { setDraft(query); setValidation(''); input.current?.focus() }}>{label}<span aria-hidden="true">↗</span></button>)}
        </div>
        <form onSubmit={handleSubmit} noValidate>
          <label className="sr-only" htmlFor="mensaje">Tu consulta</label>
          <div className={`composer ${validation ? 'invalid' : ''}`}>
            <textarea id="mensaje" ref={input} value={draft} onChange={(event) => { setDraft(event.target.value); setValidation('') }} onKeyDown={handleKeyDown} maxLength={1200} rows={2} placeholder="Escribe tu consulta aquí…" aria-describedby="composer-help message-validation" aria-invalid={!!validation} />
            <button className="send-button" type="submit" disabled={pending || !online || !draft.trim()} aria-label="Enviar consulta"><Icon name="send" size={22} /></button>
          </div>
          <p id="message-validation" className="validation-message" role={validation ? 'alert' : undefined}>{validation}</p>
          <div id="composer-help" className="composer-help"><span>Enter para enviar <span aria-hidden="true">·</span> Shift + Enter para nueva línea</span><span>{draft.length}/1200</span></div>
        </form>
      </div>
      <footer className="chat-footer"><Icon name="shield" size={14} /><span>No compartas RUT, contraseñas ni datos bancarios.</span></footer>
    </section>
  )
}
