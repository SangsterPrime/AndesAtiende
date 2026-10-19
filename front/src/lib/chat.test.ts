import { describe, expect, it, vi } from 'vitest'
import { chatFixture } from '../test/fixtures'
import { isChatResponse, sendChat } from './chat'

describe('contrato POST /api/chat', () => {
  it('envía únicamente mensaje a la ruta relativa del gateway y conserva los datos', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(chatFixture))
    vi.stubGlobal('fetch', fetchMock)
    expect(await sendChat('No tengo internet')).toEqual(chatFixture)
    expect(fetchMock).toHaveBeenCalledWith('/api/chat', expect.objectContaining({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mensaje: 'No tengo internet' }),
      signal: expect.any(AbortSignal),
    }))
  })

  it('presenta el detalle real del backend sin inventar una predicción', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: 'No se pudo registrar la predicción; operación no confirmada.' }, { status: 503 })))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'http', message: 'No se pudo registrar la predicción; operación no confirmada.' })
  })

  it('tolera una página HTML de error del gateway', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 })))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'http', message: expect.stringContaining('HTTP 502') })
  })

  it('no representa un error de validación 422 como [object Object]', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: [{ msg: 'invalid' }] }, { status: 422 })))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'http', message: expect.stringContaining('HTTP 422') })
  })

  it('rechaza respuestas exitosas incompletas y JSON inválido', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ respuesta: 'Incompleta' })))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'contract' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('invalid json')))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'contract' })
  })

  it.each([
    { confianza: 2 }, { confianza: -1 }, { confianza: Number.NaN },
    { latencia_total_ms: -1 }, { latencia_total_ms: Infinity },
    { derivar_humano: 'true' }, { version_modelo: '' }, { replica_ia: 12 },
  ])('rechaza campos fuera del contrato: %o', (patch) => {
    expect(isChatResponse({ ...chatFixture, ...patch })).toBe(false)
  })

  it('admite una réplica no informada, sin sustituirla por una ficticia', () => {
    expect(isChatResponse({ ...chatFixture, replica_ia: null })).toBe(true)
  })

  it('distingue una pérdida de conexión', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'network' })
  })

  it('corta la espera y no reintenta automáticamente', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const result = expect(sendChat('Consulta')).rejects.toMatchObject({ kind: 'timeout' })
    await vi.advanceTimersByTimeAsync(12_001)
    await result
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('respeta la cancelación al desmontar', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const result = expect(sendChat('Consulta', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await result
  })
})
