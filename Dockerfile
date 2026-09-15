# ── OrcAgent — production image ──
# Sensitive variables (API keys, private keys, secrets) are NEVER baked into
# the image. They are injected at runtime by the deployment platform.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# A compromised web process must not automatically become root inside the
# container. Create the service identity before source is copied and make only
# the app workspace writable by it for legacy/container deployments that do
# not mount /data.
RUN groupadd --system orcagent && useradd --system --gid orcagent --home-dir /app --shell /usr/sbin/nologin orcagent
COPY --chown=orcagent:orcagent . .
RUN chmod 755 start.sh && find /app -type d -exec chmod 755 {} +

USER orcagent:orcagent

EXPOSE 8080

# start.sh launches monitor.py in the background, then execs gunicorn as PID 1.
CMD ["sh", "start.sh"]
