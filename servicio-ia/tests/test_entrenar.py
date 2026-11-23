import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def entrenamiento(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'entrenar.py'
    spec = importlib.util.spec_from_file_location('entrenar', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'DATA', tmp_path / 'tickets.csv')
    monkeypatch.setattr(module, 'HERE', tmp_path)
    return module


@pytest.mark.parametrize('etiquetas', [
    ['facturacion', 'falla_conexion'],
    ['falla_conexion', 'facturacion'],
])
def test_rechaza_etiquetas_contradictorias_antes_de_deduplicar(entrenamiento, monkeypatch, etiquetas):
    pd.DataFrame({
        'texto_consulta': ['consulta sintetica repetida'] * 2,
        'categoria': etiquetas,
    }).to_csv(entrenamiento.DATA, index=False)

    def no_dividir(*args, **kwargs):
        pytest.fail('La contradiccion debe detectarse antes de dividir train/test')

    monkeypatch.setattr(entrenamiento, 'train_test_split', no_dividir)
    with pytest.raises(ValueError, match='Un mismo texto tiene etiquetas contradictorias'):
        entrenamiento.entrenar()
    assert not (entrenamiento.HERE / 'modelo').exists()


@pytest.fixture
def tickets_sinteticos():
    return pd.DataFrame([
        {'texto_consulta': f'{tema} solicitud sintetica {i}', 'categoria': categoria}
        for tema, categoria in [('factura cobros', 'facturacion'), ('conexion internet', 'falla_conexion')]
        for i in range(8)
    ])


def test_deduplica_etiquetas_consistentes_sin_fuga(entrenamiento, tickets_sinteticos, monkeypatch):
    invalidos = pd.DataFrame({
        'texto_consulta': [None, 'x', 'consulta sin etiqueta'],
        'categoria': ['facturacion', 'facturacion', None],
    })
    pd.concat([tickets_sinteticos, tickets_sinteticos, invalidos], ignore_index=True).to_csv(
        entrenamiento.DATA, index=False,
    )
    dividir = entrenamiento.train_test_split

    def dividir_sin_fuga(*args, **kwargs):
        train, test = dividir(*args, **kwargs)
        assert set(train.texto_consulta).isdisjoint(test.texto_consulta)
        return train, test

    monkeypatch.setattr(entrenamiento, 'train_test_split', dividir_sin_fuga)
    entrenamiento.entrenar(min_f1=.85)
    target = entrenamiento.HERE / 'modelo'
    metadata = json.loads((target / 'metadata.json').read_text(encoding='utf-8'))
    assert metadata['filas_totales_ticket'] == 32
    assert metadata['textos_unicos'] == 16
    assert metadata['n_train'] == 12
    assert metadata['n_test'] == 4
    assert metadata['macro_f1'] >= .85
    assert (target / 'clasificador.joblib').is_file()


def test_quality_gate_no_guarda_modelo_rechazado(entrenamiento, tickets_sinteticos):
    tickets_sinteticos.to_csv(entrenamiento.DATA, index=False)
    with pytest.raises(SystemExit) as error:
        entrenamiento.entrenar(min_f1=1.01)
    assert error.value.code == 1
    assert not (entrenamiento.HERE / 'modelo').exists()
