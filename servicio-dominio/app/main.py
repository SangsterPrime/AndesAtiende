"""Dominio telco: única autoridad para lecturas/escrituras en PostgreSQL."""
import os
import re
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import httpx
import psycopg
from app.funciones import minimiza_pii, RESPUESTAS
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

app=FastAPI(title='AndesAtiende · Dominio',version='1.0.0')
DATABASE_URL=os.getenv('DATABASE_URL','postgresql://andes:andes_local_demo@db:5432/andesdb')
IA_URL=os.getenv('IA_URL','http://gateway:8080/api/ia/predict')

class Mensaje(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mensaje:str=Field(min_length=3,max_length=1200)


@app.get('/health')
def health():
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=2) as db:
            db.execute('SELECT 1').fetchone()
        return {'status':'ok'}
    except Exception:
        raise HTTPException(status_code=503,detail='BD no disponible')

@app.post('/chat')
async def chat(payload:Mensaje):
    inicio=perf_counter()
    mensaje=minimiza_pii(payload.mensaje.strip())
    # El gateway se encarga de elegir una réplica y del failover HTTP.
    try:
        async with httpx.AsyncClient(timeout=2.5) as cliente:
            r=await cliente.post(IA_URL,json={'mensaje':mensaje})
            r.raise_for_status()
            inferencia=r.json()
    except (httpx.HTTPError,ValueError):
        # Falla controlada: no fabricamos una predicción que no existe.
        raise HTTPException(status_code=503,detail='El clasificador está temporalmente indisponible; solicita asistencia humana.')
    intent=inferencia['intencion']
    confianza=float(inferencia['confianza'])
    derivar=intent=='anulacion' or re.search(r'(?i)\b(ejecutiv[oa]|persona real|hablar con humano|cancelar mi servicio)\b',mensaje) is not None or confianza<0.15
    respuesta=RESPUESTAS.get(intent,RESPUESTAS['consulta_general'])
    if derivar and intent!='anulacion':
        respuesta='Solicitaste ayuda humana o la clasificación es incierta. Esta demo registra la solicitud, sin conectar todavía con Genesys.'
    prediccion_id=str(uuid4())
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
            db.execute('INSERT INTO predicciones (prediccion_id, entrada, resultado, confianza, version_modelo, fecha, derivada) VALUES (%s,%s,%s,%s,%s,%s,%s)',
               (prediccion_id,mensaje,intent,confianza,inferencia['version_modelo'],datetime.now(timezone.utc),derivar))
            db.commit()
    except Exception:
        raise HTTPException(status_code=503,detail='No se pudo registrar la predicción; operación no confirmada.')
    return {'prediccion_id':prediccion_id,'intencion':intent,'confianza':confianza,'version_modelo':inferencia['version_modelo'],
      'respuesta':respuesta,'derivar_humano':derivar,'replica_ia':inferencia.get('replica'),
      'latencia_total_ms':round((perf_counter()-inicio)*1000,2)}

@app.get('/estadisticas')
def estadisticas():
    with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
        total=db.execute('SELECT COUNT(*) FROM predicciones').fetchone()[0]
    return {'predicciones_registradas':total}
