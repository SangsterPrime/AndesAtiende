# Frontend AndesAtiende

React 19 + TypeScript + Vite + Tailwind CSS, con una escena decorativa de Three.js mediante React Three Fiber y Drei. **Se utiliza exclusivamente pnpm.**

## Desarrollo

Requisitos: Node.js 22.22.2+ (rama 22), 24.15.0+ (rama 24) o 26+, y pnpm 11.2.2. La versión de pnpm queda fijada en `packageManager`.

Desde `front/`:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

El servidor Vite ofrece el frontend en `http://127.0.0.1:5173`. Su proxy de desarrollo dirige `/api` al **gateway en `http://127.0.0.1:8080`**; nunca a dominio ni a las réplicas. El stack debe estar ejecutándose para recibir respuestas reales. No se incorporan servicios simulados al runtime.

En el despliegue de entrega, el único puerto publicado sigue siendo **8080**, definido en `compose.yaml`. No se modifica ese compose para desarrollar.

## Contrato y comportamiento

- Solo se envía `POST /api/chat` con `{ "mensaje": "..." }`, misma ruta relativa en desarrollo y producción.
- Se validan entre 3 y 1200 caracteres recortando espacios exteriores. Enter envía; Shift+Enter agrega una línea; se respeta la composición de texto IME.
- El detalle de cada respuesta muestra `intencion`, `confianza`, `version_modelo`, `replica_ia`, `latencia_total_ms`, `derivar_humano` y `prediccion_id`, sin métricas inventadas. La latencia es la **del backend**, no el tiempo de ida y vuelta del navegador. Una réplica nula se presenta como «No informada».
- El contrato se verifica en runtime. Un HTTP 200 incompleto no se presenta como una predicción confirmada. También se manejan errores JSON, HTML del gateway, desconexión y un timeout de 12 segundos.
- No hay reintentos automáticos de POST: un fallo de red o timeout puede ocurrir después de guardar la predicción. «Reenviar consulta» es una acción explícita y puede crear otro registro.
- «Esperando tu consulta» no afirma que todos los servicios estén saludables. Los eventos de red del navegador tampoco prueban la disponibilidad del backend. La respuesta de `/api/chat` es la confirmación de la operación.
- La derivación se muestra como solicitud registrada, **sin conexión real con Genesys o un ejecutivo**. No hay autenticación, consulta de cuentas ni operaciones comerciales.
- El historial permanece solo en memoria mientras esté abierta la página; no se guarda en localStorage. No compartir información personal o secretos.

## Accesibilidad y 3D

El chat tiene etiquetas, navegación por teclado, enlace de salto, región de mensajes, avisos de estado/error y foco visible. Los metadatos se abren con un control nativo `details`.

La escena es decorativa (`aria-hidden`), se importa de forma diferida y está aislada por un error boundary. Fallos de carga, inicialización WebGL o pérdida del contexto dejan una esfera CSS y no desmontan el chat. Con `prefers-reduced-motion: reduce` **no se descarga la escena 3D** y se desactivan animaciones y desplazamiento suave. Se limita el DPR a 1.5, se solicita GPU de bajo consumo y se pausa el renderizado con la pestaña oculta. No hay texturas, fuentes remotas, controles de cámara ni postprocesado.

## Validación

```powershell
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
pnpm audit --prod
```

Las pruebas E2E sirven `dist` con Vite Preview: requieren `pnpm build` primero. Los fixtures sintéticos solo se importan desde pruebas; **no son resultados del backend real**. Se cubren contrato HTTP, campos inválidos, errores 422/502/503, timeout, cancelación, prevención de doble envío, reenvío manual, desconexión, teclado, metadatos, derivación, escape de HTML, móvil, WebGL y movimiento reducido.

## Docker y CI

Desde la **raíz del repositorio**:

```powershell
docker build --platform linux/amd64 -f front/Dockerfile -t andesatiende-front:local .
docker run -d --name andesatiende-front-check --platform linux/amd64 andesatiende-front:local
docker inspect --format '{{.State.Health.Status}}' andesatiende-front-check
docker exec andesatiende-front-check wget -q -O - http://127.0.0.1/health
docker exec andesatiende-front-check wget -q -O /dev/null http://127.0.0.1/ruta-spa
docker image inspect andesatiende-front:local --format '{{.Size}}'
docker rm -f andesatiende-front-check
```

Esperar a que el healthcheck informe `healthy` antes de evaluar su estado. La prueba no publica puertos. Para verificar el chat completo se necesita el gateway y el resto del stack; el Nginx del frontend solo sirve archivos y `/health`.

El Dockerfile instala con lockfile congelado, ejecuta pruebas unitarias y compila en Node Alpine. La imagen final contiene únicamente Nginx Alpine y `dist`, sin Node, pnpm ni dependencias de desarrollo. `Dockerfile.dockerignore` limita **solo este build** a `front/`, excluyendo dependencias locales, resultados y archivos de entorno; no afecta los builds de IA/datos. Nginx conserva SPA y `/health`, con assets versionados cacheables, HTML revalidable y compresión gzip para JS/CSS.

No se necesitan cambios en Actions: el build existente desde raíz ejecuta ahora las pruebas unitarias y compilación del frontend. Las E2E son un control local adicional; el workflow no instala Chromium. Se conservan etiquetas GHCR y puertos del compose.

## Resultados y límites de esta migración

Validado en Windows con Node 22.23.1 y pnpm 11.2.2:

- Instalación y compilación de producción correctas.
- 28 pruebas unitarias correctas.
- 7 pruebas Chromium de teclado/contrato, móvil, gateway fallido, fallback sin WebGL, escena WebGL, descarga fallida de Three.js y pérdida del contexto.
- Auditoría de dependencias de producción sin vulnerabilidades conocidas al ejecutarla.
- Advertencia de Vite: el chunk 3D supera 500 KB minificados (~243 KB gzip en la primera compilación); se carga aparte del chat. No se oculta esta advertencia.

**No validado aquí:** Docker no está instalado; no se construyó la imagen ni se verificaron su healthcheck, tamaño, consumo total del stack o el chat contra el gateway/backend reales. El presupuesto conjunto de 2 GB debe medirse en Docker, no deducirse del tamaño de los bundles. No se publicaron imágenes ni se modificaron backend, modelo, datos, gateway, compose o workflow.

Las pruebas Python de dominio se intentaron, pero el entorno no tiene `pytest` (`ModuleNotFoundError`) y dispone de Python 3.11, no del 3.12 previsto por el proyecto. No se instalaron dependencias Python ni se ejecutó ETL/entrenamiento para esta migración; las pruebas de datos e IA siguen pendientes en el entorno del proyecto/CI.

## Integración en dev

1. Revisar el diff en `feat/frontend-react-three` y repetir instalación congelada, pruebas y build.
2. Ejecutar Docker y los controles anteriores en un equipo con Docker Desktop; probar la ruta SPA, `/health`, errores y respuesta real a través de `:8080/api/chat`.
3. Medir imagen final y `docker stats` de todo el stack; contrastar con el presupuesto de 2 GB y el límite de 64 MB del frontend.
4. Integrar mediante PR hacia `dev` y comprobar Actions. La publicación GHCR/etiquetas sigue el proceso del README raíz; no se realiza desde esta migración.
