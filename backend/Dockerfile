FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/models
WORKDIR /app
COPY requirements.lock requirements-local.txt ./
RUN pip install --no-cache-dir -r requirements.lock && \
    pip install --no-cache-dir -r requirements-local.txt --extra-index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-cache-dir --no-deps . && \
    useradd --create-home --uid 10001 ainews && mkdir -p /models /state && chown -R ainews:ainews /models /state
USER ainews
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
