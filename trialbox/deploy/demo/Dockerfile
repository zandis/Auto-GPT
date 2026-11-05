# syntax=docker/dockerfile:1.7
# Role demo (D-104): the whole TrialBox box in one process on the SYNTHETIC hospital, one sign-in per role.
# For trying the product on a public host (Hugging Face Spaces, Render, Cloud Run, any Docker host). Never real data.
#   docker build -f deploy/demo/Dockerfile -t trialbox-demo .        (context = the trialbox/ folder)
#   docker run -p 8080:8080 -e TB_DEMO_PASSWORD=... trialbox-demo
# Accounts: admin, crc, pi, smo, cra, viewer; one shared password from TB_DEMO_PASSWORD (else printed in the log).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl TB_FONTS_DIR=/app/.cache/fonts \
    TB_DEMO_HOST=0.0.0.0 PORT=8080 TB_DEMO_DIR=/tmp/tb-role-demo TB_CONSOLE_SECURE_COOKIE=1
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin tb
WORKDIR /app
COPY deploy/requirements.lock /tmp/requirements.lock
# Optional build secret "extra_ca" (PEM) is trusted during the build only (corporate TLS proxies).
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: -r /tmp/requirements.lock "pytest>=8.3"  # pytest: tests/inproc_box.py imports test helpers
COPY --chown=tb:tb . /app
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    python tools/fetch_fonts.py && chown -R tb:tb /app/.cache
USER tb
EXPOSE 8080
# --fresh: every start rebuilds the synthetic hospital, so a restart resets the demo
CMD ["python", "-m", "tools.role_demo", "--fresh"]
