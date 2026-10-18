FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY carga/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 appuser
COPY carga/cargar.py ./cargar.py
COPY datos/procesados/*.csv ./datos/
USER appuser
HEALTHCHECK --interval=15s --timeout=5s CMD python -c "import pathlib; assert pathlib.Path('/app/datos/clientes.csv').exists()"
CMD ["python","-u","cargar.py"]
