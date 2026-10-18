# Defensa de EP2 · Equipo 05 · Guion de teclado (15 min)

**Todavía no ejecutado en Docker Desktop ni validado en GHCR.**

1. **Minuto 0–2 · Preparar**: abrir PowerShell en el directorio del compose y ejecutar solamente `docker compose -p equipo05 pull`, `docker compose -p equipo05 up -d`; visitar `http://localhost:8080`.
2. **Minuto 2–4 · Inferencia y persistencia**: enviar «No tengo internet», leer intención, versión y réplica. Consultar `docker compose -p equipo05 exec db psql -U andes -d andesdb -c 'SELECT fecha,resultado,version_modelo FROM predicciones ORDER BY fecha DESC LIMIT 5;'`.
3. **Minuto 4–7 · Alta disponibilidad**: mantener enviando mensajes, identificar una réplica con `docker ps`, detenerla con `docker stop <nombre>`, demostrar respuestas en nuevas peticiones y explicar que Nginx utiliza la otra réplica. Reconocer que el resto del stack tiene puntos únicos de falla.
4. **Minuto 7–10 · Consumo**: ejecutar `python scripts/probar_carga.py --n 100` y `docker stats`; justificar `mem_limit` con el máximo observado y proyectarlo a una clase de instancia AWS cuyo costo se verifique.
5. **Minuto 10–12 · Datos/modelo**: explicar 627 duplicados originales, las 2.482 fechas invertidas antes de deduplicar (2.451 después), por qué no se borra el ticket, los 197 descartes de entrenamiento por etiqueta no válida y la división única 908/303 textos. Un macro F1 de 1.00 en muestra sintética NO representa un chatbot apto para producción.
6. **Minuto 12–15 · CI/CD y seguridad**: mostrar PR feat → dev → main, workflow verde, etiqueta `org.opencontainers.image.revision`, paquete `:ep2`, y explicar que el modelo se entrenó en CI, no se subió manualmente. Distinguir autenticación y TLS de producción de la demo local.

**Preguntas probables:** ¿Qué devuelve `/predict`? ¿Qué pasa al detener ambas réplicas? ¿Por qué IA no lee SQL? ¿Por qué el modelo está dentro de una imagen amd64? ¿Qué es RTO y RPO? ¿Qué no cumple RT8? ¿Qué harías si el p95 crece? ¿Cómo garantiza el job que no duplica? ¿Por qué el 1,00 de macro F1 no significa generalización real?
