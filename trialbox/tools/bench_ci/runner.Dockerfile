# The bench CI job image (card H-105; RUNBOOK §13 part, docs/runbook/13-bench-ci-runner.md). Built on the bench host by
# install.sh, as the tb-bench user, from a context folder that holds this file, the runner archive (its SHA-256 checked
# against the settings file first) and the files of tools/bench_ci/. Nothing in it is a secret.
# The base is the one Ubuntu 24.04 the rehearsal's host image pins (tools/rehearse_box/host.Dockerfile).
FROM ubuntu:24.04@sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8

ENV DEBIAN_FRONTEND=noninteractive
# the runner's own libraries; the tools the jobs call (make, git, the box's PostgreSQL major for tools/pglocal.py);
# a rootless engine for the engine and gpu profiles (the job's own, nested: the host's engine is never reachable)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git make maven python3 python3-venv util-linux jq unzip xz-utils zstd file \
      libicu74 libkrb5-3 liblttng-ust1t64 libssl3t64 zlib1g \
      postgresql-16 \
      podman uidmap fuse-overlayfs slirp4netns passt \
 && rm -rf /var/lib/apt/lists/*

# the job's own user (JOB_UID in launcher.py) and the id range its nested engine maps (inside the outer namespace)
RUN useradd --uid 1001 --user-group --create-home --shell /bin/bash runner \
 && echo "runner:10000:65536" > /etc/subuid && echo "runner:10000:65536" > /etc/subgid

COPY actions-runner.tar.gz /tmp/actions-runner.tar.gz
RUN mkdir -p /opt/runner && tar -xzf /tmp/actions-runner.tar.gz -C /opt/runner && rm /tmp/actions-runner.tar.gz \
 && chown -R root:root /opt/runner && chmod -R a+rX,go-w /opt/runner

COPY entrypoint.sh job_started.sh probe.sh gpu_check.py egress_proxy.py /opt/tb-bench/
RUN chmod 0755 /opt/tb-bench/*.sh && chmod 0644 /opt/tb-bench/*.py

ENV PATH=/usr/lib/postgresql/16/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
USER 1001:1001
WORKDIR /scratch
ENTRYPOINT ["/opt/tb-bench/entrypoint.sh"]
