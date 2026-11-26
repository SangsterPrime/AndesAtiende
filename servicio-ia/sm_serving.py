"""Adaptador SageMaker separado de la API EP2; solo carga artefactos de confianza."""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import os

import joblib
import numpy as np
import sklearn
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Consulta(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mensaje: str = Field(min_length=3, max_length=1200)

    @field_validator('mensaje')
    @classmethod
    def validar_mensaje(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError('El mensaje debe tener al menos 3 caracteres sin espacios exteriores')
        return value


class Prediccion(BaseModel):
    intencion: str
    probabilidad: float = Field(ge=0, le=1, allow_inf_nan=False)
    version_modelo: str


def load_model(model_dir):
    path = Path(model_dir)
    metadata = json.loads((path / 'metadata.json').read_text(encoding='utf-8'))
    if metadata.get('version_sklearn') != sklearn.__version__:
        raise ValueError('La versión de scikit-learn del artefacto no coincide con la de inferencia')
    if not isinstance(metadata.get('version_modelo'), str) or not metadata['version_modelo'].strip():
        raise ValueError('Falta version_modelo en metadata')
    # joblib/pickle puede ejecutar código: nunca cargar modelos de terceros no confiables.
    model = joblib.load(path / 'clasificador.joblib')
    if list(model.named_steps) != ['tfidf', 'classifier']:
        raise ValueError('Pipeline inesperado')
    if list(map(str, model.classes_)) != metadata.get('clases'):
        raise ValueError('Las clases no coinciden con metadata')
    predict(model, metadata, 'consulta de comprobación')
    return model, metadata


def predict(model, metadata, mensaje):
    probabilities = model.predict_proba([mensaje])[0]
    if (probabilities.shape != (len(model.classes_),) or not np.isfinite(probabilities).all()
            or not ((probabilities >= 0) & (probabilities <= 1)).all()
            or not np.isclose(probabilities.sum(), 1)):
        raise ValueError('El modelo devolvió probabilidades inválidas')
    best = int(probabilities.argmax())
    return Prediccion(intencion=str(model.classes_[best]), probabilidad=float(probabilities[best]),
                      version_modelo=metadata['version_modelo'])


def create_app(model_dir=None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.model = None
        try:
            application.state.model, application.state.metadata = load_model(
                model_dir if model_dir is not None else os.environ.get('SM_MODEL_DIR', '/opt/ml/model'))
        except Exception as error:
            # No imprimir datos de consultas, credenciales ni contenido de artefactos.
            print(f'No se pudo cargar el modelo SageMaker: {type(error).__name__}', flush=True)
        yield

    application = FastAPI(title='AndesAtiende EP3 · SageMaker', lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)

    def ready():
        if application.state.model is None:
            raise HTTPException(status_code=503, detail='Modelo no disponible')

    @application.api_route('/ping', methods=['GET', 'POST'])
    def ping():
        ready()
        return Response(status_code=200)

    @application.post('/invocations', response_model=Prediccion)
    def invocations(payload: Consulta):
        ready()
        try:
            return predict(application.state.model, application.state.metadata, payload.mensaje)
        except Exception:
            raise HTTPException(status_code=503, detail='No se pudo obtener una predicción válida')

    return application


app = create_app()
