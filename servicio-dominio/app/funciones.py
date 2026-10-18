"""Reglas de dominio testeables sin dependencias de infraestructura."""
import re

def minimiza_pii(s):
    s=re.sub(r'\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b','[CORREO]',s)
    s=re.sub(r'\b\d{1,2}(?:\.?\d{3}){2}-[0-9kK]\b','[RUT]',s)
    s=re.sub(r'\b(?:\+?56[\s-]?)?9[\s-]?\d{4}[\s-]?\d{4}\b','[TELEFONO]',s)
    s=re.sub(r'\b(?:\d[ -]?){13,19}\b','[NUMERO_SENSIBLE]',s)
    return s

RESPUESTAS={
 'anulacion':'La solicitud de anulación requiere asistencia humana. Te indicamos cómo contactar a un ejecutivo; este piloto no cancela servicios.',
 'facturacion':'Puedo orientar sobre facturación. Para ver montos, fechas o datos de cuenta es obligatorio autenticarte; esta demo no consulta Amdocs.',
 'falla_conexion':'Detecté una consulta de conexión. El diagnóstico remoto queda para la integración con operaciones de red; esta demo no lo simula como real.',
 'cambio_plan':'Identifiqué una consulta sobre cambio de plan. Antes de realizar cambios, un ejecutivo debe verificar tu identidad y condiciones.',
 'estado_visita':'Para consultar una visita se necesita autenticar al cliente y conectar la agenda de terreno; la demo solo clasifica tu intención.',
 'consulta_general':'Puedo clasificar tu consulta. Si necesitas resolver un caso particular, solicita un ejecutivo.',
 'portabilidad':'Te puedo orientar en los requisitos generales de portabilidad. Para trámites reales, solicita atención humana.',
 'cobertura':'Puedo ayudarte a identificar consultas de cobertura. Esta demo no consulta mapas de cobertura reales.',
 'roaming':'Puedo orientar sobre roaming. Para tarifas y habilitaciones concretas, consulta un ejecutivo.',
 'equipos':'Puedo orientarte sobre problemas de equipos. Una revisión técnica requiere las herramientas de Andesnet.',
 'television':'Detecté una consulta sobre televisión. Podemos continuar con ayuda general o derivar el caso.'
}

