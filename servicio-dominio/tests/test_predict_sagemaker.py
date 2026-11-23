"""Gateway simulado por prefijo ASGI, IA real, SageMaker/SQL simulados; sin AWS/BD."""
import importlib.util
import io
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.exceptions import ReadTimeoutError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
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
    monkeypatch.setenv('EP3_API_KEY', secrets.token_urlsafe(32))
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.setattr(ia.boto3, 'client', lambda *args, **kwargs: runtime)
    monkeypatch.setattr(ia.joblib, 'load', lambda *args: pytest.fail('No usar joblib'))
    application = ia.create_app()

    def ia_client(**kwargs):
        assert kwargs['timeout'] == 8.0
        return HTTP_CLIENT(transport=httpx.ASGITransport(app=application), **kwargs)

    monkeypatch.setattr(dominio.httpx, 'AsyncClient', ia_client)

    class Database:
        def __init__(self):
            self.inserts = []
            self.commits = 0
            self.connections = 0
            self.selects = []
            self.row = None

        def __enter__(self):
            self.connections += 1
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO predicciones '):
                self.inserts.append(params)
            elif sql == 'SELECT 1':
                self.row = (1,)
            else:
                assert sql == ('SELECT prediccion_id, resultado, confianza, version_modelo, fecha, derivada '
                               'FROM predicciones WHERE prediccion_id = %s')
                self.selects.append(params)
                saved = next((row for row in self.inserts if row[0] == params[0]), None)
                self.row = (saved[0], *saved[2:]) if saved else None
            return self

        def fetchone(self):
            return self.row

        def commit(self):
            self.commits += 1

    database = Database()
    monkeypatch.setattr(dominio.psycopg, 'connect', lambda *args, **kwargs: database)
    gateway = FastAPI()

    @gateway.middleware('http')
    async def nginx_simulado(request: Request, call_next):
        path = request.url.path
        if path == '/api/chat':
            # BFF: reemplaza cabecera del cliente, nunca entrega la clave al navegador.
            request.scope['headers'] = [(k, v) for k, v in request.scope['headers'] if k.lower() != b'x-api-key']
            request.scope['headers'].append((b'x-api-key', os.environ.get('EP3_API_KEY', '').encode()))
        elif path == '/docs':
            request.scope['path'] = '/api/docs'
            request.scope['raw_path'] = b'/api/docs'
        elif path not in ('/api/predict', '/api/health', '/api/openapi.json') and not path.startswith('/api/predicciones/'):
            return JSONResponse(status_code=404, content={'detail': 'Not Found'})
        return await call_next(request)

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


def auth_headers():
    return {'X-API-Key': os.environ['EP3_API_KEY']}


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
def test_contrato_y_version_real_persistida(flow, route):
    client, stub, database, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .912345, 'version_modelo': 'ep3-desplegado-42'})
    response = client.post(route, json={'mensaje': 'No tengo internet'}, headers=auth_headers())
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
    response = client.post(route, json={'mensaje': 'No tengo internet'}, headers=auth_headers())
    assert response.status_code == 503
    assert 'prediccion_id' not in response.json()
    assert database.connections == database.commits == 0
    assert not database.inserts


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
def test_minimiza_pii_antes_de_ia_y_persistencia(flow, route):
    client, stub, database, _ = flow
    minimized = 'Mi correo es [CORREO] y no tengo internet'
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': 'ep3'}, minimized)
    assert client.post(route, json={'mensaje': 'Mi correo es prueba@example.cl y no tengo internet'}, headers=auth_headers()).status_code == 200
    assert database.inserts[0][1] == minimized


@pytest.mark.parametrize('route', ['/api/chat', '/api/predict'])
@pytest.mark.parametrize('payload', [{}, {'mensaje': '   '}, {'mensaje': 'x'}, {'mensaje': 'hola', 'extra': 1}])
def test_validacion_compartida_no_invoca_ni_persiste(flow, route, payload):
    client, _, database, _ = flow
    assert client.post(route, json=payload, headers=auth_headers()).status_code == 422
    assert not database.inserts
    assert database.connections == 0


def test_dominio_rechaza_inferencia_invalida_antes_de_sql(flow, monkeypatch):
    client, _, database, _ = flow
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'intencion': 'falla_conexion', 'confianza': .8, 'version_modelo': '',
    }))
    monkeypatch.setattr(dominio.httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(transport=transport, **kwargs))
    assert client.post('/api/predict', json={'mensaje': 'No tengo internet'}, headers=auth_headers()).status_code == 503
    assert not database.inserts
    assert database.connections == 0


def test_fallo_bd_no_confirma_prediccion(flow, monkeypatch):
    client, stub, database, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': 'ep3'})

    def unavailable(*args, **kwargs):
        raise dominio.psycopg.OperationalError('BD no disponible')

    monkeypatch.setattr(dominio.psycopg, 'connect', unavailable)
    response = client.post('/api/predict', json={'mensaje': 'No tengo internet'}, headers=auth_headers())
    assert response.status_code == 503
    assert 'prediccion_id' not in response.json()
    assert database.commits == 0


