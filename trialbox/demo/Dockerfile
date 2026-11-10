# syntax=docker/dockerfile:1.7
# Demo image (D-104, D-111): the whole TrialBox box in one process on the SYNTHETIC hospital, one sign-in per role.
# For trying the product on a public host (Hugging Face Spaces, Render, Cloud Run, any Docker host). Never real data.
#   docker build -f demo/Dockerfile -t trialbox-demo .        (context = the trialbox/ folder)
#   docker run -p 8080:8080 -e TB_DEMO_PASSWORD=... trialbox-demo
# Accounts: admin, crc, pi, smo, cra, viewer; one shared password from TB_DEMO_PASSWORD (else printed in the log).
# the same pinned base as deploy/docker/python.Dockerfile (an index digest: amd64 and arm64)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl TB_FONTS_DIR=/app/.cache/fonts \
    TB_DEMO_HOST=0.0.0.0 PORT=8080 TB_DEMO_DIR=/tmp/tb-role-demo TB_CONSOLE_SECURE_COOKIE=1
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin tb
WORKDIR /app
# PostgreSQL server binaries: since D-126 the demo's trial data lives in a throwaway local cluster (tools/pglocal.py),
# and the update path backs it up with pg_dump first (D-138)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.lock /tmp/requirements.lock
# Optional build secret "extra_ca" (PEM) is trusted during the build only (corporate TLS proxies).
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: -r /tmp/requirements.lock; \
    pip install $CERT --only-binary=:all: "pytest==9.2.0"  # tests/inproc_box.py imports test helpers; version of uv.lock
COPY --chown=tb:tb . /app
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    python tools/fetch_fonts.py && chown -R tb:tb /app/.cache
USER tb
EXPOSE 8080
# Every start rebuilds the synthetic hospital, so a restart resets the demo. Default (step 5, D-111): the whole step
# 1-4 flow seeded and checked by tools.demo (about 70 s before the console answers). TB_DEMO_TOOL=role_demo gives the
# older role-only demo (600 patients, ready in about 30 s). TB_DEMO_TOOL=public_e2e serves the public-data site
# (tools.public_site: 268 real public notes, SIGIR + MedTxt; needs .cache/medtxt in the build context).
ENV TB_DEMO_TOOL=demo
CMD ["sh", "-c", "if [ \"$TB_DEMO_TOOL\" = public_e2e ]; then exec python -m tools.public_e2e --dir /tmp/tb-public --serve --host 0.0.0.0 --port $PORT --lang ${TB_DEMO_LANG:-ja}; else exec python -m tools.${TB_DEMO_TOOL} --fresh; fi"]
