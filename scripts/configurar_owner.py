"""Usar UNA VEZ antes del commit de main; no es paso de la defensa."""
from pathlib import Path
import argparse
import re
p=argparse.ArgumentParser();p.add_argument('usuario',help='Cuenta de GitHub que publica los packages')
a=p.parse_args();owner=a.usuario.strip().lower()
if not re.fullmatch(r'[a-z0-9-]+',owner):p.error('Owner no válido')
compose=Path(__file__).resolve().parents[1]/'compose.yaml'
s=compose.read_text(encoding='utf-8').replace('REEMPLAZAR_USUARIO',owner)
compose.write_text(s,encoding='utf-8')
print('compose actualizado para GHCR owner:',owner)
