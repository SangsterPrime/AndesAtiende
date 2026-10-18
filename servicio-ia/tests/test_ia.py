from fastapi.testclient import TestClient
from app.main import app


def test_prediccion_real_y_version():
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        r=client.post('/predict',json={'mensaje':'necesito ver mi factura'})
        assert r.status_code==200
        j=r.json()
        assert j['intencion'] in ('facturacion','consulta_general')
        assert j['version_modelo']=='ep2-1.0.0'
        assert 0<=j['confianza']<=1


def test_entrada_invalida_422():
    with TestClient(app) as client:
        assert client.post('/predict',json={'mensaje':'x'}).status_code==422
        assert client.post('/predict',json={'texto':'no tengo internet'}).status_code==422
