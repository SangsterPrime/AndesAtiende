import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Orb } from './Orb'

const mode = vi.hoisted(() => ({ crash: false }))
vi.mock('./OrbScene', () => ({
  default: ({ onFailure }: { onFailure: () => void }) => {
    if (mode.crash) throw new Error('WebGL unavailable')
    return <button data-testid="scene" onClick={onFailure}>Simular pérdida de contexto</button>
  },
}))

function allowMotion() {
  vi.mocked(window.matchMedia).mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList)
}

describe('escena decorativa aislada', () => {
  it('no monta Three.js cuando se solicita movimiento reducido', () => {
    render(<Orb phase="idle" />)
    expect(screen.getByTestId('orb-fallback')).toBeInTheDocument()
    expect(screen.queryByTestId('scene')).not.toBeInTheDocument()
  })

  it('cambia a fallback cuando se pierde el contexto', async () => {
    allowMotion()
    mode.crash = false
    render(<Orb phase="loading" />)
    fireEvent.click(await screen.findByTestId('scene'))
    expect(screen.getByTestId('orb-fallback')).toBeInTheDocument()
  })

  it('aísla un error de carga o renderizado de la escena', async () => {
    allowMotion()
    mode.crash = true
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<Orb phase="idle" />)
    expect(await screen.findByTestId('orb-fallback')).toBeInTheDocument()
    expect(screen.queryByTestId('scene')).not.toBeInTheDocument()
    mode.crash = false
  })
})
