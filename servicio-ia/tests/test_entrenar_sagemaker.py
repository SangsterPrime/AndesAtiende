"""Recorrido CLI real con tickets tratados, sin AWS ni escrituras en modelo/ de EP2."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest


BASE = Path(__file__).resolve().parents[1]


def hashes_ep2():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (BASE / 'modelo').glob('*') if path.is_file()
    }


def test_cli_sagemaker_con_tickets_tratados(tmp_path):
    tickets = BASE.parent / 'datos' / 'procesados' / 'tickets.csv'
    if not tickets.is_file():
        pytest.skip('Faltan tickets tratados: preparar datos antes de ejecutar esta integración')
    before = hashes_ep2()
    channel = tmp_path / 'canal train'
    target = tmp_path / 'model output'
    channel.mkdir()
    shutil.copy2(tickets, channel / 'tickets.csv')
    env = os.environ.copy()
    env.update(SM_CHANNEL_TRAIN=str(channel), SM_MODEL_DIR=str(target))

    try:
        result = subprocess.run(
            [sys.executable, str(BASE / 'entrenar.py'), '--min-f1', '0.85', '--model-version', 'ep3-sm-local-test'],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Quality gate OK' in result.stdout
        metadata = json.loads((target / 'metadata.json').read_text(encoding='utf-8'))
        assert metadata['version_modelo'] == 'ep3-sm-local-test'
        assert metadata['fuente'] == 'tickets.csv'
        assert metadata['macro_f1'] >= .85
        assert metadata['umbral_macro_f1'] == .85
        assert set(path.name for path in target.iterdir()) == {'clasificador.joblib', 'metadata.json'}

        # Se recarga el artefacto serializado; no se predice con el objeto de entrenamiento.
        modelo = joblib.load(target / 'clasificador.joblib')
        assert list(modelo.named_steps) == ['tfidf', 'classifier']
        assert sorted(map(str, modelo.classes_)) == metadata['clases']
        datos = pd.read_csv(channel / 'tickets.csv').dropna(subset=['categoria', 'texto_consulta'])
        datos = datos[datos.texto_consulta.str.len() >= 3]
        assert metadata['filas_totales_ticket'] == len(datos)
        assert metadata['textos_unicos'] == datos.texto_consulta.nunique()
        assert metadata['n_train'] + metadata['n_test'] == metadata['textos_unicos']
        consultas = datos.texto_consulta.head(3).tolist()
        predicciones = modelo.predict(consultas)
        probabilidades = modelo.predict_proba(consultas)
        assert len(predicciones) == len(consultas)
        assert set(predicciones).issubset(metadata['clases'])
        assert probabilidades.shape == (len(consultas), len(metadata['clases']))
        assert np.isfinite(probabilidades).all()
        assert ((probabilidades >= 0) & (probabilidades <= 1)).all()
        assert np.allclose(probabilidades.sum(axis=1), 1)
        print(json.dumps({
            'version_modelo': metadata['version_modelo'],
            'filas_totales_ticket': metadata['filas_totales_ticket'],
            'textos_unicos': metadata['textos_unicos'],
            'macro_f1': metadata['macro_f1'], 'n_test': metadata['n_test'],
            'predicciones_recargadas': list(map(str, predicciones)),
        }, ensure_ascii=False))
    finally:
        assert hashes_ep2() == before, 'Los artefactos locales de EP2 deben conservarse intactos'
