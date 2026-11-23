# AndesAtiende · EP2 · Equipo 05

Caso 2: Chatbot para Andesnet Telecomunicaciones S.A. · Ingeniería de Arquitectura IA (ITY1102).

**Estado: proyecto generado y pruebas Python verificables; falta publicar GHCR, medir Docker y validar en Windows.**

## Para qué sirve

La demo clasifica intenciones reales con TF-IDF + regresión logística (scikit-learn):
`frontend -> gateway:8080 -> dominio -> gateway /api/ia/predict -> réplica IA -> dominio -> PostgreSQL`.
Se registran entrada minimizada, intención, versión, confianza, fecha y derivación. El servicio de IA NO consulta la BD.

## Servicios del compose

| Servicio | Imagen propia | Puerto público |
|---|---|---|
| front | `andesatiende-front` | no |
| gateway | `andesatiende-gateway` | **8080** |
| dominio | `andesatiende-dominio` | no |
| ia-1 e ia-2 | una imagen `andesatiende-ia` | no |
| db | `postgres:16-alpine` | no |
| carga | `andesatiende-carga` (job único) | no |

## No subir el ZIP crudo a un repositorio público

Los CSV originales contienen RUT, correos, teléfonos y datos de tarjetas simulados en texto. La carpeta `datos/entrada` es una **muestra seudonimizada y minimizada para laboratorio**, creada mediante `datos/sanitizar_fuente.py`; no se garantiza que este proceso sea suficiente para datos reales. `conversaciones.csv` omite transcripciones de la fuente deliberadamente. No subir directorios `caso/` ni `datos/originales/`.

## Reproducir el entrenamiento

Con Python 3.12:

```bash
python -m pip install -r requirements-train.txt
python datos/preparar.py
python -m pytest -q datos/tests
python servicio-ia/entrenar.py --min-f1 0.85
PYTHONPATH=servicio-ia python -m pytest -q servicio-ia/tests
```

Los artefactos del entrenamiento y datos preparados están en `.gitignore`, porque **el pipeline** los genera antes del build. Si el profesor pide un script, están `datos/preparar.py` y `servicio-ia/entrenar.py`.

La evaluación actual obtiene macro-F1 **1.0000** sobre 303 textos de prueba distintos (de 1211 textos únicos), debido a textos de laboratorio sintéticos altamente repetitivos. No debe interpretarse como calidad validada en usuarios reales.

### Entrenamiento compatible con SageMaker (EP3)

Se reutiliza el mismo pipeline TF-IDF + regresión logística, el split por textos únicos y el quality gate. El comando local `python servicio-ia/entrenar.py --min-f1 0.85` no cambia: sin variables de SageMaker lee `datos/procesados/tickets.csv`, escribe en `servicio-ia/modelo/` y mantiene `ep2-1.0.0` como versión predeterminada. **Ese comando local sí reemplaza los artefactos en su salida habitual**, como antes.

Opciones para un Training Job o su simulación local:

- `SM_CHANNEL_TRAIN`: directorio que contiene el CSV **ya tratado**, con nombre `tickets.csv` y columnas `texto_consulta` y `categoria`. Si se define, no se recurre a los datos locales cuando falta el archivo.
- `SM_MODEL_DIR`: directorio de salida para `clasificador.joblib` y `metadata.json`, escritos solo al superar el quality gate. Las dos variables son independientes.
- `--model-version ep3-1.0.0`: versión que se registra en metadata. En SageMaker, pasar `model-version` como hiperparámetro al entry point `entrenar.py`.

La adaptación cubre el **entry point de entrenamiento**, no crea recursos, contenedores, roles ni jobs en AWS. El entorno del Training Job debe proporcionar las dependencias de `requirements-train.txt` y las variables/rutas indicadas. No cambia la API de inferencia.

Para repetir la comprobación segura en PowerShell desde la raíz, con las dependencias de entrenamiento instaladas:

```powershell
# Copia los tickets tratados a un canal temporal, simula ambas variables,
# ejecuta el CLI, recarga el modelo, predice y comprueba los hashes de EP2.
python -m pytest -q -s servicio-ia/tests/test_entrenar_sagemaker.py

# Regresiones del entrenamiento y calidad de los datos ya tratados.
python -m pytest -q servicio-ia/tests/test_entrenar.py servicio-ia/tests/test_entrenar_sagemaker.py datos/tests
```

La prueba usa `tmp_path` de pytest tanto para entrada como para salida, sin modificar variables del shell ni regenerar datos o artefactos EP2. Si falta `datos/procesados/tickets.csv`, la integración informa `SKIPPED`; no equivale a una validación exitosa. Las predicciones y métricas impresas provienen de la ejecución, no de fixtures inventados.

**Alcance de datos EP3:** se entrena únicamente con los tickets tratados disponibles. Integrar conversaciones sigue pendiente hasta recuperar sus transcripciones; sus metadatos no sustituyen el texto ausente y no se generan transcripciones sintéticas para este recorrido.

