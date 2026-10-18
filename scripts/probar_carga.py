"""Carga básica para defender latencia y docker stats (ejecutar con compose levantado)."""
from concurrent.futures import ThreadPoolExecutor
from statistics import mean
from time import perf_counter
from urllib.request import Request,urlopen
import json
import argparse

ap=argparse.ArgumentParser();ap.add_argument('--n',type=int,default=100);a=ap.parse_args()
texts=['No tengo internet en mi casa','No entiendo mi factura','Quiero cancelar mi servicio','Quiero cambiar mi plan']

def send(i):
    req=Request('http://localhost:8080/api/chat',data=json.dumps({'mensaje':texts[i%4]}).encode(),headers={'Content-Type':'application/json'},method='POST')
    st=perf_counter()
    try:
        with urlopen(req,timeout=5) as r:
            return ((perf_counter()-st)*1000,r.status)
    except Exception:
        return ((perf_counter()-st)*1000,0)
with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(send,range(a.n)))
ok=sorted(t for t,status in results if status==200)
print(f'Peticiones {a.n} / exitosas {len(ok)} / errores {a.n-len(ok)}')
if ok:print(f'Promedio {mean(ok):.1f} ms / p95 {ok[min(len(ok)-1,int(len(ok)*.95))]:.1f} ms')
print('Complementar con docker stats. No confundir esta carga sintética con 1000 conversaciones simultaneas.')