def test_gateway_predict_no_evade_dominio():
    config = (ROOT / 'gateway/nginx.conf').read_text(encoding='utf-8')
    block = config.split('location = /api/predict {', 1)[1].split('}', 1)[0]
    assert 'proxy_pass http://dominio:8000/predict;' in block
    assert 'proxy_read_timeout 10s;' in config
    assert 'EP3_API_KEY' not in block
    public, internal = config.split('# Solo red Docker interna.', 1)
    assert 'ia_pool' not in public.split('server {', 1)[1]
    assert 'location /api/ { return 404; }' in public
    assert 'listen 8081;' in internal
    assert 'proxy_pass http://ia_pool/predict;' in internal


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'incorrecta'}], ids=['sin-clave', 'clave-incorrecta'])
@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/predict', '{"mensaje":"No tengo internet"}'),
    ('POST', '/api/predict', '{"mensaje":"x"}'),
    ('POST', '/api/predict', '{json roto'),
    ('GET', '/api/predicciones/00000000-0000-0000-0000-000000000001', None),
    ('GET', '/api/predicciones/no-es-uuid', None),
])
def test_api_401_antes_de_validacion_ia_y_bd(flow, monkeypatch, headers, method, path, body):
    client, _, database, runtime = flow
    monkeypatch.setattr(runtime, 'invoke_endpoint', lambda **kwargs: pytest.fail('No invocar SageMaker'))
    monkeypatch.setattr(dominio.httpx, 'AsyncClient', lambda **kwargs: pytest.fail('No llamar IA'))
    response = client.request(method, path, content=body, headers={**headers, 'Content-Type': 'application/json'})
    assert response.status_code == 401
    assert database.connections == 0
    assert not database.inserts and not database.selects
    assert 'incorrecta' not in response.text


def test_prediccion_y_consulta_guardada_con_clave(flow):
    client, stub, database, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .912345, 'version_modelo': 'ep3-consulta-42'})
    saved = client.post('/api/predict', json={'mensaje': 'No tengo internet'}, headers=auth_headers())
    assert saved.status_code == 200
    prediction = saved.json()
    response = client.get('/api/predicciones/' + prediction['prediccion_id'], headers=auth_headers())
    assert response.status_code == 200
    result = response.json()
    assert result['prediccion_id'] == prediction['prediccion_id']
    assert result['intencion'] == prediction['intencion']
    assert result['confianza'] == prediction['confianza']
    assert result['version_modelo'] == 'ep3-consulta-42'
    assert result['derivar_humano'] is False
    assert result['fecha']
    assert 'entrada' not in result and 'mensaje' not in result
    assert database.selects == [(prediction['prediccion_id'],)]
    assert database.commits == 1  # La consulta no hace un segundo INSERT.


def test_consulta_inexistente_404(flow):
    client, _, database, _ = flow
    assert client.get('/api/predicciones/' + str(uuid4()), headers=auth_headers()).status_code == 404
    assert len(database.selects) == 1
    assert not database.inserts


def test_consulta_uuid_invalido_422_con_clave(flow):
    client, _, database, _ = flow
    assert client.get('/api/predicciones/no-es-uuid', headers=auth_headers()).status_code == 422
    assert database.connections == 0


def test_json_roto_422_con_clave(flow):
    client, _, database, _ = flow
    response = client.post('/api/predict', content='{json roto',
                           headers={**auth_headers(), 'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert database.connections == 0


def test_chat_publico_sin_clave_en_navegador(flow):
    client, stub, _, _ = flow
    expect(stub, {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': 'ep3-chat'})
    response = client.post('/api/chat', json={'mensaje': 'No tengo internet'})
    assert response.status_code == 200
    assert response.json()['version_modelo'] == 'ep3-chat'
    assert os.environ['EP3_API_KEY'] not in response.text


@pytest.mark.parametrize('path', ['/api/health', '/docs', '/api/openapi.json'])
def test_health_y_documentacion_publicas(flow, path):
    client, _, _, _ = flow
    response = client.get(path)
    assert response.status_code == 200
    assert os.environ['EP3_API_KEY'] not in response.text
    if path == '/docs':
        assert '/api/openapi.json' in response.text
    if path == '/api/openapi.json':
        schema = response.json()
        assert schema['components']['securitySchemes']['APIKeyHeader']['name'] == 'X-API-Key'
        assert schema['paths']['/predict']['post']['security'] == [{'APIKeyHeader': []}]


@pytest.mark.parametrize('path', [
    '/api/ia/predict', '/api/ia/modelo', '/api/ia/docs', '/api/invocations',
    '/api/predict/', '/api/chat/', '/api/estadisticas', '/api/docs', '/api',
])
def test_alias_publicos_bloqueados(flow, path):
    client, _, database, _ = flow
    assert client.post(path, json={'mensaje': 'No tengo internet'}).status_code == 404
    assert database.connections == 0


def test_clave_no_configurada_falla_cerrado(flow, monkeypatch):
    client, _, database, _ = flow
    monkeypatch.delenv('EP3_API_KEY')
    assert client.post('/api/predict', json={'mensaje': 'No tengo internet'}).status_code == 401
    assert database.connections == 0


def test_cabeceras_duplicadas_rechazadas(flow):
    client, _, database, _ = flow
    key = os.environ['EP3_API_KEY']
    response = client.post('/api/predict', json={'mensaje': 'No tengo internet'},
                           headers=[('X-API-Key', key), ('X-API-Key', key)])
    assert response.status_code == 401
    assert database.connections == 0


@pytest.mark.parametrize('path', ['/predict', '/chat', '/predicciones/no-es-uuid', '/estadisticas'])
def test_dominio_directo_no_omite_autenticacion(flow, path):
    _, _, database, _ = flow
    with TestClient(dominio.app) as direct:
        assert direct.post(path, content='{json roto').status_code == 401
        assert direct.get(path).status_code == 401
    assert database.connections == 0


def test_consulta_bd_no_disponible_503(flow, monkeypatch):
    client, _, _, _ = flow

    def unavailable(*args, **kwargs):
        raise dominio.psycopg.OperationalError('No disponible')

    monkeypatch.setattr(dominio.psycopg, 'connect', unavailable)
    response = client.get('/api/predicciones/' + str(uuid4()), headers=auth_headers())
    assert response.status_code == 503
