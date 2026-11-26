export interface ChatResponse {
  prediccion_id: string
  respuesta: string
  intencion: string
  confianza: number
  version_modelo: string
  replica_ia: string | null
  latencia_total_ms: number
  derivar_humano: boolean
  estado_llm?: "pendiente" | "lista" | "degradada"
}

export type ChatPhase = 'idle' | 'loading' | 'success' | 'error' | 'offline'

export const phaseLabels: Record<ChatPhase, string> = {
  idle: 'Esperando tu consulta',
  loading: 'Procesando tu consulta',
  success: 'Respuesta recibida',
  error: 'Solicitud no completada',
  offline: 'Conexión perdida',
}

export class ChatError extends Error {
  constructor(message: string, public readonly kind: 'network' | 'http' | 'contract' | 'timeout') {
    super(message)
    this.name = 'ChatError'
  }
}

export function isChatResponse(value: unknown): value is ChatResponse {
  if (!value || typeof value !== 'object') return false
  const data = value as Record<string, unknown>
  return ['prediccion_id', 'respuesta', 'intencion', 'version_modelo'].every(
    (key) => typeof data[key] === 'string' && data[key].trim().length > 0,
  ) && typeof data.confianza === 'number' && Number.isFinite(data.confianza)
    && data.confianza >= 0 && data.confianza <= 1
    && typeof data.latencia_total_ms === 'number' && Number.isFinite(data.latencia_total_ms)
    && data.latencia_total_ms >= 0 && typeof data.derivar_humano === 'boolean'
    && (data.replica_ia === null || typeof data.replica_ia === 'string')
    && (data.estado_llm === undefined || ['pendiente', 'lista', 'degradada'].includes(data.estado_llm as string))
}

export async function sendChat(mensaje: string, signal?: AbortSignal): Promise<ChatResponse> {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const timeout = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, 12_000)

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mensaje }),
      signal: controller.signal,
    })
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : null
      throw new ChatError(
        typeof detail === 'string' ? detail : `El servicio no pudo completar la solicitud (HTTP ${response.status}).`,
        'http',
      )
    }
    if (!isChatResponse(data)) {
      throw new ChatError('El servicio devolvió una respuesta incompleta o inválida. No hay un resultado confirmado.', 'contract')
    }
    return data
  } catch (error) {
    if (timedOut) throw new ChatError('Se agotó el tiempo de espera. No se pudo confirmar la respuesta.', 'timeout')
    if (error instanceof ChatError || signal?.aborted) throw error
    throw new ChatError('No se pudo conectar con el servicio. Revisa tu conexión o inténtalo más tarde.', 'network')
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
  }
}

export async function waitForLlm(id: string, signal: AbortSignal): Promise<string | null> {
  const deadline = performance.now() + 27_000
  try {
    while (!signal.aborted && performance.now() < deadline) {
      const timeout = Math.max(1, Math.ceil(Math.min(3000, deadline - performance.now())))
      const response = await fetch(`/api/chat/respuesta/${encodeURIComponent(id)}`, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
        cache: 'no-store',
      })
      if (!response.ok) return null
      const result: unknown = await response.json()
      if (!result || typeof result !== 'object' || !('estado_llm' in result)) return null
      if (result.estado_llm === 'lista') {
        return 'respuesta_llm' in result && typeof result.respuesta_llm === 'string' && result.respuesta_llm.trim()
          ? result.respuesta_llm : null
      }
      if (result.estado_llm !== 'pendiente') return null
      await new Promise<void>(resolve => {
        const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve() }
        const timer = setTimeout(done, 500)
        signal.addEventListener('abort', done, { once: true })
        if (signal.aborted) done()
      })
    }
  } catch {
    // Fallo de red, timeout o JSON inválido: conservar la orientación inicial.
    // Nunca reenviar el POST ni inventar una respuesta generada.
  }
  return null
}
