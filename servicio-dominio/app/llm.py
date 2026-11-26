"""Public FAQ excerpts and intent-only inputs for NVIDIA."""
import os
import re

import httpx

FAQ = {
    'cambio_plan': ('FQ1035', 'Quiero cambiar de plan.',
                    'Ingresa al portal, sección Mi Plan, y selecciona Cambiar.'),
    'falla_conexion': ('FQ1001', 'Mi conexión a internet falla.',
                       'Reinicia el router, revisa las luces y verifica que no haya corte en tu zona.'),
    'facturacion': ('FQ1002', 'Tengo una consulta de facturación.',
                    'La fecha de vencimiento aparece en la esquina superior derecha de tu boleta.'),
    'roaming': ('FQ1016', 'Tengo una consulta sobre roaming.',
                'El costo depende del país y del plan contratado.'),
    'cobertura': ('FQ1018', 'Tengo una consulta sobre cobertura.',
                  'Consulta el mapa de cobertura en el sitio web.'),
}


def enabled():
    return os.getenv('EP3_LLM_ENABLED') == '1'


def generate(intent, key, model, sleep):
    """Generate from a fixed paraphrase and a reviewed public FAQ excerpt."""
    _, message, answer = FAQ[intent]
    for attempt in range(3):
        response = httpx.post(
            'https://integrate.api.nvidia.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}'},
            json={
                'model': model, 'max_tokens': 384, 'temperature': 0,
                'messages': [
                    {'role': 'system', 'content': 'Da directamente al cliente una orientación breve en español. '
                                                  'Incluye los pasos concretos que permita la FAQ, sin título ni código de artículo. '
                                                  'No inventes datos de cuenta ni afirmes haber ejecutado acciones.'},
                    {'role': 'user', 'content': f'Consulta: {message}\nFAQ: {answer}'},
                ],
            }, timeout=4.0,
        )
        if response.status_code == 429 and attempt < 2:
            sleep(2 ** attempt)
            continue
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()
        if not content or re.fullmatch(r'(?:art[ií]culo\s*[:#-]?\s*)?FQ[0-9]+[.!]?', content, re.IGNORECASE):
            raise ValueError('NVIDIA no devolvió una orientación')
        return content[:2000]
