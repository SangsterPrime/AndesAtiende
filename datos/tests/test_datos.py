from pathlib import Path
import pandas as pd
BASE=Path(__file__).resolve().parents[1]/'procesados'

def test_claves_unicas_y_completas():
    for n,key in [('clientes','cliente_id'),('tickets','ticket_id'),('conversaciones','conversacion_id'),('faq','articulo_id')]:
        d=pd.read_csv(BASE/f'{n}.csv')
        assert not d[key].isna().any(),n
        assert not d[key].duplicated().any(),n

def test_modelo_etiquetado():
    d=pd.read_csv(BASE/'tickets.csv')
    assert d.categoria.notna().sum()>20000
    assert d.texto_consulta.notna().all()
