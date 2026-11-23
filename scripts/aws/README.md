# EP3 · Grupo 5 · SageMaker en Learner Lab

**Región única: `us-east-1`. Nada de este flujo se ejecutó en AWS durante su preparación.** Los comandos de las secciones AWS crean recursos facturables; ejecútalos únicamente desde tu sesión de Learner Lab, revisando saldo, permisos y cuotas. No se crean roles IAM ni se cambian políticas del Lab.

## Qué se reutiliza y qué se añade

Antes de esta rama solo existían `scripts/configurar_owner.py`, `scripts/probar_carga.py` y la adaptación local de `servicio-ia/entrenar.py`; no había scripts AWS. Se conserva **sin cambios** el entrenamiento y sus pruebas de EP2/PR #3: TF-IDF + regresión logística, split estratificado por textos únicos, control de etiquetas contradictorias y quality gate.

| Archivo | Responsabilidad |
|---|---|
| `scripts/aws/publicar_imagen.py` | Build `linux/amd64`, publicación ECR y devolución de URI por digest |
| `scripts/aws/ep3.py upload` | Validar y cargar el `tickets.csv` tratado a S3 |
| `scripts/aws/ep3.py train` | Training Job CPU, canal `train`, rol existente `LabRole` |
| `scripts/aws/ep3.py deploy` | Verificar artefacto y crear modelo/config/endpoint serverless |
| `scripts/aws/ep3.py invoke` | Invocación IAM con JSON y verificación de probabilidad/versión |
| `scripts/aws/ep3.py cleanup` | Borrar solo endpoint/config/model del `run-id` confirmado |
| `servicio-ia/Dockerfile.sagemaker` | **Una misma imagen inmutable** para entrenamiento e inferencia |
| `servicio-ia/sm_entrypoint.py` | Contrato SageMaker `train` / `serve` con propagación de señales |
| `servicio-ia/sm_serving.py` | Puerto 8080, `/ping` y `/invocations`, un worker |

