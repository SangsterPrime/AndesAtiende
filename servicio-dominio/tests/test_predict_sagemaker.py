"""Gateway simulado por prefijo ASGI, IA real, SageMaker/SQL simulados; sin AWS/BD."""
import importlib.util
import io
import json
from pathlib import Path

import boto3
from botocore.exceptions import ReadTimeoutError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app import main as dominio


ROOT = Path(__file__).resolve().parents[2]
HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture
def flow(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('ia_integracion', ROOT / 'servicio-ia/app/main.py')
    ia = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ia)
    runtime = boto3.client('sagemaker-runtime', region_name='us-east-1',
                           aws_access_key_id='testing', aws_secret_access_key='testing',
                           aws_session_token='testing')
    monkeypatch.setenv('IA_BACKEND', 'sagemaker')
    monkeypatch.setenv('SAGEMAKER_ENDPOINT_NAME', 'andes-test')
    monkeypatch.setenv('MODEL_DIR', str(tmp_path / 'no-modelo'))
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.setattr(ia.boto3, 'client', lambda *args, **kwargs: runtime)
    monkeypatch.setattr(ia.joblib, 'load', lambda *args: pytest.fail('No usar joblib'))
    application = ia.create_app()
    ia_gateway = FastAPI()
    # Simula el proxy_pass http://ia_pool/ que elimina /api/ia/ en Nginx.
    ia_gateway.mount('/api/ia', application)

    def ia_client(**kwargs):
        assert kwargs['timeout'] == 8.0
        return HTTP_CLIENT(transport=httpx.ASGITransport(app=ia_gateway), **kwargs)

    monkeypatch.setattr(dominio.httpx, 'AsyncClient', ia_client)

    class Database:
        def __init__(self):
            self.inserts = []
            self.commits = 0
            self.connections = 0

        def __enter__(self):
            self.connections += 1
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            assert sql.startswith('INSERT INTO predicciones ')
            self.inserts.append(params)

        def commit(self):
            self.commits += 1

    database = Database()
    monkeypatch.setattr(dominio.psycopg, 'connect', lambda *args, **kwargs: database)
    gateway = FastAPI()
    gateway.mount('/api', dominio.app)
    with Stubber(runtime) as stub, TestClient(application), TestClient(gateway) as client:
        yield client, stub, database, runtime
        stub.assert_no_pending_responses()


def expect(stub, payload, mensaje='No tengo internet'):
    data = json.dumps(payload).encode('utf-8')
    stub.add_response('invoke_endpoint', {
        'Body': StreamingBody(io.BytesIO(data), len(data)), 'ContentType': 'application/json',
    }, {'EndpointName': 'andes-test', 'ContentType': 'application/json', 'Accept': 'application/json',
        'Body': json.dumps({'mensaje': mensaje}, ensure_ascii=False).encode('utf-8')})


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
def test_contrato_y_version_real_persistida(flow, route):
    client, stub, database, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .912345, 'version_modelo': 'ep3-desplegado-42'})
    response = client.post(route, json={'mensaje': 'No tengo internet'})
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {'prediccion_id', 'intencion', 'confianza', 'version_modelo', 'respuesta',
                         'derivar_humano', 'replica_ia', 'latencia_total_ms'}
    assert data['confianza'] == .912345
    assert data['version_modelo'] == 'ep3-desplegado-42'
    assert data['intencion'] == 'falla_conexion'
    assert data['latencia_total_ms'] >= 0
    assert data['respuesta'] and data['derivar_humano'] is False
    assert database.commits == 1
    assert len(database.inserts) == 1
    row = database.inserts[0]
    assert row[0] == data['prediccion_id']
    assert row[2:5] == (data['intencion'], data['confianza'], data['version_modelo'])


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
@pytest.mark.parametrize('failure', ['timeout', 'invalid', 'access-denied'])
def test_fallo_sagemaker_no_persiste_exito(flow, monkeypatch, route, failure):
    client, stub, database, runtime = flow
    if failure == 'timeout':
        def timeout(**kwargs):
            raise ReadTimeoutError(endpoint_url='https://runtime.sagemaker.us-east-1.amazonaws.com')
        monkeypatch.setattr(runtime, 'invoke_endpoint', timeout)
    elif failure == 'access-denied':
        stub.add_client_error('invoke_endpoint', 'AccessDeniedException', 'No exponer detalle')
    else:
        expect(stub, {'intencion': 'falla_conexion', 'probabilidad': 5, 'version_modelo': 'ep3'})
    response = client.post(route, json={'mensaje': 'No tengo internet'})
    assert response.status_code == 503
    assert 'prediccion_id' not in response.json()
    assert database.connections == database.commits == 0
    assert not database.inserts


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
def test_minimiza_pii_antes_de_ia_y_persistencia(flow, route):
    client, stub, database, _ = flow
    minimized = 'Mi correo es [CORREO] y no tengo internet'
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': 'ep3'}, minimized)
    assert client.post(route, json={'mensaje': 'Mi correo es prueba@example.cl y no tengo internet'}).status_code == 200
    assert database.inserts[0][1] == minimized


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
@pytest.mark.parametrize('payload', [{}, {'mensaje': '   '}, {'mensaje': 'x'}, {'mensaje': 'hola', 'extra': 1}])
def test_validacion_compartida_no_invoca_ni_persiste(flow, route, payload):
    client, _, database, _ = flow
    assert client.post(route, json=payload).status_code == 422
    assert not database.inserts
    assert database.connections == 0


def test_dominio_rechaza_inferencia_invalida_antes_de_sql(flow, monkeypatch):
    client, _, database, _ = flow
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'intencion': 'falla_conexion', 'confianza': .8, 'version_modelo': '',
    }))
    monkeypatch.setattr(dominio.httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(transport=transport, **kwargs))
    assert client.post('/api/predict', json={'mensaje': 'No tengo internet'}).status_code == 503
    assert not database.inserts
    assert database.connections == 0


def test_fallo_bd_no_confirma_prediccion(flow, monkeypatch):
    client, stub, database, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': 'ep3'})

    def unavailable(*args, **kwargs):
        raise dominio.psycopg.OperationalError('BD no disponible')

    monkeypatch.setattr(dominio.psycopg, 'connect', unavailable)
    response = client.post('/api/predict', json={'mensaje': 'No tengo internet'})
    assert response.status_code == 503
    assert 'prediccion_id' not in response.json()
    assert database.commits == 0


def test_gateway_predict_no_evade_dominio():
    config = (ROOT / 'gateway/nginx.conf').read_text(encoding='utf-8')
    block = config.split('location = /api/predict {', 1)[1].split('}', 1)[0]
    assert 'proxy_pass http://dominio:8000/predict;' in block
    assert 'proxy_read_timeout 10s;' in config
