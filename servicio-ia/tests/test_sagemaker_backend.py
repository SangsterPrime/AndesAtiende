import io
import json

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi.testclient import TestClient
import pytest

from app import main


ENDPOINT = 'andes-g5-ep3-test-endpoint'


@pytest.fixture
def remote(monkeypatch, tmp_path):
    runtime = boto3.client('sagemaker-runtime', region_name='us-east-1',
                           aws_access_key_id='testing', aws_secret_access_key='testing',
                           aws_session_token='testing')

    def client(service, **kwargs):
        assert service == 'sagemaker-runtime'
        assert kwargs['region_name'] == 'us-east-1'
        assert set(kwargs) == {'region_name', 'config'}  # Sin claves estáticas.
        assert kwargs['config'].read_timeout == 5
        assert kwargs['config'].retries['total_max_attempts'] == 1
        return runtime

    monkeypatch.setenv('IA_BACKEND', 'sagemaker')
    monkeypatch.setenv('SAGEMAKER_ENDPOINT_NAME', ENDPOINT)
    monkeypatch.setenv('MODEL_DIR', str(tmp_path / 'modelo-inexistente'))
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.setattr(main.boto3, 'client', client)
    monkeypatch.setattr(main.joblib, 'load', lambda *args: pytest.fail('No cargar modelo local en modo SageMaker'))
    with Stubber(runtime) as stub, TestClient(main.create_app()) as api:
        assert api.get('/health').json() == {'status': 'ok', 'backend': 'sagemaker'}
        yield api, stub
        stub.assert_no_pending_responses()


def expected():
    return {'EndpointName': ENDPOINT, 'ContentType': 'application/json', 'Accept': 'application/json',
            'Body': json.dumps({'mensaje': 'No tengo internet'}, ensure_ascii=False).encode('utf-8')}


def response(payload, content_type='application/json'):
    data = json.dumps(payload).encode('utf-8')
    return {'Body': StreamingBody(io.BytesIO(data), len(data)), 'ContentType': content_type}


def test_sagemaker_adapta_probabilidad_y_conserva_version(remote):
    api, stub = remote
    assert api.get('/modelo').json() == {'backend': 'sagemaker', 'endpoint': ENDPOINT}
    stub.add_response('invoke_endpoint', response({
        'intencion': 'falla_conexion', 'probabilidad': .923456, 'version_modelo': 'ep3-real-42',
    }), expected())
    result = api.post('/predict', json={'mensaje': 'No tengo internet'})
    assert result.status_code == 200
    data = result.json()
    assert set(data) == {'intencion', 'confianza', 'version_modelo', 'latencia_ms', 'replica'}
    assert data['intencion'] == 'falla_conexion'
    assert data['confianza'] == .923456
    assert data['version_modelo'] == 'ep3-real-42'
    assert data['latencia_ms'] >= 0


@pytest.mark.parametrize('payload', [
    {}, [], {'intencion': 'falla_conexion', 'probabilidad': .9},
    {'intencion': '', 'probabilidad': .9, 'version_modelo': 'ep3'},
    {'intencion': 'falla_conexion', 'probabilidad': True, 'version_modelo': 'ep3'},
    {'intencion': 'falla_conexion', 'probabilidad': '0.9', 'version_modelo': 'ep3'},
    {'intencion': 'falla_conexion', 'probabilidad': float('nan'), 'version_modelo': 'ep3'},
    {'intencion': 'falla_conexion', 'probabilidad': 1.1, 'version_modelo': 'ep3'},
    {'intencion': 'falla_conexion', 'probabilidad': .9, 'version_modelo': '   '},
])
def test_sagemaker_rechaza_respuesta_invalida(remote, payload):
    api, stub = remote
    stub.add_response('invoke_endpoint', response(payload), expected())
    result = api.post('/predict', json={'mensaje': 'No tengo internet'})
    assert result.status_code == 503
    assert 'intencion' not in result.json()


@pytest.mark.parametrize('code', ['ModelNotReadyException', 'AccessDeniedException', 'ModelError'])
def test_sagemaker_error_aws_controlado(remote, code):
    api, stub = remote
    stub.add_client_error('invoke_endpoint', code, 'Detalle AWS no debe exponerse', expected_params=expected())
    result = api.post('/predict', json={'mensaje': 'No tengo internet'})
    assert result.status_code == 503
    assert 'Detalle AWS' not in result.text


def test_sagemaker_timeout_controlado(remote, monkeypatch):
    from botocore.exceptions import ReadTimeoutError
    api, _ = remote

    def timeout(**kwargs):
        raise ReadTimeoutError(endpoint_url='https://runtime.sagemaker.us-east-1.amazonaws.com')

    monkeypatch.setattr(api.app.state.runtime, 'invoke_endpoint', timeout)
    assert api.post('/predict', json={'mensaje': 'No tengo internet'}).status_code == 503


def test_sagemaker_cierra_body_y_rechaza_json_roto(remote):
    api, stub = remote
    stream = io.BytesIO(b'not-json')
    stub.add_response('invoke_endpoint', {'Body': StreamingBody(stream, 8), 'ContentType': 'application/json'}, expected())
    assert api.post('/predict', json={'mensaje': 'No tengo internet'}).status_code == 503
    assert stream.closed


@pytest.mark.parametrize('content_type,data', [
    ('text/html', b'<html>error</html>'),
    ('application/json', b' ' * (main.MAX_RESPONSE_BYTES + 1)),
], ids=['content-type-invalido', 'respuesta-demasiado-grande'])
def test_sagemaker_rechaza_tipo_y_tamano_de_respuesta(remote, content_type, data):
    api, stub = remote
    stream = io.BytesIO(data)
    stub.add_response('invoke_endpoint', {
        'Body': StreamingBody(stream, len(data)), 'ContentType': content_type,
    }, expected())
    assert api.post('/predict', json={'mensaje': 'No tengo internet'}).status_code == 503
    assert stream.closed


@pytest.mark.parametrize('backend,endpoint', [('sagemaker', ''), ('desconocido', 'endpoint')])
def test_configuracion_invalida_no_recurre_al_modelo_local(monkeypatch, backend, endpoint):
    monkeypatch.setenv('IA_BACKEND', backend)
    monkeypatch.setenv('SAGEMAKER_ENDPOINT_NAME', endpoint)
    monkeypatch.setattr(main.joblib, 'load', lambda *args: pytest.fail('No recurrir a EP2'))
    monkeypatch.setattr(main.boto3, 'client', lambda *args, **kwargs: pytest.fail('No contactar AWS'))
    with TestClient(main.create_app()) as api:
        assert api.get('/health').status_code == 503
        assert api.post('/predict', json={'mensaje': 'No tengo internet'}).status_code == 503


@pytest.mark.parametrize('payload', [{}, {'mensaje': '   '}, {'mensaje': 'x'}, {'mensaje': 'hola', 'otra': 1}])
def test_sagemaker_valida_entrada_sin_invocacion(remote, payload):
    api, _ = remote
    assert api.post('/predict', json=payload).status_code == 422


def test_local_sin_modelo_no_contacta_aws(monkeypatch, tmp_path):
    monkeypatch.setenv('IA_BACKEND', 'local')
    monkeypatch.setenv('MODEL_DIR', str(tmp_path / 'no-modelo'))
    monkeypatch.setattr(main.boto3, 'client', lambda *args, **kwargs: pytest.fail('EP2 no usa AWS'))
    with TestClient(main.create_app()) as api:
        assert api.get('/health').status_code == 503
        assert api.post('/predict', json={'mensaje': 'No tengo internet'}).status_code == 503
