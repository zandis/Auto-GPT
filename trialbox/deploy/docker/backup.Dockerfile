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
# restic's own test suite (`go test -short ./...`) runs on these modules before the binary is kept (D-1039).
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
    go test -short -count=1 ./...; \
    go build -ldflags "-s -w" -o /out/restic ./cmd/restic; \
    /out/restic version

# hadolint ignore=DL3006
FROM ${BASE_IMAGE}
COPY --from=restic /out/restic /usr/local/bin/restic
RUN restic version
