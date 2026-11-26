"""Dominio telco: única autoridad para lecturas/escrituras en PostgreSQL."""
import os
import re
import hmac
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID, uuid4
from typing import Annotated, Literal
import httpx
import psycopg
from app.funciones import minimiza_pii, RESPUESTAS
from app.llm import FAQ, enabled
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

app=FastAPI(title='AndesAtiende · Dominio',version='1.0.0',docs_url=None,redoc_url=None,
            servers=[{'url':'/api'}])
DATABASE_URL=os.getenv('DATABASE_URL','postgresql://andes:andes_local_demo@db:5432/andesdb')
IA_URL=os.getenv('IA_URL','http://gateway:8081/predict')
api_key_header=APIKeyHeader(name='X-API-Key',auto_error=False)


def clave_valida(request:Request):
    expected=os.environ.get('EP3_API_KEY','')
    supplied=request.headers.getlist('x-api-key')
    return (re.fullmatch(r'[A-Za-z0-9_-]{32,128}',expected) is not None
            and len(supplied)==1
            and hmac.compare_digest(supplied[0].encode('utf-8'),expected.encode('utf-8')))


@app.middleware('http')
async def autenticar_antes_del_cuerpo(request:Request,call_next):
    path=request.scope['path']
    root=request.scope.get('root_path','').rstrip('/')
    if root and path.startswith(root+'/'):
        path=path[len(root):]
    public=request.method=='GET' and path in ('/health','/docs','/openapi.json')
    if not public and not clave_valida(request):
        # Antes de parsear JSON/UUID, abrir BD o llamar IA. No reflejar cabeceras.
        return JSONResponse(status_code=401,content={'detail':'API key ausente o inválida'},
                            headers={'WWW-Authenticate':'APIKey'})
    return await call_next(request)


def autenticar(request:Request,key=Security(api_key_header)):
    # También documenta el esquema en OpenAPI; el middleware aplica el orden 401/422.
    if not clave_valida(request):
        raise HTTPException(status_code=401,detail='API key ausente o inválida')


@app.get('/docs',include_in_schema=False)
def docs():
    return get_swagger_ui_html(openapi_url='/api/openapi.json',title='AndesAtiende · API EP3')

class Mensaje(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mensaje:str=Field(min_length=3,max_length=1200)

    @field_validator('mensaje')
    @classmethod
    def validar_mensaje(cls, value):
        value=value.strip()
        if len(value)<3:
            raise ValueError('El mensaje debe tener al menos 3 caracteres sin espacios exteriores')
        return value


class Inferencia(BaseModel):
    intencion:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1)]
    confianza:float=Field(strict=True,ge=0,le=1,allow_inf_nan=False)
    version_modelo:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1)]
    replica:str|None=None


class PrediccionGuardada(BaseModel):
    prediccion_id:UUID
    intencion:str
    confianza:float=Field(ge=0,le=1,allow_inf_nan=False)
    version_modelo:str
    fecha:datetime
    derivar_humano:bool
    estado_llm:Literal["pendiente","lista","degradada"]|None=None
    respuesta_llm:str|None=None


@app.get('/health')
def health():
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=2) as db:
            db.execute('SELECT 1').fetchone()
        return {'status':'ok'}
    except Exception:
        raise HTTPException(status_code=503,detail='BD no disponible')

