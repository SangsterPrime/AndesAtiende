export function StaticOrb({ reason = 'unavailable' }: { reason?: 'loading' | 'reduced-motion' | 'unavailable' }) {
  return <div className="static-orb" data-testid="orb-fallback" data-reason={reason}><div className="static-orb-core" /></div>
}
