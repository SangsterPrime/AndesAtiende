export interface ChatResponse {
  prediccion_id: string
  respuesta: string
  intencion: string
  confianza: number
  version_modelo: string
  replica_ia: string | null
  latencia_total_ms: number
  derivar_humano: boolean
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
