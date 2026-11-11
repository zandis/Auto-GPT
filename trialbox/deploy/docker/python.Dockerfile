# syntax=docker/dockerfile:1.7
# Base image for every TrialBox Python service (multi-arch: linux/amd64, linux/arm64).
#   docker buildx build --platform linux/amd64,linux/arm64 -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
# Prerequisites in the build context: .cache/fonts (tools/fetch_fonts.py).
# No OS packages are installed (DECISIONS D-23): git via dulwich, 7z via py7zr, PID 1 via compose `init: true`.
# Optional build secret "extra_ca" (PEM) is trusted for pip during the build only (corporate TLS proxies).
# pinned by index digest (amd64 and arm64); move it in a pull request so the release gates scan the new base (D-186)
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/libs:/app/services:/app MPLBACKEND=Agg TB_DATA_DIR=/data MPLCONFIGDIR=/tmp/mpl \
    TB_FONTS_DIR=/opt/trialbox/fonts
# Debian security updates for the packages the base already has (no new package, D-23): the pinned base may lag a
# fix (zlib1g, Nov 2026); the release gates scan the result by image id (D-186)
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin tb \
    && mkdir -p /app /data/lake /data/audit /data/orchestrator /data/rulesets /data/mail /data/traces /data/objects \
       /run/secrets/trialbox \
    && chown -R tb:tb /data /run/secrets/trialbox && chmod 700 /run/secrets/trialbox
COPY deploy/requirements.lock /tmp/requirements.lock
# $CERT is empty or "--cert <file>": it must split into two words (SC2086 by design)
# hadolint ignore=SC2086
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: -r /tmp/requirements.lock
# Report fonts (SPEC §9: Noto Sans TC/JP embedded; OFL). Prerequisite: tools/fetch_fonts.py fills .cache/fonts.
COPY .cache/fonts/OFL.txt .cache/fonts/NotoSansTC-Regular.ttf .cache/fonts/NotoSansTC-Bold.ttf \
     .cache/fonts/NotoSansJP-Regular.ttf .cache/fonts/NotoSansJP-Bold.ttf /opt/trialbox/fonts/
COPY --chown=tb:tb schemas /app/schemas
COPY --chown=tb:tb libs /app/libs
COPY --chown=tb:tb services /app/services
COPY --chown=tb:tb tools /app/tools
COPY --chown=tb:tb rulesets /app/rulesets
# T-107 (D-353): the clinical item catalogue, read as data by the items page, the OMOP load and chart extraction
COPY --chown=tb:tb catalogue /app/catalogue
# routing policy, model registry and cards (tb-gateway, model-registry); a site pin is mounted, never baked in
COPY --chown=tb:tb models /app/models
COPY --chown=tb:tb deploy/settings.example.yaml /app/deploy/settings.example.yaml
COPY --chown=tb:tb pyproject.toml /app/pyproject.toml
# admin console state (accounts, sessions, pilot runs): a named volume takes this owner on first use
RUN install -d -o tb -g tb -m 0750 /data/console
WORKDIR /app
USER tb
CMD ["python", "-c", "print('specify a service command')"]
