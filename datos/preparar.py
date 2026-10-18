"""ETL repetible para EP2: perfilado, deduplicación, normalización y exportación.
Se ejecuta en GitHub Actions antes del entrenamiento y del docker build.
"""
from pathlib import Path
import argparse
import json
import re
import unicodedata
import pandas as pd

ROOT = Path(__file__).resolve().parent


def norma(x):
    if pd.isna(x): return ''
    s = unicodedata.normalize('NFKD',str(x).strip().lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s)

MAP = {
    'facturacion':['facturacion','fact','fact.','cobros','facturación'],
    'falla_conexion':['falla_tecnica','falla tecnica','soporte_tecnico','soporte tecnico','tecnico','soporte','falla_conexion','falla','sin_internet'],
    'cambio_plan':['cambio_plan','cambio plan','cambio de plan','upgrade'],
    'estado_visita':['visita_tecnica','visita tecnica','agenda_tecnico','visita','estado_visita'],
    'anulacion':['anulacion','cancelacion','baja'],
    'equipos':['equipos','equipo','router'],
    'cobertura':['cobertura','senal'],
    'portabilidad':['portabilidad','porta'],
    'roaming':['roaming','internacional'],
    'television':['tv','television'],
    'consulta_general':['otros','consulta_general','general','desconocida','unknown','consulta saldo','consulta_saldo','saldo'],
}
# Excepción: el bot original usa consulta_saldo como etiqueta específica.
MAP['consulta_general'] = [x for x in MAP['consulta_general'] if x not in ('consulta saldo','consulta_saldo','saldo')]
MAP['facturacion'] += ['consulta saldo','consulta_saldo','saldo']
CATS = {norma(alias): canonical for canonical,aliases in MAP.items() for alias in aliases}

def canon_cat(s):
    key = norma(s)
    if key == '' or key == '-': return None
    return CATS.get(key)

def stats(df, key):
    return {'filas':int(len(df)), 'columnas':int(len(df.columns)), 'nulos_por_columna':{k:int(v) for k,v in df.isna().sum().items()},'duplicados_exactos':int(df.duplicated().sum()),'duplicados_por_clave':int(df[key].duplicated().sum()), 'tipos':df.dtypes.astype(str).to_dict()}

def fecha(series):
    return pd.to_datetime(series,format='mixed',utc=True,errors='coerce')

