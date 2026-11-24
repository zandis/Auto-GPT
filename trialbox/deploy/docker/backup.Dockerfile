# syntax=docker/dockerfile:1.7
# The nightly backup's container (PERF-010, D-968): trialbox-py plus restic, used by nothing else. It runs with no
# network (the nightly's `docker run`), so restic's Go code is kept out of every service image.
#   docker build --build-arg BASE_IMAGE=trialbox-py:1.0.0 -f deploy/docker/backup.Dockerfile -t trialbox-backup:1.0.0 .
# restic is built here from its release's source archive (pinned by sha256) with a patched Go (the image pinned by
# index digest), and its modules are fetched under its own go.sum (GOSUMDB checks them; -mod=readonly fails on any
# change). The licence register's row `restic` holds the same version and sums (tools/licence_register.py --check).
# RESTIC_MODULE_BUMPS: the release's modules that the image gates find open advisories in, raised to the versions on
# restic's own main branch (no release carries them yet); each is pinned, `go get` adds their sums under GOSUMDB and
# the build then runs -mod=readonly. restic_bumps.sh fails the build on a bump that is not newer than the release's
# own version: drop it then (D-968). One bump goes past restic's main branch: golang.org/x/crypto v0.59.0, the first
# tag with the fix of GO-2026-5932 (x/crypto/openpgp; main is at v0.58.0), D-1039; it requires golang.org/x/text
# v0.44.0, so x/text goes there too (main: v0.43.0). x/sys and x/term rise with them by Go's version selection.
# restic's own test suite (`go test -short ./...`) runs on these modules before the binary is kept (D-1039), as an
# unprivileged user (restic's tests that make a file unreadable fail as root), without its FUSE mount tests (no FUSE
# in a build; RESTIC_TEST_FUSE=0, restic's own switch), without the four TestStdinFromCommand* tests (they run a
# `python` the Go image does not have; the box never uses --stdin-from-command) and without `go vet` (a lint, not a
# test), and without internal/selfupdate: it imports x/crypto/openpgp, which v0.59.0 removed (the GO-2026-5932 fix,
# D-1039), and only the build-tagged self-update command uses it, which this binary leaves out. A failure prints the
# failing tests and any compiler line.
# H-100: the database client tools of the server's major (the restore and the copy before it, run on the host by
# `trialbox restore`, restore and dump in this image). Their package source and its signing key are the db image's
# own base (the stage below, pinned by the same index digest as deploy/images.lock's db base); each package is
# installed at its exact version, held, and checked; the build stops on another major or on a base that is not
# Debian 13 (the source's suite). tests/unit/test_restore_from_the_host_h100.py holds the pins.
# Optional build secret "extra_ca" (PEM): trusted for the downloads only (corporate TLS proxies).
ARG GO_IMAGE=golang:1.26.11-bookworm@sha256:dc40a13b61304647ed7e5d581d246b86413dfc29d63c6d018310feb93cd98fc0
ARG BASE_IMAGE=trialbox-py:1.0.0
# hadolint ignore=DL3006
FROM ${GO_IMAGE} AS restic
ARG RESTIC_VERSION=0.19.1
ARG RESTIC_SHA256_SRC=bb9b1a19040744d26d8a79be029d4e6b189c45ccc9d8831d7fe367d3c33df725
ARG RESTIC_MODULE_BUMPS="github.com/go-jose/go-jose/v4@v4.1.6 github.com/klauspost/compress@v1.20.3 golang.org/x/crypto@v0.59.0 golang.org/x/net@v0.62.0 golang.org/x/text@v0.44.0 google.golang.org/grpc@v1.85.0"
ENV CGO_ENABLED=0 GOFLAGS="-mod=readonly -trimpath" GOTOOLCHAIN=local
WORKDIR /src
COPY deploy/docker/restic_bumps.sh /usr/local/bin/restic_bumps.sh
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    curl --fail --silent --show-error --location --retry 3 --retry-all-errors -o restic.tar.gz \
      "https://github.com/restic/restic/releases/download/v$RESTIC_VERSION/restic-$RESTIC_VERSION.tar.gz"; \
    echo "$RESTIC_SHA256_SRC  restic.tar.gz" | sha256sum -c -; \
    tar -xzf restic.tar.gz --strip-components=1; rm restic.tar.gz; \
    sh /usr/local/bin/restic_bumps.sh go.mod $RESTIC_MODULE_BUMPS; \
    GOFLAGS=-trimpath go get $RESTIC_MODULE_BUMPS; go mod verify; \
    go mod download; \
    useradd --create-home --uid 10001 gotest; chown -R gotest /src; \
    if ! runuser -u gotest -- env HOME=/home/gotest PATH="$PATH" GOFLAGS="$GOFLAGS" GOTOOLCHAIN=local CGO_ENABLED=0 \
         GOMODCACHE=/go/pkg/mod RESTIC_TEST_FUSE=0 go test -short -vet=off -count=1 -skip '^TestStdinFromCommand' \
         $(go list ./... | grep -v '/internal/selfupdate$') > /tmp/go-test.log 2>&1; then \
      grep -E '^(--- FAIL|FAIL|panic:|# |vet: )|\.go:[0-9]+(:[0-9]+)?:' /tmp/go-test.log | tail -80; exit 1; \
    fi; \
    tail -3 /tmp/go-test.log; \
    go build -ldflags "-s -w" -o /out/restic ./cmd/restic; \
    /out/restic version

