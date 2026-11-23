"""Validaciones locales de la configuración; no sustituyen nginx -t desplegado."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def shell():
    path = shutil.which('sh')
    if path is None and os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/usr/bin/sh.exe'
        if candidate.is_file():
            path = str(candidate)
    if path is None:
        pytest.skip('Requiere un shell POSIX para probar el guard del gateway')
    return path


@pytest.mark.parametrize('value', [None, '', 'corta', 'a' * 129, 'a' * 32 + '";', 'a' * 32 + '\n'])
def test_guard_rechaza_clave_ausente_o_inyectable_sin_imprimirla(shell, value):
    env = {**os.environ}
    env.pop('EP3_API_KEY', None)
    if value is not None:
        env['EP3_API_KEY'] = value
    result = subprocess.run([shell, (ROOT / 'gateway/15-check-api-key.sh').as_posix()],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert '32 a 128' in result.stderr
    if value:
        assert value not in result.stdout + result.stderr


def test_guard_acepta_clave_valida_sin_imprimirla(shell):
    key = secrets.token_urlsafe(32)
    result = subprocess.run([shell, (ROOT / 'gateway/15-check-api-key.sh').as_posix()],
                            env={**os.environ, 'EP3_API_KEY': key}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout == result.stderr == ''


def test_template_solo_inyecta_en_chat_y_no_publica_listener_interno():
    template = (ROOT / 'gateway/nginx.conf').read_text(encoding='utf-8')
    assert template.count('${EP3_API_KEY}') == 1
    chat = template.split('location = /api/chat {', 1)[1].split('\n        }', 1)[0]
    assert 'proxy_set_header X-API-Key "${EP3_API_KEY}";' in chat
    assert 'proxy_pass http://dominio:8000/chat;' in chat
    assert 'location = /api/health { proxy_pass http://dominio:8000/health; }' in template
    assert 'location = /docs { proxy_pass http://dominio:8000/docs; }' in template
    assert 'location ^~ /api/predicciones/' in template
    dockerfile = (ROOT / 'gateway/Dockerfile').read_text(encoding='utf-8')
    assert 'NGINX_ENVSUBST_FILTER=^EP3_API_KEY$' in dockerfile
    assert '/etc/nginx/templates/nginx.conf.template' in dockerfile
    assert '8081:' not in (ROOT / 'compose.yaml').read_text(encoding='utf-8')
    assert '8081:' not in (ROOT / 'compose.ep3.yaml').read_text(encoding='utf-8')
    # El secreto no se configura en el build ni en el frontend.
    assert 'ARG EP3_API_KEY' not in dockerfile and 'ENV EP3_API_KEY=' not in dockerfile
    for path in (ROOT / 'front/src').rglob('*'):
        if path.is_file():
            assert 'EP3_API_KEY' not in path.read_text(encoding='utf-8')
