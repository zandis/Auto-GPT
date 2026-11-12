# syntax=docker/dockerfile:1.7
# trialbox-embed (ENG-003, D-563): trialbox-py plus the embedder's library, for the embed service alone.
#   docker build -f deploy/docker/embed.Dockerfile -t trialbox-embed:1.0.0 .
# deploy/requirements-embed.lock is the hashed export of uv.lock with the `embed` extra (`make lock`; `make
# lock-check` holds it): sentence-transformers, and torch from the publisher's CPU wheel index, so the image carries
# no CUDA library (the embedder runs on the CPU; the card's memory is the model pair's). The entries the base image
# already installed are the same versions and hashes; pip leaves them as they are.
# No weights are in the image: the pinned folder is mounted read-only at /models/embedder (D-429).
# Optional build secret "extra_ca" (PEM) is trusted for pip during the build only (corporate TLS proxies).
ARG BASE_IMAGE=trialbox-py:1.0.0
# the base is pinned through its ARG (the locally built trialbox-py tag): DL3006 cannot see it
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}
USER root
COPY deploy/requirements-embed.lock /tmp/requirements-embed.lock
# every entry carries sha256 hashes, so pip checks each file whatever index served it; the CPU wheel index is named
# for torch only (pyproject.toml [tool.uv.sources])
# $CERT is empty or "--cert <file>": it must split into two words (SC2086 by design)
# hadolint ignore=SC2086
# setuptools comes in because torch names it (its helpers that compile extensions); the service never compiles.
# It is taken out in the same layer, so no layer ships it: it carries an LGPL part (autocommand) and Windows
# launchers the licence gate cannot name. The start test embeds without it.
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu \
      -r /tmp/requirements-embed.lock; \
    pip uninstall -y setuptools
# the service never asks the publisher's hub for anything: the folder is the site's own (D-429)
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HOME=/tmp/hf
USER tb
CMD ["uvicorn", "embed_service.app:app", "--host", "0.0.0.0", "--port", "8014"]
