# syntax=docker/dockerfile:1.7
# The box's one PostgreSQL server (D-121, D-126, D-204, D-371): Debian 13 `postgres:16` with pgvector 0.8.x and
# pgBackRest 2.60.x (from the PostgreSQL apt repository, PGDG, already configured in the base image) and PGroonga 4.1.x
# (from the Groonga apt repository). The base is pinned by its multi-arch index digest and the packages by exact
# version; all are recorded in deploy/images.lock, which a test keeps equal to the ARG defaults below.
# One PostgreSQL major everywhere (D-371): PG_MAJOR here, `postgres_major` in the lock, the demo image's PG_MAJOR and
# tools/ci_postgres.sh in CI; tests/unit/test_pg_major.py holds them equal, and the build stops on another pg_config.
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
ARG POSTGRES_BASE=postgres:16-trixie@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f
FROM ${POSTGRES_BASE}
ARG PGVECTOR_VERSION=0.8.7-1.pgdg13+1
ARG PGROONGA_VERSION=4.1.0-1
ARG LIBGROONGA_VERSION=16.1.5-1
ARG PGBACKREST_VERSION=2.60.0-1.pgdg13+1
# SC-1b (D-993): the base's zlib1g carries CVE-2026-85091; the fix is in trixie-security, held at it like the rest
ARG ZLIB1G_VERSION=1:1.3.dfsg+really1.3.1-1+deb13u1
# H-93: the base's krb5 libraries (1.21.3-5+deb13u1; the server and libpq5 link libgssapi-krb5-2) carry 14 CVEs the
# release gates fail on (CVE-2026-71199 to CVE-2026-119079, DSA-6650-1); the fix is in trixie-security, held like zlib1g
ARG KRB5_VERSION=1.21.3-5+deb13u2
ARG PG_MAJOR_EXPECTED=16
ARG GROONGA_KEY_FINGERPRINT=2701F317CFCCCB975CADE9C2624CF77434839225
COPY db.groonga-archive-keyring.asc /usr/share/keyrings/groonga-archive-keyring.asc
COPY --chmod=0755 db.healthcheck.sh /usr/local/bin/tb-db-check
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    set -eux; \
    rm /usr/local/bin/gosu; command -v setpriv; \
    test "${PG_MAJOR}" = "${PG_MAJOR_EXPECTED}"; \
    pg_config --version | grep -q "^PostgreSQL ${PG_MAJOR_EXPECTED}\."; \
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
      "libgroonga0=${LIBGROONGA_VERSION}" \
      "pgbackrest=${PGBACKREST_VERSION}" \
      "zlib1g=${ZLIB1G_VERSION}" \
      "libkrb5-3=${KRB5_VERSION}" "libkrb5support0=${KRB5_VERSION}" "libk5crypto3=${KRB5_VERSION}" \
      "libgssapi-krb5-2=${KRB5_VERSION}"; \
    apt-mark hold "postgresql-${PG_MAJOR}-pgvector" "postgresql-${PG_MAJOR}-pgdg-pgroonga" libgroonga0 pgbackrest; \
    apt-mark hold zlib1g libkrb5-3 libkrb5support0 libk5crypto3 libgssapi-krb5-2; \
    for p in libkrb5-3 libkrb5support0 libk5crypto3 libgssapi-krb5-2; do \
      test "$(dpkg-query -W -f '${Version}' "$p")" = "${KRB5_VERSION}"; \
    done; \
    test "$(dpkg-query -W -f '${Version}' zlib1g)" = "${ZLIB1G_VERSION}"; \
    test "$(dpkg-query -W -f '${Version}' pgbackrest)" = "${PGBACKREST_VERSION}"; \
    pgbackrest version | grep -q "^pgBackRest ${PGBACKREST_VERSION%%-*}$"; \
    install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest /var/spool/pgbackrest /var/log/pgbackrest; \
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
# SC-1b (D-993): the upstream gosu (a Go binary, the source of most of the image's findings) is replaced by a shell shim
# on setpriv at the same path, so the upstream entrypoint's `gosu postgres ...` drops root the same way. The binary is
# deleted in the layer above and the shim copied in its own: a scanner that reads the image layer by layer (Trivy) keeps
# a file a later layer only overwrites, so an overwrite alone left Go 1.24.6 in the gate (train 70); the deletion is a
# whiteout it applies.
COPY --chmod=0755 db.gosu-setpriv.sh /usr/local/bin/gosu
RUN test "$(head -c 2 /usr/local/bin/gosu)" = "#!"
LABEL org.opencontainers.image.title="trialbox-postgres" \
      org.opencontainers.image.description="PostgreSQL 16 with pgvector, PGroonga and pgBackRest for TrialBox (D-204, D-371)"
