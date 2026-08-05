FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 horo && \
    useradd --uid 10001 --gid horo --no-create-home \
      --home-dir /app --shell /usr/sbin/nologin horo

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=horo:horo alembic.ini ./
COPY --chown=horo:horo alembic ./alembic
COPY --chown=horo:horo src ./src
COPY --chown=horo:horo scripts ./scripts
RUN mkdir -p /app/data && chown horo:horo /app/data

USER horo

# 這是 healthcheck 唯一的定義處，compose 不再重複一份。
# start_period 要涵蓋啟動時的 alembic 升級與指令同步，之後才會有第一次心跳。
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-m", "src.healthcheck"]

CMD ["python", "-m", "src.main"]