Se usa Boto3, no el SDK de alto nivel de SageMaker. Estos scripts entrenan y despliegan el endpoint de forma independiente. La integración del chatbot mediante `IA_BACKEND=sagemaker` y el overlay `compose.ep3.yaml` se explica en el [README principal](../../README.md#chat-y-predicción-con-sagemaker-ep3); conserva el contrato `/api/chat` y añade `/api/predict` a través del dominio. No necesita NVIDIA; los scripts AWS no leen `.env`.

## Dependencias y contrato del artefacto

La imagen propia usa Python 3.12, `scikit-learn==1.8.0`, `joblib==1.5.3`, `pandas==2.2.3`, `numpy==2.2.6` y las dependencias FastAPI fijadas en `servicio-ia/requirements.txt`. No se usa un contenedor preconstruido de scikit-learn de otra versión ni se instalan paquetes al arrancar. La publicación devuelve `...@sha256:...`: el Training Job usa ese digest y el despliegue recupera **el mismo digest de `DescribeTrainingJob`**, no un tag mutable.

1. `upload` escribe `s3://BUCKET/andesatiende/ep3/RUN/train/tickets.csv`, con SSE-S3 y hash SHA-256. `IfNoneMatch=*` impide sobrescribir una carga previa; para otra ejecución usa otro `run-id`.
2. El canal se llama `train`, modo `File`, `FullyReplicated`. SageMaker monta el archivo en `/opt/ml/input/data/train/tickets.csv`. El entry point BYOC establece `SM_CHANNEL_TRAIN=/opt/ml/input/data/train` y `SM_MODEL_DIR=/opt/ml/model`: no depende de que el Training Toolkit genere esas variables.
3. Se leen `min-f1` y `model-version` de `/opt/ml/input/config/hyperparameters.json` y se invoca el **script existente**. Solo se guardan `clasificador.joblib` y `metadata.json` después de superar el gate.
4. SageMaker empaqueta `/opt/ml/model` en `model.tar.gz`. Se toma su ubicación real desde `ModelArtifacts.S3ModelArtifacts`, sin adivinar la ruta.
5. `deploy` requiere estado `Completed` y revisa el tar **sin extraerlo ni ejecutar pickle localmente**: ambos archivos en raíz, sin enlaces/rutas arbitrarias, versión esperada, scikit-learn 1.8.0 y macro-F1 suficiente. El contenedor comprueba versiones antes de `joblib.load`, verifica clases y hace una predicción de salud. **Solo se deben usar artefactos propios/de confianza**: pickle/joblib puede ejecutar código.
6. SageMaker expande el artefacto en `/opt/ml/model` de solo lectura. La imagen sirve `GET /ping` (200 solo con modelo cargado) y `POST /invocations`. Un fallo produce error/503, nunca una predicción inventada.

Solicitud: `{"mensaje":"No tengo internet"}`. Respuesta: objeto con `intencion`, `probabilidad` (probabilidad real de la clase elegida, entre 0 y 1) y `version_modelo`. No se inventan valores ni se presentan probabilidades como certeza comercial.

La imagen solo copia cinco archivos de código/requirements; su contexto Docker excluye datos, artefactos EP2, `.env` y credenciales. Se desactivan provenance/SBOM en el build para evitar un índice multi-manifest por attestations; se necesita Docker Desktop/BuildKit reciente. Entrenamiento con una instancia, volumen de 10 GB y límite de 600 segundos. Serverless con **2048 MB**, concurrencia máxima **1**, sin capacidad provisionada, GPU, VPC ni aislamiento de red en inferencia (serverless no lo soporta). El aislamiento de red sí se activa para entrenamiento. Estos límites son un punto inicial, no mediciones de rendimiento.

## 1. Preparar y probar localmente (PowerShell, sin AWS)

Desde la raíz del repositorio; se recomienda Python 3.12:

```powershell
python --version
python -m venv .venv
$Python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-train.txt -r servicio-ia/requirements-sagemaker.txt -r scripts/aws/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación' }

# El PYTHONPATH solo se cambia durante estas pruebas.
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$(Join-Path (Get-Location) 'servicio-ia');$(Get-Location)"
    & $Python -m pytest -q scripts/aws/tests servicio-ia/tests datos/tests
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas locales' }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

& $Python -m scripts.aws.ep3 upload --bucket bucket-local-prueba-g5 --run-id ep3-dry-run --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Falló la validación del CSV tratado' }

# ARN/digest ficticios: solo se construye la solicitud, sin resolver credenciales.
$DummyImage = '123456789012.dkr.ecr.us-east-1.amazonaws.com/andesatiende-ep3-g5@sha256:' + ('a' * 64)
& $Python -m scripts.aws.ep3 train --bucket bucket-local-prueba-g5 --run-id ep3-dry-run --image-uri $DummyImage --role-arn arn:aws:iam::123456789012:role/LabRole --model-version ep3-1.0.0 --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Falló la construcción del Training Job' }
```

Los tickets tratados **deben existir** en `datos/procesados/tickets.csv`. Las pruebas no ejecutan ETL/entrenamiento sobre `servicio-ia/modelo/`. Si falta el CSV, las pruebas de integración se omiten: `SKIPPED` no demuestra un flujo válido. La comprobación usa exclusivamente tickets; **integrar conversaciones sigue pendiente hasta recuperar sus transcripciones**. No se generan transcripciones ficticias ni se suben fuentes originales.

### Comprobación Docker opcional, aún sin AWS

Con Docker Desktop en modo Linux y desde raíz:

```powershell
docker build --platform linux/amd64 --provenance=false --sbom=false -f servicio-ia/Dockerfile.sagemaker -t andesatiende-sm:local .
if ($LASTEXITCODE -ne 0) { throw 'Falló el build Docker' }
$Smoke = Join-Path $env:TEMP ('andes-sm-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path "$Smoke\train", "$Smoke\config", "$Smoke\model" | Out-Null
Copy-Item datos/procesados/tickets.csv "$Smoke\train\tickets.csv"
[IO.File]::WriteAllText("$Smoke\config\hyperparameters.json", '{"min-f1":"0.85","model-version":"ep3-docker-local"}', [Text.UTF8Encoding]::new($false))
docker run --rm --platform linux/amd64 --mount "type=bind,source=$Smoke\train,target=/opt/ml/input/data/train,readonly" --mount "type=bind,source=$Smoke\config,target=/opt/ml/input/config,readonly" --mount "type=bind,source=$Smoke\model,target=/opt/ml/model" andesatiende-sm:local train
if ($LASTEXITCODE -ne 0) { throw 'Falló el entrenamiento dentro de Docker' }
docker run -d --name andesatiende-ep3-smoke --platform linux/amd64 -p 127.0.0.1:8091:8080 --mount "type=bind,source=$Smoke\model,target=/opt/ml/model,readonly" andesatiende-sm:local serve
if ($LASTEXITCODE -ne 0) { throw 'Falló el arranque de inferencia' }
# Esperar unos segundos al arranque; si aún no está listo, repetir /ping.
Invoke-WebRequest -Uri http://127.0.0.1:8091/ping -UseBasicParsing
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8091/invocations -ContentType application/json -Body '{"mensaje":"No tengo internet"}'
docker rm -f andesatiende-ep3-smoke
```

El puerto de prueba está limitado a localhost y no cambia el compose ni el puerto 8080 del gateway. Los temporales se conservan para inspección; no borres directorios ajenos a esta prueba.

## 2. Preparar la sesión del Learner Lab (a partir de aquí SÍ hay AWS)

Requisitos: Lab iniciado y con saldo; Docker Desktop Linux; conexión a ECR/S3/SageMaker; bucket general-purpose **ya existente y privado en `us-east-1`**, y rol **LabRole existente**. No se provisionan buckets, roles ni claves. Antes de continuar verifica en el Lab:

- Acceso S3: `GetBucketLocation`, `PutObject`, `GetObject`/`HeadObject` y lectura/escritura de SageMaker en los prefijos elegidos.
- Acceso ECR: autenticación, descripción, push/pull; `CreateRepository` solo si se usa la opción explícita. `LabRole` debe poder extraer la imagen.
- Acceso SageMaker: crear/describir training, modelos, configs, endpoints; invocar y eliminar los recursos de esta ejecución; `iam:PassRole` de LabRole.
- Cuota de entrenamiento para `ml.m5.large` (o una de las alternativas CPU del CLI) y disponibilidad/cuota de **Serverless Inference**. Learner Lab puede bloquearlo por políticas: no se garantiza que esté habilitado. No hay fallback automático a un endpoint provisionado que genere otro coste.

Obtén las credenciales temporales desde **AWS Details → AWS CLI** del Lab y configúralas localmente mediante el mecanismo estándar AWS, **incluido `aws_session_token`**. Guarda los perfiles en `%USERPROFILE%\.aws\credentials`, fuera del repositorio, o usa variables de entorno temporales. No pegues claves en código, `.env`, scripts, capturas ni chat. Si usas un perfil, selecciona `$env:AWS_PROFILE = 'nombre-del-perfil'`; no combines perfiles con credenciales de entorno de otra sesión. Renueva las credenciales cuando expire el Lab.

En una consola PowerShell situada en la raíz y con `$Python` del paso 1:

```powershell
$env:AWS_DEFAULT_REGION = 'us-east-1'
$AccountId = & $Python -c "import boto3; print(boto3.client('sts', region_name='us-east-1').get_caller_identity()['Account'])"
if ($LASTEXITCODE -ne 0) { throw 'Verifica las credenciales temporales y el token de sesión del Lab' }
$AccountId = $AccountId.Trim()
$RoleArn = "arn:aws:iam::${AccountId}:role/LabRole"
# Si AWS Details muestra un path para LabRole, usa su ARN exacto en vez del anterior.
$Bucket = 'REEMPLAZAR_POR_BUCKET_PRIVADO_US_EAST_1'
$RunId = 'ep3-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$Version = 'ep3-1.0.0'
```

Guarda `$RunId`, `$Bucket`, `$Version` y la URI de imagen (no son credenciales) para volver a describir o limpiar la ejecución. Los scripts no actualizan ni sobrescriben recursos con el mismo nombre; usa un `run-id` nuevo en cada entrenamiento.

## 3. Publicar imagen, cargar S3 y entrenar

```powershell
# Hace build y push. Omitir --create-repository si ya existe o no puedes crearlo.
# La salida stdout es SOLO JSON; los logs Docker van a stderr.
$PublishedJson = & $Python -m scripts.aws.publicar_imagen --tag $RunId --create-repository
if ($LASTEXITCODE -ne 0) { throw 'Falló la publicación ECR; no continúes' }
$ImageUri = ($PublishedJson | ConvertFrom-Json).image_uri

& $Python -m scripts.aws.ep3 upload --bucket $Bucket --run-id $RunId
if ($LASTEXITCODE -ne 0) { throw 'Falló la carga de tickets; no continúes' }

& $Python -m scripts.aws.ep3 train --bucket $Bucket --run-id $RunId --image-uri $ImageUri --role-arn $RoleArn --model-version $Version --min-f1 0.85 --instance-type ml.m5.large --wait
if ($LASTEXITCODE -ne 0) { throw 'Entrenamiento no completado; revisa SageMaker y CloudWatch' }
```

El script devuelve el nombre del Training Job y, con `--wait`, la URI real del artefacto. El gate falla con código distinto de cero si macro-F1 no alcanza 0.85. `--wait` puede durar varios minutos: provisioning no es tiempo de entrenamiento. Un timeout de espera local no cancela automáticamente el job: comprueba su estado antes de repetir. Revisa errores/logs en SageMaker y `/aws/sagemaker/TrainingJobs` de CloudWatch. No reconstruyas la imagen entre entrenamiento y despliegue; se reutiliza el digest.

## 4. Desplegar serverless e invocar

```powershell
& $Python -m scripts.aws.ep3 deploy --run-id $RunId --memory 2048 --concurrency 1 --wait
if ($LASTEXITCODE -ne 0) { throw 'Endpoint no listo; revisa permisos, cuota y logs de hosting' }

& $Python -m scripts.aws.ep3 invoke --run-id $RunId --mensaje 'No tengo internet' --model-version $Version
if ($LASTEXITCODE -ne 0) { throw 'Falló la prueba de inferencia o su versión no coincide' }
```

La salida solo muestra la intención, probabilidad y versión **recibidas del endpoint**. Para esta prueba usa mensajes sintéticos, sin PII. Serverless puede tener arranque en frío; ante `ModelNotReadyException`, throttling o timeout, revisa que esté `InService`, espera y vuelve a invocar manualmente. Nunca se imprime una respuesta simulada. El endpoint está autenticado por IAM/SigV4, no es una URL de chat pública.

Si el despliegue falla después de crear modelo/config, esos recursos pueden quedar presentes: el script no borra ni reemplaza recursos automáticamente. Revisa `/aws/sagemaker/Endpoints/andes-g5-RUN-endpoint` y limpia con el mismo `$RunId` antes de volver a desplegar.

## 5. Limpiar lo desplegado por esta ejecución

```powershell
& $Python -m scripts.aws.ep3 cleanup --run-id $RunId --confirm
if ($LASTEXITCODE -ne 0) { throw 'La limpieza quedó incompleta; revisar recursos en SageMaker' }
```

Elimina el endpoint, espera su borrado, luego elimina su configuración y modelo. **No borra** datos/artefactos S3, imágenes ECR, logs, roles ni el historial de Training Jobs; revisa manualmente su retención y coste cuando ya no se necesiten. Un Training Job todavía activo debe detenerse desde SageMaker si no lo necesitas. No se ejecuta limpieza al importar módulos ni al terminar una prueba local.

## Verificación realizada y límites

**69 pruebas aprobadas, sin omisiones** (67 de herramientas AWS, entrenamiento, inferencia y datos; 2 de dominio). Verificado localmente con Python 3.11.9, scikit-learn 1.8.0 y dependencias fijadas, en entorno virtual temporal externo al repositorio. Las pruebas de la API EP2 emiten 3 avisos de deprecación ya existentes (`on_event` y alias de AnyIO), sin fallos:

- Regresiones de entrenamiento y calidad de tickets; simulación de `SM_*` sin modificar EP2.
- Entry point real `train` como subproceso, usando tickets tratados y config temporal; empaquetado `model.tar.gz`, expansión y carga en la aplicación de inferencia.
- `/ping`, `/invocations`, igualdad de intención/probabilidad con `predict_proba` del artefacto recargado, validación de payload y fallo controlado ante modelo ausente/incompatible.
- Solicitudes Boto3 contra **Stubber**, no AWS: carga S3, canal File, LabRole, quality gate, digest compartido y configuración exclusivamente serverless, invocación y rechazo de respuestas inválidas. `--dry-run` no crea sesiones AWS.
- Preservación de los hashes SHA-256 de los artefactos locales EP2. No se muestran ni se empaquetan secretos locales.

**Pendiente de verificar en tu entorno:** build/arranque del contenedor Python 3.12 (Docker no está instalado aquí), autenticación y permisos de Learner Lab, subida S3/ECR, ejecución real del job, descarga/carga del artefacto dentro de SageMaker, cuota y creación serverless, arranque en frío, inferencia remota, tamaño de imagen, consumo, costes y limpieza real. Ninguna prueba simulada confirma permisos, disponibilidad o latencias de AWS.

La prueba de tickets anteriores obtuvo macro-F1 1,0000 sobre 303 textos; la fuente es de laboratorio con textos sintéticos repetitivos, **no validación con usuarios reales**. Las conversaciones no se incorporan hasta recuperar transcripciones. No se realizaron commit, push ni acciones AWS durante la preparación.

Referencias del contrato consultado:
- https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-training-algo-dockerfile.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-inference-code.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/serverless-endpoints.html
