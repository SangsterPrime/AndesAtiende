"""Crea un extracto de laboratorio seudonimizado a partir del ZIP privado del caso.
NO sustituye una evaluación DLP en producción. No publiques los originales.
"""
import argparse
import hashlib
import re
from pathlib import Path
import pandas as pd

CONTACTS = [
    (r'\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[CORREO]'),
    (r'\b(?:\+?56[\s-]?)?9[\s-]?\d{4}[\s-]?\d{4}\b', '[TELEFONO]'),
    (r'\b\d{1,2}(?:\.?\d{3}){2}-[0-9kK]\b', '[RUT]'),
    (r'\b(?:\d[ -]?){13,19}\b', '[NUMERO_SENSIBLE]'),
    (r'\b(?:calle|pasaje|avenida|av\.|domicilio|direcci[oó]n)\s+[^,\n;]{3,70}\s+\d+[A-Za-z]?\b', '[DIRECCION]'),
]


def anon_id(value):
    if pd.isna(value) or str(value).strip() == '':
        return ''
    return hashlib.sha256(('ep2-lab-v1|' + str(value)).encode()).hexdigest()[:20]


def redactar(texto):
    if pd.isna(texto):
        return ''
    value = str(texto).replace('\x00', '')
    for pattern, sub in CONTACTS:
        value = re.sub(pattern, sub, value, flags=re.IGNORECASE)
    # Las frases introducidas por ejecutivos incluyen identificadores no estructurados.
    # Elimina esos apéndices completos y preserva la consulta inicial útil al modelo.
    value = re.sub(r'(?i)\s+(?:mi\s+(?:rut|correo|email|telefono|tel[eé]fono|numero|n[uú]mero|direcci[oó]n)|escr[ií]banme\s+a|pagu[eé]\s+con\s+la\s+tarjeta|vivo\s+en)\b[^.!?\n]*', ' [DATO_REDACTADO]', value)
    return value.strip()


COLUMNS = {
    'clientes': ['cliente_id','fecha_alta','plan','tipo_servicio','region','segmento','antiguedad_meses','deuda_vigente','canal_preferido','acepta_contacto'],
    'tickets': ['ticket_id','cliente_id','canal','fecha_apertura','fecha_cierre','categoria','texto_consulta','tiempo_espera_seg','resuelto','csat','reabierto'],
    'conversaciones': ['conversacion_id','cliente_id','canal','inicio','fin','turnos','intencion_detectada','derivada_a_humano','resuelta','idioma'],
    'faq': ['articulo_id','pregunta','respuesta','categoria','vistas_12m','ultima_edicion','vigente'],
}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--origen',type=Path,required=True)
    parser.add_argument('--destino',type=Path,default=Path(__file__).parent/'entrada')
    args=parser.parse_args();args.destino.mkdir(parents=True,exist_ok=True)
    for name,fields in COLUMNS.items():
        df=pd.read_csv(args.origen/f'{name}.csv',dtype=str,keep_default_na=True)[fields]
        for col in ['cliente_id','ticket_id','conversacion_id']:
            if col in df: df[col] = df[col].map(anon_id)
        for col in ['texto_consulta','pregunta','respuesta']:
            if col in df: df[col]=df[col].map(redactar)
        df.to_csv(args.destino/f'{name}.csv',index=False)
        print(f'{name}: {len(df):,} filas; fuente seudonimizada y minimizada')
    print('ADVERTENCIA: Sanitización orientada a datos ficticios de laboratorio; no es certificación GDPR ni DLP.')
if __name__ == '__main__': main()
