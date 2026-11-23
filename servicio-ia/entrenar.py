"""Modelo supervisado real para clasificar intención de consultas de telecomunicaciones.
Entrenamiento sin fugas: divide por textos únicos antes de ajustar TF-IDF.
"""
from pathlib import Path
import argparse
import json
import os
import sys
import joblib
import pandas as pd
import sklearn
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score, accuracy_score

HERE=Path(__file__).resolve().parent
DATA=HERE.parent/'datos'/'procesados'/'tickets.csv'

def entrenar(min_f1=.60, version_modelo='ep2-1.0.0'):
    # SageMaker monta el canal train y empaqueta el contenido de SM_MODEL_DIR.
    # Sin esas variables se conservan las rutas locales originales de EP2.
    channel=os.environ.get('SM_CHANNEL_TRAIN')
    source=Path(channel)/'tickets.csv' if channel else DATA
    target=Path(os.environ.get('SM_MODEL_DIR') or HERE/'modelo')
    df=pd.read_csv(source).dropna(subset=['categoria','texto_consulta']).copy()
    df=df[df.texto_consulta.str.len()>=3]
    # Validamos antes de deduplicar para no ocultar etiquetas contradictorias.
    if df.groupby('texto_consulta')['categoria'].nunique().gt(1).any():
        raise ValueError('Un mismo texto tiene etiquetas contradictorias')
    # Para el conjunto de evaluación no mezclamos textos idénticos entre train/test.
    u=df[['texto_consulta','categoria']].drop_duplicates(subset='texto_consulta')
    train,test=train_test_split(u,test_size=.25,random_state=42,stratify=u.categoria)
    pipe=Pipeline([
        ('tfidf',TfidfVectorizer(lowercase=True,strip_accents='unicode',ngram_range=(1,2),min_df=2,max_features=12000,sublinear_tf=True)),
        ('classifier',LogisticRegression(max_iter=500,class_weight='balanced',random_state=42))
    ])
    pipe.fit(train.texto_consulta,train.categoria)
    pred=pipe.predict(test.texto_consulta)
    score=float(f1_score(test.categoria,pred,average='macro',zero_division=0))
    acc=float(accuracy_score(test.categoria,pred))
    result={
      'version_modelo':version_modelo, 'framework':'scikit-learn','version_sklearn':sklearn.__version__,
      'algoritmo':'TF-IDF (1,2) + regresión logística', 'macro_f1':score,'accuracy':acc,
      'filas_totales_ticket':int(len(df)), 'textos_unicos':int(len(u)), 'n_train':int(len(train)),
      'n_test':int(len(test)), 'split':'estratificado 75/25 sobre textos únicos, random_state=42',
      'objetivo':'categoria normalizada', 'fuente':'tickets.csv',
      'clases':sorted(map(str,pipe.classes_)), 'umbral_macro_f1':min_f1,
      'detalle':classification_report(test.categoria,pred,output_dict=True,zero_division=0)
    }
    print(json.dumps({k:v for k,v in result.items() if k!='detalle'},ensure_ascii=False,indent=2))
    if score<min_f1:
       print(f'Quality gate: F1 {score:.4f} < {min_f1:.4f}',file=sys.stderr)
       raise SystemExit(1)
    target.mkdir(parents=True,exist_ok=True)
    joblib.dump(pipe,target/'clasificador.joblib',compress=3)
    (target/'metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Quality gate OK: {score:.4f} >= {min_f1:.4f}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--min-f1',type=float,default=.60)
    parser.add_argument('--model-version',default='ep2-1.0.0',help='Versión guardada en metadata.json (por defecto: ep2-1.0.0)')
    args=parser.parse_args();entrenar(args.min_f1,version_modelo=args.model_version)
