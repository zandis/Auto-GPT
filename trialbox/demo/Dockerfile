# syntax=docker/dockerfile:1.7
# Demo image (D-104, D-111): the whole TrialBox box in one process on the SYNTHETIC hospital, one sign-in per role.
# For trying the product on a public host (Hugging Face Spaces, Render, Cloud Run, any Docker host). Never real data.
#   docker build -f demo/Dockerfile -t trialbox-demo .        (context = the trialbox/ folder; a fresh clone is enough)
#   docker run -p 8080:8080 trialbox-demo                     (no -e needed; the password is printed in the log)
# Accounts: admin, crc, pi, subpi, cra, viewer; one shared password from TB_DEMO_PASSWORD (else printed in the log);
# per-tester accounts from TB_DEMO_ACCOUNTS and a kept data folder with TB_DEMO_KEEP=1 (T-505b, demo/README.md).
# Measured (T-501, demo/README.md): peak memory 1.8 GB, first answer on /login after 3 to 6 minutes; plan 4 GB.
# the same pinned base as deploy/docker/python.Dockerfile (an index digest: amd64 and arm64)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl TB_FONTS_DIR=/app/.cache/fonts \
    TB_DEMO_HOST=0.0.0.0 PORT=8080 TB_DEMO_DIR=/tmp/tb-role-demo TB_CONSOLE_SECURE_COOKIE=1
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin tb && mkdir /data && chown tb:tb /data  # T-505b: a volume on /data
WORKDIR /app
# PostgreSQL server binaries: since D-126 the demo's trial data lives in a throwaway local cluster (tools/pglocal.py),
# and the update path backs it up with pg_dump first (D-138)
ARG PG_MAJOR=16
# postgresql-<PG_MAJOR> from PGDG (D-371: one major for the db image, the demo and CI; tests/unit/test_pg_major.py),
# with the PGDG key that Debian's postgresql-common ships; the build stops on another pg_config --version. The release
# gates scan the built image (D-186); upgrade: Debian security fixes
# hadolint ignore=DL3008
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; if [ -s /run/secrets/extra_ca ]; then echo 'Acquire::https::CAInfo "/run/secrets/extra_ca";' > /etc/apt/apt.conf.d/99-extra-ca; fi; \
    apt-get update; apt-get upgrade -y --no-install-recommends; \
    apt-get install -y --no-install-recommends postgresql-common; /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y; \
    apt-get install -y --no-install-recommends "postgresql-${PG_MAJOR}"; \
    v="$("/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config" --version)"; echo "$v"; \
    case "$v" in "PostgreSQL ${PG_MAJOR}."*) ;; *) echo "not PostgreSQL ${PG_MAJOR} (D-371)" >&2; exit 1 ;; esac; \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99-extra-ca
COPY deploy/requirements.lock /tmp/requirements.lock
# Optional build secret "extra_ca" (PEM) is trusted during the build only (corporate TLS proxies).
# every package is pinned (the lock file, pytest==); $CERT is empty or "--cert <file>" and must split
# hadolint ignore=DL3013,SC2086
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; CERT=""; if [ -f /run/secrets/extra_ca ]; then CERT="--cert /run/secrets/extra_ca"; fi; \
    pip install $CERT --only-binary=:all: -r /tmp/requirements.lock; \
    pip install $CERT --only-binary=:all: "pytest==9.2.0"  # tests/inproc_box.py imports test helpers; version of uv.lock
COPY --chown=tb:tb . /app
# T-501 (OPS-001, UX-001, LIFE-005): the compiler reads FHIRHelpers-4.0.1.cql from the translator's quick jar, also
# with the in-process fake translator. `make demo-bundle` runs `make jvm-deps` first, and .dockerignore lets only that
# jar into the context (the demo has no JRE, so the other translator jars would be dead weight). A build from a fresh
# clone (Render, Cloud Run, CI) has no jar: it is fetched from Maven Central and checked against its sha256. Either
# way the FHIRHelpers text must match the pinned sha256, or the build stops here, not at the first compile.
ARG CQL_QUICK_VERSION=5.4.0
ARG CQL_QUICK_SHA256=b5b1b076711d7c6ddb700f7f6d7aacc210824dc37a41405fdfd9fab09d6a2ba4
ARG FHIRHELPERS_SHA256=6748661c16fe66dd07a68f07f77f7fea44e8b933d265dcc3c575964ba8329591
ENV TB_CQL_TRANSLATOR_LIB=/app/.cache/jvm/cql-translator/lib
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    python tools/fetch_fonts.py; \
    mkdir -p "$TB_CQL_TRANSLATOR_LIB"; \
    if ! ls "$TB_CQL_TRANSLATOR_LIB"/quick-*.jar >/dev/null 2>&1; then \
      jar="$TB_CQL_TRANSLATOR_LIB/quick-$CQL_QUICK_VERSION.jar"; \
      python -c "import os,ssl,sys,urllib.request as u; c=ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or None); open(sys.argv[2],'wb').write(u.urlopen(sys.argv[1],timeout=120,context=c).read())" \
        "https://repo1.maven.org/maven2/org/cqframework/quick/$CQL_QUICK_VERSION/quick-$CQL_QUICK_VERSION.jar" "$jar"; \
      echo "$CQL_QUICK_SHA256  $jar" > /tmp/quick.sha256; sha256sum -c /tmp/quick.sha256; rm /tmp/quick.sha256; \
    fi; \
    PYTHONPATH=services python -c "import sys; from criteria_compiler.compile_cql.translator import fhirhelpers_source as f; open(sys.argv[1],'wb').write(f().encode())" \
      /app/.cache/jvm/FHIRHelpers-4.0.1.cql; \
    echo "$FHIRHELPERS_SHA256  /app/.cache/jvm/FHIRHelpers-4.0.1.cql" > /app/.cache/jvm/FHIRHelpers-4.0.1.cql.sha256; \
    sha256sum -c /app/.cache/jvm/FHIRHelpers-4.0.1.cql.sha256; \
    chown -R tb:tb /app/.cache
USER tb
EXPOSE 8080
# Every start rebuilds the synthetic hospital unless TB_DEMO_KEEP=1 (T-505b: it wins over --fresh; demo/README.md).
# Default (step 5, D-111): the whole step 1-4 flow seeded and checked by tools.demo (measured: 3 to 6 minutes before
# the console answers, peak 1.8 GB; demo/README.md). It seeds over https in process, so the Secure cookie above stays
# on (T-501). TB_DEMO_TOOL=role_demo gives the older role-only demo (600 patients, ready in about 20 s).
# TB_DEMO_TOOL=public_e2e serves the public-data site (tools.public_site: 268 real public notes, SIGIR + MedTxt;
# needs .cache/medtxt in the build context).
ENV TB_DEMO_TOOL=demo
CMD ["sh", "-c", "if [ \"$TB_DEMO_TOOL\" = public_e2e ]; then exec python -m tools.public_e2e --dir /tmp/tb-public --serve --host 0.0.0.0 --port $PORT --lang ${TB_DEMO_LANG:-ja}; else exec python -m tools.${TB_DEMO_TOOL} --fresh; fi"]