@app.post('/conversacion',dependencies=[Security(autenticar)])
@app.post('/chat',dependencies=[Security(autenticar)])
@app.post('/predict',dependencies=[Security(autenticar)])
async def chat(payload:Mensaje,request:Request):
    inicio=perf_counter()
    mensaje=minimiza_pii(payload.mensaje.strip())
    # El gateway se encarga de elegir una réplica y del failover HTTP.
    try:
        async with httpx.AsyncClient(timeout=8.0) as cliente:
            r=await cliente.post(IA_URL,json={'mensaje':mensaje})
            r.raise_for_status()
            inferencia=Inferencia.model_validate(r.json())
    except (httpx.HTTPError,ValueError):
        # Falla controlada: no fabricamos una predicción que no existe.
        raise HTTPException(status_code=503,detail='El clasificador está temporalmente indisponible; solicita asistencia humana.')
    intent=inferencia.intencion
    confianza=inferencia.confianza
    derivar=intent=='anulacion' or re.search(r'(?i)\b(ejecutiv[oa]|persona real|hablar con humano|hablar con una persona|cancelar mi servicio)\b',mensaje) is not None or confianza<0.15
    respuesta=RESPUESTAS.get(intent,RESPUESTAS['consulta_general'])
    if derivar and intent!='anulacion':
        respuesta='Solicitaste ayuda humana o la clasificación es incierta. Esta demo registra la solicitud, sin conectar todavía con Genesys.'
    prediccion_id=str(uuid4())
    estado_llm = None
    if enabled() and not request.url.path.endswith('/predict'):
        estado_llm = 'pendiente' if intent in FAQ and not derivar else 'degradada'
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
            db.execute('INSERT INTO predicciones (prediccion_id, entrada, resultado, confianza, version_modelo, fecha, derivada) VALUES (%s,%s,%s,%s,%s,%s,%s)',
               (prediccion_id,mensaje,intent,confianza,inferencia.version_modelo,datetime.now(timezone.utc),derivar))
            if estado_llm:
                db.execute(
                    'INSERT INTO respuestas_llm (prediccion_id,intencion,estado) VALUES (%s,%s,%s)',
                    (prediccion_id,intent,estado_llm),
                )
            db.commit()
    except Exception:
        raise HTTPException(status_code=503,detail='No se pudo registrar la predicción; operación no confirmada.')
    extra = {'estado_llm': estado_llm} if estado_llm else {}
    return {**extra,'prediccion_id':prediccion_id,'intencion':intent,'confianza':confianza,'version_modelo':inferencia.version_modelo,
      'respuesta':respuesta,'derivar_humano':derivar,'replica_ia':inferencia.replica,
      'latencia_total_ms':round((perf_counter()-inicio)*1000,2)}


@app.get('/predicciones/{prediccion_id}',response_model=PrediccionGuardada,response_model_exclude_none=True,
         dependencies=[Security(autenticar)])
def consultar_prediccion(prediccion_id:UUID):
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
            row=db.execute(
                'SELECT prediccion_id, resultado, confianza, version_modelo, fecha, derivada '
                'FROM predicciones WHERE prediccion_id = %s', (str(prediccion_id),),
            ).fetchone()
            llm = consultar_llm(db, prediccion_id) if row and enabled() else {}
    except Exception:
        raise HTTPException(status_code=503,detail='No se pudo consultar la predicción')
    if row is None:
        raise HTTPException(status_code=404,detail='Predicción no encontrada')
    # No exponer la entrada del usuario ni fabricar una respuesta que no se guardó.
    return dict(zip(('prediccion_id','intencion','confianza','version_modelo','fecha','derivar_humano'),row)) | llm


def consultar_llm(db, prediccion_id):
    row = db.execute(
        "SELECT CASE WHEN estado='pendiente' AND creada < now() - interval '25 seconds' "
        "THEN 'degradada' ELSE estado END, respuesta FROM respuestas_llm WHERE prediccion_id=%s",
        (str(prediccion_id),),
    ).fetchone()
    return dict(zip(('estado_llm','respuesta_llm'), row)) if row else {}


@app.get('/chat/respuesta/{prediccion_id}', include_in_schema=False)
def respuesta_chat(prediccion_id:UUID):
    # The unpredictable UUID is the capability returned to the chat.
    if not enabled():
        raise HTTPException(status_code=404)
    try:
        with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
            llm = consultar_llm(db, prediccion_id)
    except psycopg.Error:
        raise HTTPException(status_code=503,detail='No se pudo consultar la respuesta')
    if not llm:
        raise HTTPException(status_code=404)
    return JSONResponse(llm,headers={'Cache-Control':'no-store'})

@app.get('/estadisticas',dependencies=[Security(autenticar)])
def estadisticas():
    with psycopg.connect(DATABASE_URL,connect_timeout=3) as db:
        total=db.execute('SELECT COUNT(*) FROM predicciones').fetchone()[0]
        if not enabled():
            return {'predicciones_registradas':total}
        conversations, referrals, degraded, pending = db.execute(
            "SELECT count(*), count(*) FILTER (WHERE p.derivada), "
            "count(*) FILTER (WHERE r.estado='degradada' OR "
            "(r.estado='pendiente' AND r.creada < now() - interval '25 seconds')), "
            "count(*) FILTER (WHERE r.estado='pendiente' AND r.creada >= now() - interval '25 seconds') "
            "FROM respuestas_llm r JOIN predicciones p USING (prediccion_id)"
        ).fetchone()
        intents = db.execute(
            'SELECT intencion, count(*) FROM respuestas_llm GROUP BY intencion ORDER BY intencion'
        ).fetchall()
    return {'predicciones_registradas':total,'conversaciones':conversations,
            'intenciones':dict(intents),'pendientes':pending,
            'tasa_derivacion':referrals/conversations if conversations else 0,
            'tasa_degradada':degraded/conversations if conversations else 0}
