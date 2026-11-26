from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import httpx
import pytest

from app import llm, llm_worker


def test_nvidia_reintenta_429_y_envia_solo_faq_revisada():
    request = httpx.Request('POST', 'https://integrate.api.nvidia.com')
    successful = {'choices': [{'message': {'content': 'Revisa el router.'}}]}
    with patch.object(llm.httpx, 'post', side_effect=[
        httpx.Response(429, request=request),
        httpx.Response(429, request=request),
        httpx.Response(200, json=successful, request=request),
    ]) as post:
        wait = Mock()
        assert llm.generate('falla_conexion', 'key-test', 'model-test', wait) == 'Revisa el router.'
        assert [c.args[0] for c in wait.call_args_list] == [1, 2]
        for call in post.call_args_list:
            payload = call.kwargs['json']
            assert payload['messages'][1]['content'] == (
                'Consulta: Mi conexión a internet falla.\nFAQ: '
                'Reinicia el router, revisa las luces y verifica que no haya corte en tu zona.'
            )


def test_worker_persiste_modo_degradado_si_nvidia_no_responde():
    db = Mock()
    db.execute.return_value.fetchone.return_value = ('falla_conexion',)
    prediction = str(uuid4())
    with patch.object(llm_worker, 'generate', side_effect=httpx.ReadTimeout('timeout')):
        llm_worker.consume(db, prediction.encode(), 'key-test', 'model-test')
    assert db.execute.call_args.args[1] == ('degradada', None, prediction)
    assert 'entrada' not in db.execute.call_args_list[0].args[0]


def test_worker_ignora_mensaje_duplicado_si_ya_se_completo():
    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    with patch.object(llm_worker, 'generate') as generate:
        llm_worker.consume(db, str(uuid4()).encode(), 'key-test', 'model-test')
    generate.assert_not_called()


def test_worker_publica_id_durable_y_ack_despues_de_persistir(monkeypatch):
    prediction = str(uuid4())
    for name, value in {'NVIDIA_API_KEY': 'fake-key', 'NVIDIA_MODEL': 'fake-model',
                        'DATABASE_URL': 'fake-db', 'RABBITMQ_PASSWORD': 'fake-password'}.items():
        monkeypatch.setenv(name, value)
    events = []
    db = Mock()
    cursor = Mock()
    db.execute.side_effect = lambda sql, params=None: (events.append(('sql', sql)) or cursor)
    cursor.fetchone.side_effect = [(prediction,), ('falla_conexion',)]
    channel = Mock()
    channel.basic_get.side_effect = [(None, None, None), (Mock(delivery_tag=7), None, prediction.encode()), KeyboardInterrupt]
    channel.basic_ack.side_effect = lambda tag: events.append(('ack', tag))
    broker_context, db_context = MagicMock(), MagicMock()
    broker_context.__enter__.return_value.channel.return_value = channel
    db_context.__enter__.return_value = db
    monkeypatch.setattr(llm_worker.pika, 'BlockingConnection', lambda params: broker_context)
    connect = Mock(return_value=db_context)
    monkeypatch.setattr(llm_worker.psycopg, 'connect', connect)
    monkeypatch.setattr(llm_worker, 'generate', lambda *args: 'Respuesta de prueba')
    with pytest.raises(KeyboardInterrupt):
        llm_worker.run()
    assert connect.call_args.kwargs['autocommit'] is True
    channel.queue_declare.assert_called_once_with(queue=llm_worker.QUEUE, durable=True)
    channel.confirm_delivery.assert_called_once()
    sent = channel.basic_publish.call_args.kwargs
    assert sent['body'] == prediction.encode('ascii')
    assert sent['mandatory'] is True and sent['properties'].delivery_mode == 2
    assert events[-1] == ('ack', 7)
    assert 'UPDATE respuestas_llm SET estado=%s' in events[-2][1]


def test_worker_descarta_id_invalido_sin_bd_ni_nvidia():
    db = Mock()
    with patch.object(llm_worker, 'generate') as generate:
        llm_worker.consume(db, b'\xff-invalido', 'fake-key', 'fake-model')
    db.execute.assert_not_called()
    generate.assert_not_called()


def test_nvidia_rechaza_una_cita_sola():
    request = httpx.Request('POST', 'https://integrate.api.nvidia.com')
    with patch.object(llm.httpx, 'post', return_value=httpx.Response(
        200, request=request, json={'choices': [{'message': {'content': 'Artículo FQ1001'}}]},
    )):
        try:
            llm.generate('falla_conexion', 'test', 'test', Mock())
        except ValueError:
            return
    raise AssertionError('Una cita sola no debe reemplazar la orientación inicial')
