"""Job idempotente: crea esquema y carga las tablas del laboratorio una sola vez."""
from pathlib import Path
import csv
import os
import psycopg
from psycopg import sql

DATABASE_URL=os.getenv('DATABASE_URL','postgresql://andes:andes_local_demo@db:5432/andesdb')
DIR=Path('/app/datos')
DDL='''
CREATE TABLE IF NOT EXISTS clientes (cliente_id TEXT PRIMARY KEY, plan TEXT, tipo_servicio TEXT, region TEXT, segmento TEXT);
CREATE TABLE IF NOT EXISTS tickets (ticket_id TEXT PRIMARY KEY, cliente_id TEXT REFERENCES clientes(cliente_id), categoria TEXT, texto_consulta TEXT, fecha_apertura TEXT, fecha_cierre TEXT);
CREATE TABLE IF NOT EXISTS conversaciones (conversacion_id TEXT PRIMARY KEY, cliente_id TEXT REFERENCES clientes(cliente_id), canal TEXT, intencion TEXT);
CREATE TABLE IF NOT EXISTS faq (articulo_id TEXT PRIMARY KEY, pregunta TEXT, respuesta TEXT, categoria TEXT, vigente BOOLEAN NOT NULL);
CREATE TABLE IF NOT EXISTS predicciones (prediccion_id UUID PRIMARY KEY, entrada TEXT NOT NULL, resultado TEXT NOT NULL, confianza DOUBLE PRECISION NOT NULL, version_modelo TEXT NOT NULL, fecha TIMESTAMPTZ NOT NULL, derivada BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS idx_predicciones_fecha ON predicciones (fecha DESC);
'''

def cargar(db,archivo,table,columns):
    with (DIR/f'{archivo}.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=csv.DictReader(f)
        vals=[[row.get(c) or None for c in columns] for row in rows]
    query=sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join([sql.Placeholder()]*len(columns)))
    with db.cursor() as cur:
        cur.executemany(query, vals)
    print(f'[{table}] {len(vals)} registros evaluados (ON CONFLICT DO NOTHING)',flush=True)

with psycopg.connect(DATABASE_URL,connect_timeout=10) as conn:
    for sentence in DDL.strip().split(';'):
        if sentence.strip():conn.execute(sentence)
    cargar(conn,'clientes','clientes',['cliente_id','plan','tipo_servicio','region','segmento'])
    cargar(conn,'tickets','tickets',['ticket_id','cliente_id','categoria','texto_consulta','fecha_apertura','fecha_cierre'])
    # Alias explícito para no depender de que el CSV tenga el mismo nombre de columna.
    with (DIR/'conversaciones.csv').open(encoding='utf-8',newline='') as f:
        rows=csv.DictReader(f)
        values=[(r['conversacion_id'],r.get('cliente_id') or None,r['canal'],r.get('intencion_detectada') or None) for r in rows]
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO conversaciones (conversacion_id,cliente_id,canal,intencion) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',values)
    print(f'[conversaciones] {len(values)} registros evaluados',flush=True)
    with (DIR/'faq.csv').open(encoding='utf-8',newline='') as f:
        rows=csv.DictReader(f)
        values=[(r['articulo_id'],r['pregunta'],r['respuesta'],r.get('categoria') or None,r['vigente']=='1') for r in rows]
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO faq (articulo_id,pregunta,respuesta,categoria,vigente) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',values)
    print(f'[faq] {len(values)} registros evaluados',flush=True)
    conn.commit()
print('Carga terminada correctamente',flush=True)
