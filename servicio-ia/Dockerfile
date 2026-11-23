FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY servicio-ia/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 appuser
COPY servicio-ia/app /app/app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --retries=5 --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]

# El build predeterminado conserva el modelo local de EP2.
# EP3 construye --target runtime: no copia ni necesita archivos .joblib.
FROM runtime AS local
COPY --chown=appuser:appuser servicio-ia/modelo /app/modelo
