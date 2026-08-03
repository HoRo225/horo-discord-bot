FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 crystalline && \
    useradd --uid 10001 --gid crystalline --no-create-home \
      --home-dir /app --shell /usr/sbin/nologin crystalline

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=crystalline:crystalline alembic.ini ./
COPY --chown=crystalline:crystalline alembic ./alembic
COPY --chown=crystalline:crystalline src ./src
COPY --chown=crystalline:crystalline scripts ./scripts
RUN mkdir -p /app/data && chown crystalline:crystalline /app/data

USER crystalline

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-m", "src.healthcheck"]

CMD ["python", "-m", "src.main"]
