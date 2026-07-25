FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY services/api/pyproject.toml services/api/README.md ./services/api/
RUN pip install --upgrade pip && \
    cd services/api && pip install .

COPY services/api ./services/api

WORKDIR /srv/services/api
RUN pip install --no-deps .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
