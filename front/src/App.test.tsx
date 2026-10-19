import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { chatFixture } from './test/fixtures'

describe('experiencia conversacional', () => {
  it('muestra el chat sin WebGL y no inventa disponibilidad ni métricas', () => {
    render(<App />)
    expect(screen.getByRole('textbox', { name: 'Tu consulta' })).toBeVisible()
    expect(screen.getByTestId('orb-fallback')).toBeInTheDocument()
    expect(screen.getAllByText('Esperando tu consulta')).toHaveLength(2)
    expect(screen.queryByText('87,32%')).not.toBeInTheDocument()
    expect(screen.getByText(/Demo sin autenticación/)).toBeVisible()
  })

  it('envía con Enter y muestra respuesta, metadatos y latencia del backend', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(Response.json(chatFixture))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await user.type(screen.getByRole('textbox', { name: 'Tu consulta' }), 'No tengo internet{Enter}')
    expect(await screen.findByText(chatFixture.respuesta)).toBeVisible()
    await user.click(screen.getByText('Detalles de la clasificación'))
    for (const value of ['soporte_tecnico', '87,32%', 'modelo-prueba-v2', 'replica-prueba-2', '42,75 ms', 'No solicitada', 'prueba-prediccion-001']) {
      expect(screen.getByText(value)).toBeVisible()
    }
    expect(screen.getAllByText('Respuesta recibida')).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('permite Shift+Enter, sugiere sin enviar y valida la longitud mínima', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const input = screen.getByRole('textbox', { name: 'Tu consulta' })
    await user.type(input, 'ab{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('entre 3 y 1200')
    expect(fetchMock).not.toHaveBeenCalled()
    await user.clear(input)
    await user.type(input, 'Hola{Shift>}{Enter}{/Shift}equipo')
    expect(input).toHaveValue('Hola\nequipo')
    expect(fetchMock).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /Mi factura/ }))
    expect(input).toHaveValue('Quiero revisar mi factura')
    expect(input).toHaveFocus()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('bloquea envíos duplicados mientras espera la respuesta', async () => {
    const user = userEvent.setup()
    let resolve!: (response: Response) => void
    const fetchMock = vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const input = screen.getByRole('textbox', { name: 'Tu consulta' })
    await user.type(input, 'No tengo internet{Enter}')
    expect(screen.getByRole('button', { name: 'Enviar consulta' })).toBeDisabled()
    expect(screen.getAllByText('Procesando tu consulta')).toHaveLength(2)
    await user.type(input, 'Otra consulta{Enter}{Enter}')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => { resolve(Response.json(chatFixture)) })
    expect(await screen.findByText(chatFixture.respuesta)).toBeVisible()
    expect(input).toHaveValue('Otra consulta')
  })

  it('presenta derivación registrada sin prometer conexión con una persona', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ ...chatFixture, derivar_humano: true, replica_ia: null })))
    render(<App />)
    await user.type(screen.getByRole('textbox'), 'Quiero hablar con humano{Enter}')
    expect(await screen.findByText('Derivación registrada. Esta demo no conecta con Genesys ni con un ejecutivo.')).toBeVisible()
    await user.click(screen.getByText('Detalles de la clasificación'))
    expect(screen.getByText('Solicitada y registrada')).toBeVisible()
    expect(screen.getByText('No informada')).toBeVisible()
  })

  it('conserva el historial, explica el fallo y reenvía solo por acción explícita', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({ detail: 'Clasificador indisponible' }, { status: 503 }))
      .mockResolvedValueOnce(Response.json(chatFixture))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await user.type(screen.getByRole('textbox'), 'No tengo internet{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('Clasificador indisponible')
    expect(screen.getByRole('alert')).toHaveTextContent('pudo haberse registrado')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /Reenviar consulta/ }))
    expect(await screen.findByText(chatFixture.respuesta)).toBeVisible()
    expect(within(screen.getByRole('log')).getAllByText('No tengo internet')).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('distingue conexión perdida y permite recuperar la conversación', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<App />)
    await user.type(screen.getByRole('textbox'), 'Mi consulta{Enter}')
    await waitFor(() => expect(screen.getAllByText('Conexión perdida')).toHaveLength(2))
    fireEvent(window, new Event('offline'))
    expect(screen.getByRole('button', { name: /Reenviar consulta/ })).toBeDisabled()
    expect(screen.getByText(/No hay conexión de red/)).toBeVisible()
    fireEvent(window, new Event('online'))
    expect(screen.getByRole('button', { name: /Reenviar consulta/ })).toBeEnabled()
    expect(screen.getByText('Mi consulta')).toBeVisible()
  })

  it('no interpreta HTML devuelto por el servicio', async () => {
    const user = userEvent.setup()
    const text = '<img src=x onerror=alert(1)>'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ ...chatFixture, respuesta: text })))
    render(<App />)
    await user.type(screen.getByRole('textbox'), 'Consulta de prueba{Enter}')
    expect(await screen.findByText(text)).toBeVisible()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
