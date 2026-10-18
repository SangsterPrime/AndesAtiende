# Estado de validación real · 18/10/2026

| Verificación | Resultado | Evidencia |
|---|---|---|
| Lectura de cuatro CSV del Caso 2 | Confirmado | 6.074 clientes, 24.312 tickets, 8.241 conversaciones y 500 FAQ antes de limpiar |
| Duplicados exactos | Confirmado | 74+312+241+0 = 627 |
| Cierres anteriores a apertura | Confirmado | 2.482 en CSV original, 2.451 después de deduplicar por ticket_id |
| ETL reproducible | Ejecutado | `python datos/preparar.py`, salida `reporte_calidad.json` |
| Modelo de IA real | Entrenado | `servicio-ia/modelo/clasificador.joblib` y metadata |
| Métrica macro-F1 sobre textos únicos | 1.0000 | 908 textos de train, 303 de test, muestra sintética extremadamente repetitiva; limitada validez externa |
| Test datos | 2/2 pasó | `pytest -q datos/tests` |
| Test API de IA | 2/2 pasó | `PYTHONPATH=servicio-ia pytest -q servicio-ia/tests` |
| Test utilidades dominio | 2/2 pasó | `PYTHONPATH=servicio-dominio pytest -q servicio-dominio/tests` |
| Análisis YAML | Correcto | 7 servicios, 1 puerto expuesto (8080), sin `build:` en `compose.yaml` |
| Docker imagen tamaño <2 GB | **No medido** | Este entorno no tiene Docker Engine |
| `docker compose pull` / `up -d` en Windows | **No verificado** | Requiere imágenes GHCR reales del usuario |
| Tests integrados con PostgreSQL | **No ejecutados** | Requiere Docker/instalación psycopg; tests de dominio son unitarios solamente |
| GitFlow con 2 PR por integrante | **No realizado** | Requiere cuentas GitHub y PR reales |
| Pipeline GHCR verde y tag ep2 publicado | **No realizado** | Requiere push al repositorio del equipo |
| Docker stats y latencia p95 | **No medido** | Hay script de carga, no hay evidencia de consumo real |
| AWS costo y RTO/RPO | **Pendiente** | Debe respaldarse con medición/cotización AWS, no inventarse |
| PDF arc42 final 15 páginas | **Pendiente** | Hay borrador markdown y 8 fuentes Mermaid, faltan links y validaciones |

La solución es una primera implementación de laboratorio para continuar en el computador del equipo. Los datos fuente seudonimizados no equivalen a un dataset aprobado para datos personales reales.