Comprobación local realizada en Windows con Python 3.11.9 y un entorno virtual temporal fuera del repositorio, usando las versiones fijadas de `requirements-train.txt` y los requirements de IA/dominio: **12 pruebas de entrenamiento/datos, 2 de API IA y 2 de dominio correctas**, sin omisiones. La simulación obtuvo 23.803 filas válidas, 1.211 textos únicos, 908 para entrenamiento y 303 para evaluación, macro-F1 1,0000; se recargó el clasificador y se comprobaron predicciones y probabilidades válidas. Los hashes SHA-256 de los artefactos locales EP2 quedaron intactos. Estas métricas siguen sujetas a la limitación de datos sintéticos de laboratorio indicada arriba. Las pruebas API emiten avisos de deprecación de `on_event` y de un alias de AnyIO, sin fallos. **Pendiente validar Python 3.12 y el entorno real de SageMaker**; no se realizaron operaciones AWS ni cambios en dependencias, datos o API.

## Publicar desde GitHub (ANTES de la entrega)

1. Crear repositorio personal/público y subir este código a ramas `dev` y `feat/`, siguiendo los PR exigidos. Evitar pushes directos a `main`.
2. Ejecutar una sola vez `python scripts/configurar_owner.py TU_USUARIO_GITHUB` para fijar owner real en `compose.yaml`, antes del merge a `main`.
3. Crear al menos **dos pull requests por cada integrante** desde `feat/` hacia `dev`. Integrar `dev` hacia `main` mediante PR. Habilitar packages con visibilidad **Public** en GitHub Packages.
4. GitHub Actions hace tratamiento -> pruebas -> entrenamiento -> quality gate -> 5 docker builds. El push a main publica `latest` y `sha-XXXXXXX`.
5. Después del último merge correcto a `main`, poner tag **ep2** sobre ese commit y hacer push del tag: `git tag ep2 && git push origin ep2`. Esperar a que todas las imágenes **:ep2** estén publicadas y públicas. **No mover el tag** después del cierre.
6. En un Windows limpio con Docker Desktop, ejecutar solo:

```powershell
docker compose -p equipo05 pull
docker compose -p equipo05 up -d
```

Visitar `http://localhost:8080` y escribir «No tengo internet». `docker compose -p equipo05 ps` debe mostrar servicios healthy y `carga` exited (0).

## Frontend React

`front/` usa React 19, TypeScript, Vite, Tailwind CSS y una esfera Three.js opcional. Desarrollo y pruebas con **pnpm**; ver [front/README.md](front/README.md) para instalación, proxy al gateway, accesibilidad, validación y Docker multi-stage. La entrega mantiene el único puerto público `8080` y las imágenes GHCR del compose. El frontend solo presenta resultados recibidos de `/api/chat`, sin autenticación ni integración real con Genesys.

**Importante:** no intentar esos dos comandos hasta publicar las cinco imágenes y sustituir `REEMPLAZAR_USUARIO`. No se hicieron publicaciones desde ChatGPT.

## Demostraciones de defensa

```powershell
# Estado
 docker compose -p equipo05 ps
# Ver consumo real y justificar los limites provisionales
 docker stats
# Prueba de 100 peticiones mientras observas docker stats
 python scripts/probar_carga.py --n 100
# Detener una replica IA y comprobar continuidad del servicio
 docker stop equipo05-ia-1-1
# Consultar predicciones persistidas en la BD
 docker compose -p equipo05 exec db psql -U andes -d andesdb -c 'SELECT fecha,resultado,confianza,version_modelo FROM predicciones ORDER BY fecha DESC LIMIT 5;'
# Ver revision OCI (reemplazar con imagen descargada)
 docker image inspect ghcr.io/TU_USUARIO/andesatiende-ia:ep2 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

Los comandos de inspección requieren ajustar el nombre de contenedor obtenido en `docker ps`. Después de detener una réplica, Nginx puede devolver un fallo en una petición en tránsito; comprueben nuevas peticiones. Una réplica de cada servicio no representa HA completa del stack ni Multi-AZ.

## Qué falta para calificar EP2

- Publicar GHCR desde GitHub Actions y confirmar pruebas verdes; habilitar las cinco imágenes públicas.
- Ejecutar los dos comandos en Docker Desktop/Windows, comprobar `healthcheck`, replicación y failover.
- Medir `docker stats`, latencia p95 y tamaños `docker images`: los valores `cpus` y `mem_limit` actuales son **hipótesis iniciales**, no mediciones.
- Revisar con el docente qué se entiende por disponibilidad de servicio en caída de réplica y qué debe quedar para AWS Multi-AZ.
- Completar el arc42 corregido EP1 (8 figuras, 7.2/7.3, ADR, seguridad, riesgos, anexos A/B/C) con cifras medidas y links reales.
- Cumplimiento GDPR, autenticación OIDC, integración SOAP Siebel, Oracle Amdocs, Infobip, Genesys, RAG y AWS quedan explícitamente **fuera del MVP EP2**.

## Nota sobre arquitectura

La red Docker no está cifrada con mTLS: es una excepción de la demo local, **no** cumplimiento de RT8. Las credenciales PostgreSQL del compose son exclusivamente ejemplos públicos de laboratorio; no sirven para producción. El clasificador nunca debe responder saldos reales ni anular contratos.