def iso(series):
    return series.dt.strftime('%Y-%m-%dT%H:%M:%SZ').where(series.notna(),'')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrada',type=Path,default=ROOT/'entrada')
    parser.add_argument('--salida',type=Path,default=ROOT/'procesados')
    args=parser.parse_args(); args.salida.mkdir(parents=True,exist_ok=True)
    raw={n:pd.read_csv(args.entrada/f'{n}.csv',dtype=str,keep_default_na=True) for n in ('clientes','tickets','conversaciones','faq')}
    keys={'clientes':'cliente_id','tickets':'ticket_id','conversaciones':'conversacion_id','faq':'articulo_id'}
    reporte={'archivos':{},'tratamiento':{},'integracion':{},'modelo':{}}
    for name,df in raw.items():
        reporte['archivos'][name]={'antes':stats(df,keys[name])}
        df=df.drop_duplicates(subset=[keys[name]],keep='first').copy()
        for col in ('canal','canal_preferido'):
            if col in df:
                m={'wa':'whatsapp','sitio_web':'web','app_movil':'app','aplicacion':'app','telefono':'telefono','teléfono':'telefono','fono':'telefono','call':'telefono'}
                df[col]=df[col].map(lambda x:m.get(norma(x),norma(x) or 'desconocido'))
        for col in ('categoria','intencion_detectada'):
            if col in df: df[col]=df[col].map(canon_cat)
        if name=='clientes':
            df['tipo_servicio']=df['tipo_servicio'].map(lambda x: {'movil':'movil','paquete':'combo'}.get(norma(x),norma(x)))
            df['segmento']=df['segmento'].map(lambda x: norma(x) or 'no_informado')
            df['canal_preferido']=df['canal_preferido'].fillna('desconocido')
            df['acepta_contacto']=df['acepta_contacto'].map(lambda x: '1' if norma(x) in ('1','si','true') else ('0' if norma(x) in ('0','no','false') else ''))
            df['deuda_vigente']=pd.to_numeric(df['deuda_vigente'].str.replace(',','.',regex=False),errors='coerce').clip(lower=0)
            df['fecha_alta']=iso(fecha(df['fecha_alta']))
            df['antiguedad_meses']=pd.to_numeric(df['antiguedad_meses'],errors='coerce').clip(lower=0)
            df['region']=df['region'].fillna('no_informada').str.strip()
        elif name=='tickets':
            inicio=fecha(df['fecha_apertura']); cierre=fecha(df['fecha_cierre'])
            invertidas=(cierre < inicio)
            reporte['tratamiento']['tickets_cierre_anterior_apertura']=int(invertidas.sum())
            reporte['tratamiento']['tickets_cierre_nulo_original']=int(cierre.isna().sum())
            cierre=cierre.mask(invertidas)
            df['fecha_apertura']=iso(inicio)
            df['fecha_cierre']=iso(cierre)
            df['csat']=pd.to_numeric(df['csat'],errors='coerce')
            reporte['tratamiento']['tickets_csat_escala_6_a_10']=int(df['csat'].between(6,10).sum())
            # La escala 1-5 y 1-10 es ambigua; se conserva origen y no se fusiona a ciegas.
            df['csat']=df['csat'].where(df['csat'].between(1,10))
            df['resuelto']=df['resuelto'].map(lambda x: '1' if norma(x) in ('1','si','true') else ('0' if norma(x) in ('0','no','false') else ''))
            df['texto_consulta']=df['texto_consulta'].fillna('').astype(str).str.strip()
        elif name=='conversaciones':
            df['inicio']=iso(fecha(df['inicio']))
            df['fin']=iso(fecha(df['fin']))
            df['idioma']=df['idioma'].map(lambda x:norma(x) or 'no_informado')
        else:
            df['vigente']=df['vigente'].map(lambda x:'1' if norma(x) in ('1','si','true') else '0')
            df['ultima_edicion']=iso(fecha(df['ultima_edicion']))
            df['pregunta']=df['pregunta'].fillna('').str.strip()
            df['respuesta']=df['respuesta'].fillna('').str.strip()
        raw[name]=df
        reporte['archivos'][name]['despues']=stats(df,keys[name])
        reporte['tratamiento'][name+'_duplicados_descartados']=reporte['archivos'][name]['antes']['duplicados_por_clave']
    ids=set(raw['clientes']['cliente_id'].dropna())
    for name in ('tickets','conversaciones'):
        missing=~raw[name]['cliente_id'].isin(ids)&raw[name]['cliente_id'].notna()&(raw[name]['cliente_id']!='')
        reporte['integracion'][name+'_sin_cliente']=int(missing.sum())
        # Sin perder información operativa, se conserva fila y la FK queda NULL.
        raw[name].loc[missing,'cliente_id']=None
    tr=raw['tickets']
    entrenable=tr['categoria'].notna()&(tr['texto_consulta'].str.len()>=3)
    reporte['modelo']['tickets_etiquetados_utilizables']=int(entrenable.sum())
    reporte['modelo']['tickets_excluidos_del_entrenamiento']=int((~entrenable).sum())
    reporte['modelo']['clases']=tr.loc[entrenable,'categoria'].value_counts().to_dict()
    for name,df in raw.items():
        df.to_csv(args.salida/f'{name}.csv',index=False)
    reporte['modelo']['origen']='tickets.csv (texto_consulta -> categoria normalizada); no se entrena usando el texto completo del bot anterior'
    (args.salida/'reporte_calidad.json').write_text(json.dumps(reporte,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'filas_limpias':{n:len(d) for n,d in raw.items()},'cierre_invertido':reporte['tratamiento']['tickets_cierre_anterior_apertura'],'integracion':reporte['integracion'],'train':reporte['modelo']['tickets_etiquetados_utilizables']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
