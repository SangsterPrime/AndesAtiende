"""API de inferencia independiente de BD: una responsabilidad, un contrato."""
import json
import os
from pathlib import Path
from time import perf_counter
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

MODEL_DIR=Path(os.environ.get('MODEL_DIR',Path(__file__).resolve().parents[1]/'modelo'))
app=FastAPI(title='AndesAtiende · Microservicio IA',version='1.0.0')
modelo=None
metadata={}

class Consulta(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mensaje:str=Field(min_length=3,max_length=1200)

class Resultado(BaseModel):
    intencion:str
    confianza:float
    version_modelo:str
    latencia_ms:float
    replica:str

@app.on_event('startup')
def init():
    global modelo,metadata
    try:
        metadata=json.loads((MODEL_DIR/'metadata.json').read_text(encoding='utf-8'))
        modelo=joblib.load(MODEL_DIR/'clasificador.joblib')
    except Exception as err:
        print(f'Modelo no disponible: {type(err).__name__}: {err}',flush=True)

@app.get('/health')
def health():
    if modelo is None:
        raise HTTPException(status_code=503,detail='Modelo no disponible')
    return {'status':'ok','version_modelo':metadata['version_modelo']}

@app.get('/modelo')
def modelo_info():
    if modelo is None:raise HTTPException(status_code=503,detail='Modelo no disponible')
    return {k: metadata[k] for k in ('version_modelo','algoritmo','macro_f1','n_test','clases')}

@app.post('/predict',response_model=Resultado)
def predict(payload:Consulta):
    if modelo is None:raise HTTPException(status_code=503,detail='Modelo no disponible')
    inicio=perf_counter()
    probabilities=modelo.predict_proba([payload.mensaje])[0]
    best=int(probabilities.argmax())
    return Resultado(intencion=str(modelo.classes_[best]),confianza=round(float(probabilities[best]),4),version_modelo=metadata['version_modelo'],latencia_ms=round((perf_counter()-inicio)*1000,3),replica=os.getenv('HOSTNAME','local'))
