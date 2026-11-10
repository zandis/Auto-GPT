# The "box" of the box-install rehearsal (D-176): a clean Ubuntu 24.04 with what a site's IT installs before TrialBox
# (RUNBOOK §1 step 1, the debs of docs/handover/OFFLINE-MEDIA.md): Docker CLI and the compose plugin, nftables, cron
# and python3 with PyYAML and cryptography for the host tools. The Docker daemon is the rehearsal host's, through its
# socket (docker-outside-of-docker). No TrialBox file is in this image: they come from the offline media.
# The optional build secret "extra_ca" (PEM) is trusted by apt during the build only (corporate TLS proxies).
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eu; \
    if [ -f /run/secrets/extra_ca ]; then \
      install -m 0644 /run/secrets/extra_ca /tmp/extra-ca.pem; \
      sed -i 's#http://#https://#g' /etc/apt/sources.list.d/ubuntu.sources; \
      echo 'Acquire::https::CAInfo "/tmp/extra-ca.pem";' > /etc/apt/apt.conf.d/99-extra-ca; \
    fi; \
    apt-get update -q; \
    apt-get install -y -q --no-install-recommends docker.io docker-compose-v2 python3 python3-yaml \
      python3-cryptography nftables cron curl ca-certificates iproute2 xz-utils; \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99-extra-ca /tmp/extra-ca.pem
CMD ["sleep", "infinity"]
