import { Component, lazy, Suspense, useState, type ReactNode } from 'react'
import type { ChatPhase } from '../lib/chat'
import { useReducedMotion } from '../hooks/useReducedMotion'
import { StaticOrb } from './StaticOrb'

const OrbScene = lazy(() => import('./OrbScene'))

class SceneBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

export function Orb({ phase }: { phase: ChatPhase }) {
  const reducedMotion = useReducedMotion()
  const [failed, setFailed] = useState(false)
  return (
    <div className={`orb-stage phase-${phase}`} aria-hidden="true">
      <div className="orb-orbit orbit-one" />
      <div className="orb-orbit orbit-two" />
      <div className="orb-halo" />
      {reducedMotion || failed ? <StaticOrb reason={reducedMotion ? 'reduced-motion' : 'unavailable'} /> : (
        <SceneBoundary fallback={<StaticOrb />}>
          <Suspense fallback={<StaticOrb reason="loading" />}>
            <OrbScene phase={phase} onFailure={() => setFailed(true)} />
          </Suspense>
        </SceneBoundary>
      )}
      <span className="orb-cross cross-one">+</span><span className="orb-cross cross-two">+</span>
    </div>
  )
}
