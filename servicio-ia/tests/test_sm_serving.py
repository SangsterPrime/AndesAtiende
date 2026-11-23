"""Entrena tickets tratados en temporal y sirve el artefacto, sin tocar modelo/ EP2."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from fastapi.testclient import TestClient
import pytest


BASE = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, BASE / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(scope='module')
def artifact(tmp_path_factory):
    tickets = BASE.parent / 'datos/procesados/tickets.csv'
    if not tickets.exists():
        pytest.skip('Requiere tickets.csv tratado; no se regeneran datos en esta prueba')
    path = tmp_path_factory.mktemp('sagemaker-serving')
    channel = path / 'input/data/train'
    config = path / 'input/config'
    target = path / 'model'
    channel.mkdir(parents=True)
    config.mkdir(parents=True)
    shutil.copy2(tickets, channel / 'tickets.csv')
    (config / 'hyperparameters.json').write_text(json.dumps({
        'model-version': 'ep3-serving-test', 'min-f1': '0.85',
    }), encoding='utf-8')
    env = {**os.environ, 'SM_CHANNEL_TRAIN': str(channel), 'SM_MODEL_DIR': str(target),
           'SM_INPUT_CONFIG_DIR': str(config)}
    result = subprocess.run([sys.executable, str(BASE / 'sm_entrypoint.py'), 'train'],
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    # Simula el empaquetado de SageMaker y su expansión en /opt/ml/model.
    archive = path / 'model.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in ('metadata.json', 'clasificador.joblib'):
            bundle.add(target / name, arcname=name)
    extracted = path / 'inference-model'
    extracted.mkdir()
    with tarfile.open(archive) as bundle:
        for name in ('metadata.json', 'clasificador.joblib'):
            (extracted / name).write_bytes(bundle.extractfile(name).read())
    return extracted, archive


def test_model_tar_gz_y_contrato_http_real(artifact):
    serving = module('sm_serving')
    directory, archive = artifact
    from scripts.aws.ep3 import validate_artifact
    metadata = validate_artifact(archive.read_bytes(), 'ep3-serving-test', .85)
    model, _ = serving.load_model(directory)
    with TestClient(serving.create_app(directory)) as client:
        assert client.get('/ping').status_code == 200
        assert client.post('/ping').status_code == 200
        response = client.post('/invocations', json={'mensaje': 'No tengo internet'})
        assert response.status_code == 200
        result = response.json()
        assert set(result) == {'intencion', 'probabilidad', 'version_modelo'}
        probabilities = model.predict_proba(['No tengo internet'])[0]
        assert result['intencion'] == str(model.classes_[probabilities.argmax()])
        assert result['probabilidad'] == pytest.approx(float(probabilities.max()))
        assert result['version_modelo'] == metadata['version_modelo']
        assert 0 <= result['probabilidad'] <= 1


@pytest.mark.parametrize('payload', [
    {}, {'mensaje': 'x'}, {'mensaje': '   '}, {'mensaje': 'a' * 1201},
    {'mensaje': 123}, {'mensaje': 'hola', 'otra': True},
])
def test_rechaza_payload_invalido(artifact, payload):
    with TestClient(module('sm_serving').create_app(artifact[0])) as client:
        assert client.post('/invocations', json=payload).status_code == 422


def test_modelo_ausente_no_inventa_disponibilidad(tmp_path):
    with TestClient(module('sm_serving').create_app(tmp_path)) as client:
        assert client.get('/ping').status_code == 503
        assert client.post('/invocations', json={'mensaje': 'Mi factura'}).status_code == 503


def test_rechaza_sklearn_incompatible_antes_de_joblib(artifact, tmp_path, monkeypatch):
    serving = module('sm_serving')
    metadata = json.loads((artifact[0] / 'metadata.json').read_text(encoding='utf-8'))
    metadata['version_sklearn'] = 'version-incompatible'
    (tmp_path / 'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
    monkeypatch.setattr(serving.joblib, 'load', lambda *args: pytest.fail('No cargar pickle incompatible'))
    with pytest.raises(ValueError, match='scikit-learn'):
        serving.load_model(tmp_path)


def test_fallo_de_prediccion_no_devuelve_resultado_ficticio(artifact, monkeypatch):
    serving = module('sm_serving')
    with TestClient(serving.create_app(artifact[0])) as client:
        def fail(*args):
            raise ValueError('Fallo simulado')
        monkeypatch.setattr(serving, 'predict', fail)
        response = client.post('/invocations', json={'mensaje': 'Mi factura'})
        assert response.status_code == 503
        assert 'intencion' not in response.json()


def test_entrypoint_train_y_serve(tmp_path, monkeypatch):
    entry = module('sm_entrypoint')
    (tmp_path / 'hyperparameters.json').write_text('{"model-version":"ep3-test","min-f1":"0.85"}')
    monkeypatch.setenv('SM_INPUT_CONFIG_DIR', str(tmp_path))
    monkeypatch.delenv('SM_CHANNEL_TRAIN', raising=False)
    monkeypatch.delenv('SM_MODEL_DIR', raising=False)
    calls = []
    monkeypatch.setattr(entry.os, 'execv', lambda exe, args: calls.append(args))
    entry.main(['train'])
    assert calls[0][-4:] == ['--min-f1', '0.85', '--model-version', 'ep3-test']
    assert os.environ['SM_CHANNEL_TRAIN'] == '/opt/ml/input/data/train'
    assert os.environ['SM_MODEL_DIR'] == '/opt/ml/model'
    entry.main(['serve'])
    assert '8080' in calls[1] and calls[1][calls[1].index('--workers') + 1] == '1'
    with pytest.raises(SystemExit):
        entry.main(['invalid'])


@pytest.mark.parametrize('params', [
    {'min-f1': 'NaN'}, {'min-f1': '1.1'}, {'model-version': ''}, {'unknown': 'value'},
])
def test_entrypoint_valida_hiperparametros(tmp_path, params):
    (tmp_path / 'hyperparameters.json').write_text(json.dumps(params))
    with pytest.raises(ValueError):
        module('sm_entrypoint').training_command(tmp_path)
