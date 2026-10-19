import type { ChatResponse } from '../lib/chat'

export function ResponseDetails({ data }: { data: ChatResponse }) {
  return (
    <details className="response-details">
      <summary>Detalles de la clasificación <span aria-hidden="true">↗</span></summary>
      <dl className="metadata-grid">
        <div><dt>Intención</dt><dd>{data.intencion}</dd></div>
        <div><dt>Confianza</dt><dd>{(data.confianza * 100).toLocaleString('es-CL', { maximumFractionDigits: 2 })}%</dd></div>
        <div><dt>Modelo</dt><dd>{data.version_modelo}</dd></div>
        <div><dt>Réplica IA</dt><dd>{data.replica_ia || 'No informada'}</dd></div>
        <div><dt>Latencia del backend</dt><dd>{data.latencia_total_ms.toLocaleString('es-CL', { maximumFractionDigits: 2 })} ms</dd></div>
        <div><dt>Derivación humana</dt><dd>{data.derivar_humano ? 'Solicitada y registrada' : 'No solicitada'}</dd></div>
        <div className="prediction-id"><dt>ID de predicción</dt><dd>{data.prediccion_id}</dd></div>
      </dl>
    </details>
  )
}
