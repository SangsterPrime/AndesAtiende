"""Un contrato de inferencia para EP2 local o SageMaker, sin acceso a BD."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Annotated

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MAX_RESPONSE_BYTES = 64 * 1024


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


class ResultadoSageMaker(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intencion: Texto
    probabilidad: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    version_modelo: Texto


class Resultado(BaseModel):
    intencion: Texto
    confianza: float = Field(ge=0, le=1, allow_inf_nan=False)
    version_modelo: Texto
    latencia_ms: float = Field(ge=0, allow_inf_nan=False)
    replica: str


def invocar_sagemaker(runtime, endpoint, mensaje):
    response = runtime.invoke_endpoint(
        EndpointName=endpoint, ContentType='application/json', Accept='application/json',
        Body=json.dumps({'mensaje': mensaje}, ensure_ascii=False).encode('utf-8'),
    )
    body = response['Body']
    try:
        data = body.read(MAX_RESPONSE_BYTES + 1)
    finally:
        body.close()
    if (len(data) > MAX_RESPONSE_BYTES
            or response.get('ContentType', '').split(';')[0].strip().lower() != 'application/json'):
        raise ValueError('Respuesta SageMaker incompatible')
    return ResultadoSageMaker.model_validate_json(data)


def create_app():
    @asynccontextmanager
    async def lifespan(application):
        state = application.state
        state.backend = os.environ.get('IA_BACKEND', 'local').strip().lower()
        state.ready = False
        state.model = None
        state.runtime = None
        state.metadata = {}
        try:
            if state.backend == 'sagemaker':
                state.endpoint = os.environ.get('SAGEMAKER_ENDPOINT_NAME', '').strip()
                if not state.endpoint:
                    raise ValueError('Falta SAGEMAKER_ENDPOINT_NAME')
                # Cadena de credenciales estándar: rol de instancia EC2/IMDS.
                # No hay claves estáticas, assume-role ni invocaciones de pago al arrancar.
                state.runtime = boto3.client('sagemaker-runtime', region_name='us-east-1', config=Config(
                    connect_timeout=1, read_timeout=5, retries={'total_max_attempts': 1},
                ))
            elif state.backend == 'local':
                directory = Path(os.environ.get('MODEL_DIR', Path(__file__).resolve().parents[1] / 'modelo'))
                state.metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
                state.model = joblib.load(directory / 'clasificador.joblib')
            else:
                raise ValueError('IA_BACKEND debe ser local o sagemaker')
            state.ready = True
        except Exception as error:
            # No exponer credenciales, consultas ni detalles internos de AWS.
            print(f'Inferencia no configurada: {type(error).__name__}', flush=True)
        try:
            yield
        finally:
            if state.runtime is not None:
                state.runtime.close()

    application = FastAPI(title='AndesAtiende · Microservicio IA', version='1.0.0', lifespan=lifespan)

    def ready():
        if not application.state.ready:
            raise HTTPException(status_code=503, detail='Clasificador no disponible')

    @application.get('/health')
    def health():
        ready()
        if application.state.backend == 'sagemaker':
            # Es salud de configuración, no garantiza disponibilidad remota ni inventa versión.
            return {'status': 'ok', 'backend': 'sagemaker'}
        return {'status': 'ok', 'version_modelo': application.state.metadata['version_modelo']}

    @application.get('/modelo')
    def modelo_info():
        ready()
        if application.state.backend == 'sagemaker':
            return {'backend': 'sagemaker', 'endpoint': application.state.endpoint}
        return {k: application.state.metadata[k] for k in ('version_modelo', 'algoritmo', 'macro_f1', 'n_test', 'clases')}

    @application.post('/predict', response_model=Resultado)
    def predict(payload: Consulta):
        ready()
        state = application.state
        inicio = perf_counter()
        try:
            if state.backend == 'sagemaker':
                prediction = invocar_sagemaker(state.runtime, state.endpoint, payload.mensaje)
                intent, confidence, version = prediction.intencion, prediction.probabilidad, prediction.version_modelo
            else:
                probabilities = state.model.predict_proba([payload.mensaje])[0]
                best = int(probabilities.argmax())
                intent = str(state.model.classes_[best])
                confidence = round(float(probabilities[best]), 4)
                version = state.metadata['version_modelo']
            return Resultado(intencion=intent, confianza=confidence, version_modelo=version,
                             latencia_ms=round((perf_counter() - inicio) * 1000, 3),
                             replica=os.getenv('HOSTNAME', 'local'))
        except (BotoCoreError, ClientError, ValueError, TypeError, KeyError):
            raise HTTPException(status_code=503, detail='El clasificador está temporalmente indisponible')

    return application


app = create_app()
