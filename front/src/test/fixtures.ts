import type { ChatResponse } from '../lib/chat'

// Datos sintéticos exclusivos de pruebas. Nunca se usan como respuesta de la app.
export const chatFixture: ChatResponse = {
  prediccion_id: 'prueba-prediccion-001',
  respuesta: 'Respuesta sintética del servicio para una prueba.',
  intencion: 'soporte_tecnico',
  confianza: 0.8732,
  version_modelo: 'modelo-prueba-v2',
  replica_ia: 'replica-prueba-2',
  latencia_total_ms: 42.75,
  derivar_humano: false,
}
