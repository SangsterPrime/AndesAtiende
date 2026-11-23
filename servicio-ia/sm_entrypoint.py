"""Contrato BYOC de SageMaker: `docker run IMAGE train|serve`, sin SDK ni AWS calls."""
import json
import math
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent


def training_command(config_dir=Path('/opt/ml/input/config')):
    params = json.loads((Path(config_dir) / 'hyperparameters.json').read_text(encoding='utf-8'))
    if set(params) - {'min-f1', 'model-version'}:
        raise ValueError('Hiperparámetros no reconocidos')
    minimum = float(params.get('min-f1', '.60'))
    version = params.get('model-version', 'ep2-1.0.0')
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError('min-f1 debe estar entre 0 y 1')
    if not isinstance(version, str) or not version.strip():
        raise ValueError('model-version no puede estar vacío')
    return [sys.executable, str(HERE / 'entrenar.py'), '--min-f1', str(minimum), '--model-version', version]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ['train']:
        # Sin Training Toolkit, SageMaker monta estas rutas pero no garantiza SM_*.
        os.environ.setdefault('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train')
        os.environ.setdefault('SM_MODEL_DIR', '/opt/ml/model')
        command = training_command(Path(os.environ.get('SM_INPUT_CONFIG_DIR', '/opt/ml/input/config')))
    elif args == ['serve']:
        command = [sys.executable, '-m', 'uvicorn', 'sm_serving:app', '--host', '0.0.0.0',
                   '--port', '8080', '--workers', '1', '--no-access-log']
    else:
        raise SystemExit('Uso: sm_entrypoint.py train|serve')
    # exec conserva SIGTERM y el código de salida del quality gate.
    os.execv(command[0], command)


if __name__ == '__main__':
    main()
