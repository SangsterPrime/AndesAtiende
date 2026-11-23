# AndesAtiende · EP2 · Equipo 05

Caso 2: Chatbot para Andesnet Telecomunicaciones S.A. · Ingeniería de Arquitectura IA (ITY1102).

**Estado: proyecto generado y pruebas Python verificables; falta publicar GHCR, medir Docker y validar en Windows.**

## Para qué sirve

La demo clasifica intenciones reales con TF-IDF + regresión logística (scikit-learn):
`frontend -> gateway:8080 -> dominio -> gateway:8081 /predict (interno) -> réplica IA -> dominio -> PostgreSQL`.
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

### Endpoint SageMaker serverless (EP3)

El flujo reproducible para Learner Lab en **us-east-1** está en [scripts/aws/README.md](scripts/aws/README.md): pruebas locales, imagen compartida de entrenamiento/inferencia, carga de tickets tratados a S3, Training Job con **LabRole**, despliegue serverless, invocación y limpieza. Incluye los comandos exactos de PowerShell y separa lo verificado localmente de lo pendiente en AWS. Los scripts solo crean recursos cuando se ejecutan explícitamente; no se ejecutaron acciones AWS al prepararlos.

### Chat y predicción con SageMaker (EP3)

El backend de `servicio-ia` se selecciona mediante `IA_BACKEND=local|sagemaker` (predeterminado: `local`, compatible con EP2). Con `sagemaker` se exige `SAGEMAKER_ENDPOINT_NAME`, se usa boto3 en **us-east-1** y **no se leen archivos `.joblib` ni se recurre a EP2 ante fallos**. No necesita NVIDIA. La región es explícita y el cliente no recibe claves: en EC2 usa el rol del instance profile y la cadena de credenciales AWS; no agregues claves al compose o al repositorio.

Recorrido: `POST /api/chat` o `POST /api/predict` → dominio (autentica/valida/minimiza datos) → gateway **interno** `:8081/predict` → servicio-ia → SageMaker `/invocations` → dominio → PostgreSQL. Ambas rutas aceptan `{"mensaje":"No tengo internet"}` y devuelven el mismo contrato del chat: `prediccion_id`, `intencion`, `confianza`, `version_modelo`, `respuesta`, `derivar_humano`, `replica_ia` y `latencia_total_ms`. IA convierte `probabilidad` en `confianza` sin inventar ni sustituir la versión: **la versión recibida del endpoint se devuelve al cliente y se inserta en `predicciones.version_modelo`**.

#### Clave de API EP3 y rutas públicas

Configura **`EP3_API_KEY` únicamente en el entorno del servidor**, compartida entre dominio y gateway. Debe ser aleatoria, de 32 a 128 caracteres `A-Z`, `a-z`, `0-9`, `_` o `-`; no hay clave predeterminada. `.env.example` solo documenta el nombre, no contiene un secreto. No usar variables `VITE_*`, archivos del frontend, parámetros de URL ni cabeceras en logs. Guarda la clave real fuera del repositorio con acceso restringido; al rotarla, recrea dominio y gateway juntos. Los builds actuales requieren configuración; las imágenes antiguas `:ep2` **no implementan estos controles**, usa el overlay EP3.

| Ruta externa | Acceso |
|---|---|
| `POST /api/predict` | Cabecera `X-API-Key` válida; valida y persiste |
| `GET /api/predicciones/{id}` | Misma cabecera; SELECT parametrizado por UUID |
| `POST /api/chat` | Chat público mediante BFF: Nginx añade la clave solo en el servidor |
| `GET /api/health` | Público; 200 si PostgreSQL está disponible, 503 en caso contrario |
| `GET /docs`, `GET /api/openapi.json` | Públicos; esquema APIKey en Swagger, sin clave precargada |

Clave ausente/incorrecta o servidor sin clave válida: **401 antes de parsear JSON/UUID, llamar IA o abrir PostgreSQL**, incluso con JSON roto. Clave válida y entrada inválida: **422**. La consulta devuelve únicamente ID, intención, confianza, versión, fecha y derivación guardadas; no expone el mensaje del usuario ni hace una nueva inferencia. ID válido inexistente: **404**; fallo de BD: **503**. La clave es compartida a nivel de aplicación: no identifica usuarios ni implementa autorización por propietario de cada registro.

El dominio exige clave también para `/chat`; el navegador sigue enviando solo su mensaje a `/api/chat`. Nginx sobrescribe la cabecera **exclusivamente en esa ruta exacta**, nunca en `/api/predict` o en la consulta. Se elimina el proxy público genérico: `/api/ia/*`, `/api/estadisticas`, alias con barra final y demás rutas no declaradas devuelven 404. La comunicación con IA usa un segundo listener en 8081, **no publicado en el host**; dominio/IA/BD no deben publicar puertos. Las redes internas siguen siendo un límite de confianza, no mTLS.

El chat anónimo es una excepción pública deliberada para conservar la interfaz; **no se afirma que la clave impida todas las inferencias anónimas**, ni que autentique al usuario del chat. Si se requiere eso, también hay que autenticar al usuario y limitar el chat; no se debe resolver entregando la clave compartida al JavaScript.

Timeout, error AWS o respuesta inválida producen HTTP 503, sin INSERT ni confirmación de predicción exitosa. Si falla PostgreSQL tampoco se confirma éxito. Se usan timeouts acotados: conexión AWS 1 s/lectura 5 s/sin reintentos SDK, dominio 8 s, gateway 10 s y cliente web 12 s. Un cold start serverless puede excederlos; espera/reintenta manualmente tras revisar el endpoint. `/health` en modo SageMaker valida configuración local del adaptador, **no** hace invocaciones de pago ni garantiza salud remota; no fabrica una versión del modelo. `/modelo` informa backend/endpoint, no métricas locales.

