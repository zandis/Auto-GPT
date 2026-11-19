# The "box" of the box-install rehearsal (D-176): a clean Ubuntu 24.04 with what a site's IT installs before TrialBox
# (RUNBOOK §1 step 1, the debs of docs/handover/OFFLINE-MEDIA.md): Docker CLI and the compose plugin, nftables, cron
# and python3 with PyYAML and cryptography for the host tools; openssl, which Ubuntu Server has and the base image
# lacks (RUNBOOK §1's first command checks the bootstrap's signature with it, D-996). The Docker daemon is the rehearsal host's, through its
# socket (docker-outside-of-docker). No TrialBox file is in this image: they come from the offline media.
# The optional build secret "extra_ca" (PEM) is trusted by apt during the build only (corporate TLS proxies).
# H-54: the base is pinned by digest (the multi-arch index of ubuntu:24.04, read 2026-11-19), and every apt fetch
# is bounded and retried: a mirror that does not answer fails one fetch in 20 s and apt tries again (5 times, with
# backoff), and an index that could not be read fails `apt-get update` instead of leaving "Unable to locate package"
# for the install (train 98: archive.ubuntu.com:80 refused for 500 s in one leg, the indexes failed in the other).
# The rehearsal caches the built image on this file's hash (rehearse.sh TB_REHEARSE_HOST_CACHE, the workflow's cache).
FROM ubuntu:24.04@sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8
ARG DEBIAN_FRONTEND=noninteractive
# D-1343: DL3008, the packages are what a site's IT installs from Ubuntu 24.04 (RUNBOOK §1 step 1) at the version
# of the digest-pinned base's suite, as on the box; the rehearsal is not a shipped image.
# hadolint ignore=DL3008
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eu; \
    if [ -f /run/secrets/extra_ca ]; then \
      install -m 0644 /run/secrets/extra_ca /tmp/extra-ca.pem; \
      sed -i 's#http://#https://#g' /etc/apt/sources.list.d/ubuntu.sources; \
      echo 'Acquire::https::CAInfo "/tmp/extra-ca.pem";' > /etc/apt/apt.conf.d/99-extra-ca; \
    fi; \
    printf '%s\n' 'Acquire::Retries "5";' 'Acquire::Retries::Delay "true";' 'Acquire::http::Timeout "20";' \
      'Acquire::https::Timeout "20";' > /etc/apt/apt.conf.d/99-tb-bounded-fetch; \
    apt-get update -q --error-on=any; \
    apt-get install -y -q --no-install-recommends docker.io docker-compose-v2 python3 python3-yaml \
      python3-cryptography nftables cron curl ca-certificates iproute2 xz-utils openssl; \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99-extra-ca /etc/apt/apt.conf.d/99-tb-bounded-fetch /tmp/extra-ca.pem
CMD ["sleep", "infinity"]
