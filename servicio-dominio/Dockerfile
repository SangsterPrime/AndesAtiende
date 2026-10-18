FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY servicio-dominio/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 appuser
COPY servicio-dominio/app /app/app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --retries=5 --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
