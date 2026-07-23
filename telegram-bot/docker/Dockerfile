# Python 3.13: setup.cfg declares python_requires >=3.13,<3.15. The previous
# 3.11 base ran an interpreter the project does not claim to support.
# 3.13 also keeps requirements.txt on the asyncpg branch of its version marker.
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build into an isolated venv so the runtime stage copies only what it needs
# and never inherits build tooling.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    BOT_PERSISTENCE_PATH=/data/bot_data.pkl

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Run as an unprivileged user. /data holds PicklePersistence state and must be
# a volume: without it, in-flight event-creation flows are lost on restart.
RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /data \
    && chown -R botuser:botuser /data /app

COPY --chown=botuser:botuser . .

USER botuser

VOLUME ["/data"]

# Polling mode exposes no port; this is the webhook listener port
# (WEBHOOK_PORT, default 8443) used when ENVIRONMENT=production.
EXPOSE 8443

# The database is the dependency most likely to fail underneath a running bot.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

CMD ["python", "main.py"]
