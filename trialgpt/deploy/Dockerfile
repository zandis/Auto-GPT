# TrialGPT interface (FastAPI + MedCPT retrieval on CPU). The LLM runs in the separate Ollama container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 UV_SYSTEM_PYTHON=1 \
    TG_HOST=0.0.0.0 TG_PORT=8090 \
    TG_DATA_DIR=/data/data TG_RESULTS_DIR=/data/results TG_CACHE_DIR=/data/cache \
    HF_HOME=/data/hf NLTK_DATA=/usr/local/share/nltk_data
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY trialgpt_local ./trialgpt_local
COPY benchmarks ./benchmarks
# behind a TLS-inspecting proxy: docker build --secret id=extra_ca,src=ca.crt --build-arg HTTPS_PROXY=...
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca UV_NATIVE_TLS=1 \
       REQUESTS_CA_BUNDLE=/run/secrets/extra_ca NLTK_ALLOW_PROXIED_URLOPEN=1; fi; \
    uv pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    uv pip install -e . && \
    python -c "import nltk; [nltk.download(p, download_dir='$NLTK_DATA', quiet=True, raise_on_error=True) for p in ('punkt_tab', 'punkt')]"

RUN useradd --create-home --uid 10001 tg && mkdir -p /data && chown tg /data
USER tg
VOLUME /data
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/config', timeout=4)"
CMD ["python", "-m", "trialgpt_local.app"]