FROM postgres:16-trixie@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f AS pgdg
RUN test -s /etc/apt/sources.list.d/pgdg.list && test -s /usr/local/share/keyrings/postgres.gpg.asc

# hadolint ignore=DL3006
FROM ${BASE_IMAGE}
ARG PG_CLIENT_MAJOR=16
ARG PG_CLIENT_VERSION=16.16-1.pgdg13+1
ARG LIBPQ_VERSION=19.0-2.pgdg13+1
ARG PG_CLIENT_COMMON_VERSION=297.pgdg13+1
COPY --from=restic /out/restic /usr/local/bin/restic
COPY --from=pgdg /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/pgdg.list
COPY --from=pgdg /usr/local/share/keyrings/postgres.gpg.asc /usr/local/share/keyrings/postgres.gpg.asc
USER root
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    set -eux; \
    . /etc/os-release; test "$VERSION_CODENAME" = trixie; \
    CA=/etc/ssl/certs/ca-certificates.crt; \
    if [ -s /run/secrets/extra_ca ]; then \
      sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/pgdg.list; \
      CA=/run/secrets/extra_ca; \
    fi; \
    apt-get -o Acquire::https::CAInfo="$CA" -o Dpkg::Use-Pty=0 update; \
    apt-get -o Acquire::https::CAInfo="$CA" -o Dpkg::Use-Pty=0 install -y --no-install-recommends \
      "postgresql-client-${PG_CLIENT_MAJOR}=${PG_CLIENT_VERSION}" \
      "libpq5=${LIBPQ_VERSION}" \
      "postgresql-client-common=${PG_CLIENT_COMMON_VERSION}"; \
    apt-mark hold "postgresql-client-${PG_CLIENT_MAJOR}" libpq5 postgresql-client-common; \
    test "$(dpkg-query -W -f '${Version}' "postgresql-client-${PG_CLIENT_MAJOR}")" = "${PG_CLIENT_VERSION}"; \
    test "$(dpkg-query -W -f '${Version}' libpq5)" = "${LIBPQ_VERSION}"; \
    test "$(dpkg-query -W -f '${Version}' postgresql-client-common)" = "${PG_CLIENT_COMMON_VERSION}"; \
    for tool in pg_restore pg_dump psql; do \
      case "$("$tool" --version)" in "$tool (PostgreSQL) ${PG_CLIENT_MAJOR}."*) ;; *) exit 1 ;; esac; \
    done; \
    rm -rf /var/lib/apt/lists/*
USER tb
RUN restic version
