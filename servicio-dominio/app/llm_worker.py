"""Relay the PostgreSQL outbox through RabbitMQ and persist NVIDIA results."""
import os
from time import sleep
from uuid import UUID

import httpx
import pika
import psycopg

from app.llm import generate

QUEUE = 'andesatiende.llm.v1'


def consume(db, body, key, model):
    try:
        prediction = str(UUID(body.decode('ascii')))
    except ValueError:
        return
    row = db.execute(
        "SELECT intencion FROM respuestas_llm WHERE prediccion_id=%s AND estado='pendiente'",
        (prediction,),
    ).fetchone()
    if row is None:
        return
    try:
        answer = generate(row[0], key, model, sleep)
        status = 'lista'
    except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
        print(f'NVIDIA: {type(error).__name__}', flush=True)
        answer, status = None, 'degradada'
    db.execute(
        "UPDATE respuestas_llm SET estado=%s, respuesta=%s, completada=now() "
        "WHERE prediccion_id=%s AND estado='pendiente'",
        (status, answer, prediction),
    )


def run():
    key, model = os.environ['NVIDIA_API_KEY'], os.environ['NVIDIA_MODEL']
    params = pika.ConnectionParameters(
        host='rabbitmq', credentials=pika.PlainCredentials('andes', os.environ['RABBITMQ_PASSWORD']),
        heartbeat=60, socket_timeout=5, blocked_connection_timeout=5,
    )
    while True:
        try:
            with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, connect_timeout=3) as db:
                with pika.BlockingConnection(params) as broker:
                    channel = broker.channel()
                    channel.queue_declare(queue=QUEUE, durable=True)
                    channel.confirm_delivery()
                    while True:
                        delivery, _, body = channel.basic_get(QUEUE)
                        if delivery:
                            consume(db, body, key, model)
                            channel.basic_ack(delivery.delivery_tag)
                            continue
                        db.execute(
                            "UPDATE respuestas_llm SET estado='degradada', completada=now() "
                            "WHERE estado='pendiente' AND creada < now() - interval '25 seconds'"
                        )
                        job = db.execute(
                            "SELECT prediccion_id FROM respuestas_llm WHERE estado='pendiente' "
                            "ORDER BY creada, prediccion_id LIMIT 1"
                        ).fetchone()
                        if job:
                            channel.basic_publish(
                                exchange='', routing_key=QUEUE, body=str(job[0]).encode('ascii'),
                                mandatory=True, properties=pika.BasicProperties(delivery_mode=2),
                            )
                        else:
                            broker.sleep(0.25)
        except (pika.exceptions.AMQPError, psycopg.Error, OSError) as error:
            print(f'Worker: {type(error).__name__}; reintento en 2 s', flush=True)
            sleep(2)


if __name__ == '__main__':
    run()