En la EC2 del Lab, con endpoint `InService` e instance profile que permita `sagemaker:InvokeEndpoint` sobre su ARN, configura `SAGEMAKER_ENDPOINT_NAME`. Si usas IMDSv2 desde contenedores, revisa conectividad a IMDS y el hop limit del instance profile (habitualmente 2 para la red bridge); no desactives IMDSv2 ni montes credenciales. Revisa también las imágenes EP2 de `front`/`carga` y el owner GHCR de `compose.yaml`.

```powershell
# En un host con Docker y acceso mediante rol EC2. No ejecutado en esta revisión.
$env:SAGEMAKER_ENDPOINT_NAME = 'REEMPLAZAR_POR_ENDPOINT_REAL'
# Solo la primera vez: generar SIN imprimir. Conservarla fuera del repositorio.
# Si ya existe una clave configurada, usarla en lugar de generar otra.
$env:EP3_API_KEY = (python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
docker compose -f compose.yaml -f compose.ep3.yaml up -d --build
Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/chat -ContentType application/json -Body '{"mensaje":"No tengo internet"}'
$Headers = @{ 'X-API-Key' = $env:EP3_API_KEY }
$Prediction = Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/predict -Headers $Headers -ContentType application/json -Body '{"mensaje":"No tengo internet"}'
Invoke-RestMethod -Uri "http://localhost:8080/api/predicciones/$($Prediction.prediccion_id)" -Headers $Headers
```

`compose.ep3.yaml` construye versiones locales de IA/dominio/gateway, en lugar de ejecutar accidentalmente sus imágenes `:ep2` sin esta integración. IA usa el target `runtime` sin copiar modelos; el Dockerfile predeterminado conserva el target local con artefactos EP2. Los tags remotos y el tag Git `ep2` no se modifican. No ejecutar el overlay en el PC del profesor para la entrega EP2.

**Seguridad:** hay autenticación por clave de aplicación, pero aún no hay identidad/autorización de usuarios ni TLS. La autenticación IAM/SigV4 corresponde únicamente al tramo hacia SageMaker. No exponer el puerto público en Internet sin HTTPS y límites de abuso del chat. Nginx renderiza la clave en su configuración **interna** al arrancar, tras validar el formato; no registrar cabeceras, activar logs debug ni publicar volcados de `nginx -T`, del entorno o de `docker compose config` (pueden contener secretos). El rol IAM y sus permisos se verifican en el Lab, no se crean desde la aplicación.

Pruebas sin Docker/AWS (con dependencias del workflow y artefactos EP2 existentes, que no se regeneran):

```powershell
$env:PYTHONPATH = "$(Join-Path (Get-Location) 'servicio-ia');$(Get-Location)"
python -m pytest -q servicio-ia/tests datos/tests scripts/aws/tests
$env:PYTHONPATH = "$(Join-Path (Get-Location) 'servicio-dominio');$(Get-Location)"
python -m pytest -q servicio-dominio/tests
```

Las pruebas cruzan dominio e IA por ASGI, con SageMaker/SQL simulados. Verifican éxito, timeout/respuesta inválida, versión y parámetros del INSERT/SELECT, orden 401/422 y BFF del chat sin secreto en el navegador; **no prueban Nginx ejecutándose ni una transacción real PostgreSQL**. Pendiente en Lab: build Python 3.12, renderizado del template/`nginx -t`, HTTPS, cabeceras y rechazo de rutas/puertos internos a través del Nginx desplegado; red/rol IMDS, permisos/cold start y verificación SQL real de la versión persistida.

Verificación local de esta integración y su autenticación en Windows/Python 3.11.9: **91 pruebas de IA/datos/herramientas AWS, 65 de dominio/autenticación/configuración, 28 unitarias de frontend y 7 Playwright aprobadas**, sin omisiones. Incluye 401 antes de IA/BD, 422 con clave válida, INSERT/SELECT por ID, BFF del chat y guard del template. Las pruebas de navegador usan respuestas interceptadas, no el endpoint real. Los datos procesados y el modelo EP2 conservaron sus hashes SHA-256; no se ejecutaron Docker ni operaciones AWS.

### Entrenamiento compatible con SageMaker (EP3)

Se reutiliza el mismo pipeline TF-IDF + regresión logística, el split por textos únicos y el quality gate. El comando local `python servicio-ia/entrenar.py --min-f1 0.85` no cambia: sin variables de SageMaker lee `datos/procesados/tickets.csv`, escribe en `servicio-ia/modelo/` y mantiene `ep2-1.0.0` como versión predeterminada. **Ese comando local sí reemplaza los artefactos en su salida habitual**, como antes.

Opciones para un Training Job o su simulación local:

- `SM_CHANNEL_TRAIN`: directorio que contiene el CSV **ya tratado**, con nombre `tickets.csv` y columnas `texto_consulta` y `categoria`. Si se define, no se recurre a los datos locales cuando falta el archivo.
- `SM_MODEL_DIR`: directorio de salida para `clasificador.joblib` y `metadata.json`, escritos solo al superar el quality gate. Las dos variables son independientes.
- `--model-version ep3-1.0.0`: versión que se registra en metadata. En SageMaker, pasar `model-version` como hiperparámetro al entry point `entrenar.py`.

El entry point por sí solo no crea recursos AWS. El flujo de [scripts/aws/README.md](scripts/aws/README.md) prepara su imagen, variables y dependencias compatibles para entrenamiento e inferencia; no crea roles IAM. El comando local y la API de inferencia EP2 no cambian.

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
