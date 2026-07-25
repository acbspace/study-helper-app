FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY services/api/pyproject.toml services/api/README.md ./services/api/
RUN pip install --upgrade pip && cd services/api && pip install .

COPY services/api ./services/api
WORKDIR /srv/services/api
RUN pip install --no-deps .

COPY services/worker /srv/services/worker
WORKDIR /srv/services/worker

CMD ["python", "-m", "arq", "worker.main.WorkerSettings"]
