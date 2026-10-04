# syntax=docker/dockerfile:1.7
# Base image for every TrialBox Python service (multi-arch: linux/amd64, linux/arm64).
#   docker buildx build --platform linux/amd64,linux/arm64 -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
# No OS packages are installed (DECISIONS D-23): git via dulwich, 7z via py7zr, PID 1 via compose `init: true`.
# Optional build secret "extra_ca" (PEM) is trusted for pip during the build only (corporate TLS proxies).
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/libs:/app/services:/app MPLBACKEND=Agg TB_DATA_DIR=/data MPLCONFIGDIR=/tmp/mpl
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin tb \
    && mkdir -p /app /data/lake /data/audit /data/orchestrator /data/rulesets /data/mail /run/secrets/trialbox \
    && chown -R tb:tb /data /run/secrets/trialbox && chmod 700 /run/secrets/trialbox
COPY deploy/requirements.lock /tmp/requirements.lock
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: -r /tmp/requirements.lock
COPY --chown=tb:tb schemas /app/schemas
COPY --chown=tb:tb libs /app/libs
COPY --chown=tb:tb services /app/services
COPY --chown=tb:tb tools /app/tools
COPY --chown=tb:tb rulesets /app/rulesets
COPY --chown=tb:tb deploy/settings.example.yaml /app/deploy/settings.example.yaml
COPY --chown=tb:tb pyproject.toml /app/pyproject.toml
WORKDIR /app
USER tb
CMD ["python", "-c", "print('specify a service command')"]
