# syntax=docker/dockerfile:1.7
# The box's one PostgreSQL server (D-121, D-126, D-204): Debian `postgres:16` with pgvector 0.8.x (from the
# PostgreSQL apt repository, already configured in the base image) and PGroonga 4.1.x (from the Groonga apt
# repository). The base is pinned by its multi-arch index digest and the two packages by exact version; all three are
# recorded in deploy/images.lock, which a test keeps equal to the ARG defaults below.
#   docker build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker
# Behind a TLS-intercepting proxy add: --network host --build-arg https_proxy=$HTTPS_PROXY \
#   --secret id=extra_ca,src=<proxy CA PEM>   (apt, as user _apt, then fetches every repository over https trusting it).
# Without the secret, Debian and PostgreSQL packages come over http (apt checks their signatures) and Groonga's over
# https once ca-certificates is installed. The Groonga signing key is vendored (db.groonga-archive-keyring.asc) and
# checked against its fingerprint: nothing is trusted on first download.
# Base suite: trixie, not bookworm (D-204): PGroonga 4.1.x is not built for bookworm (last there: 4.0.6) and needs
# glibc >= 2.38. The extensions are created by db-init/20-extensions.sh on the first start of an empty volume, as
# the role `trialbox`: both are marked `trusted` here (D-204), so the database owner can create, own, drop and re-create
# them, which a restore as `trialbox` (pg_restore --clean --if-exists, tools/trialbox/backup.py, update.py) needs.
# /usr/local/bin/tb-db-check (db.healthcheck.sh) is the readiness check: server up, trialbox_wf there, both extensions
# installed; a compose healthcheck runs it (D-204 lists the wiring).
ARG POSTGRES_BASE=postgres:16-trixie@sha256:f9a7b9ebf6f56201f949db745e47bc423c0f0f8294bafe991cc10bf74b029657
FROM ${POSTGRES_BASE}
ARG PGVECTOR_VERSION=0.8.7-1.pgdg13+1
ARG PGROONGA_VERSION=4.1.0-1
ARG LIBGROONGA_VERSION=16.1.5-1
ARG GROONGA_KEY_FINGERPRINT=2701F317CFCCCB975CADE9C2624CF77434839225
COPY db.groonga-archive-keyring.asc /usr/share/keyrings/groonga-archive-keyring.asc
COPY --chmod=0755 db.healthcheck.sh /usr/local/bin/tb-db-check
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    set -eux; \
    KEYS="$(gpg --show-keys --with-colons /usr/share/keyrings/groonga-archive-keyring.asc)"; \
    test "$(printf '%s\n' "$KEYS" | grep -c '^pub:')" = 1; \
    test "$(printf '%s\n' "$KEYS" | grep -A1 '^pub:' | grep '^fpr:' | cut -d: -f10)" = "${GROONGA_KEY_FINGERPRINT}"; \
    APT="-o APT::Install-Recommends=false -o Dpkg::Use-Pty=0"; \
    if [ -s /run/secrets/extra_ca ]; then \
      sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/pgdg.list; \
      APT="$APT -o Acquire::https::CAInfo=/run/secrets/extra_ca"; \
    fi; \
    apt-get $APT update; \
    apt-get $APT install -y ca-certificates; \
    . /etc/os-release; \
    printf 'Types: deb\nURIs: https://packages.groonga.org/debian/\nSuites: %s\nComponents: main\nSigned-By: %s\n' \
      "$VERSION_CODENAME" /usr/share/keyrings/groonga-archive-keyring.asc > /etc/apt/sources.list.d/groonga.sources; \
    apt-get $APT update; \
    apt-get $APT install -y \
      "postgresql-${PG_MAJOR}-pgvector=${PGVECTOR_VERSION}" \
      "postgresql-${PG_MAJOR}-pgdg-pgroonga=${PGROONGA_VERSION}" \
      "libgroonga0=${LIBGROONGA_VERSION}"; \
    apt-mark hold "postgresql-${PG_MAJOR}-pgvector" "postgresql-${PG_MAJOR}-pgdg-pgroonga" libgroonga0; \
    test "$(dpkg-query -W -f '${Version}' libgroonga0)" = "${LIBGROONGA_VERSION}"; \
    test "$(dpkg-query -W -f '${Version}' "postgresql-${PG_MAJOR}-pgvector")" = "${PGVECTOR_VERSION}"; \
    test "$(dpkg-query -W -f '${Version}' "postgresql-${PG_MAJOR}-pgdg-pgroonga")" = "${PGROONGA_VERSION}"; \
    test -f "/usr/share/postgresql/${PG_MAJOR}/extension/vector.control"; \
    test -f "/usr/share/postgresql/${PG_MAJOR}/extension/pgroonga.control"; \
    for ext in vector pgroonga; do \
      f="/usr/share/postgresql/${PG_MAJOR}/extension/${ext}.control"; \
      if grep -q '^trusted' "$f"; then echo "$f already sets trusted" >&2; exit 1; fi; \
      echo 'trusted = true' >> "$f"; \
    done; \
    if [ -s /run/secrets/extra_ca ]; then \
      sed -i 's|https://|http://|g' /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/pgdg.list; \
    fi; \
    rm -rf /var/lib/apt/lists/*
LABEL org.opencontainers.image.title="trialbox-postgres" \
      org.opencontainers.image.description="PostgreSQL 16 with pgvector and PGroonga for TrialBox (D-204)"
