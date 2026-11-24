#!/usr/bin/env bash
# The bench CI job container's start (card H-105): one single-use runner for one job, as the image's non-root user.
# The launcher gives the runner's one-job configuration on standard input (never an argument or a variable on the
# host); the runner is copied into this job's scratch folder (the image stays read-only), runs its one job and ends,
# and the container with it. Before the job's first step, the runner runs job_started.sh: the CI cards' check.
set -euo pipefail
umask 077
if [ "$(id -u)" = 0 ]; then echo "bench CI: the job container runs as its own user, never as root" >&2; exit 1; fi
IFS= read -r config || true
if [ -z "${config:-}" ]; then echo "bench CI: no runner configuration on standard input" >&2; exit 2; fi
mkdir -p /scratch/home /scratch/runner
cp -a /opt/runner/. /scratch/runner/
# the build tool that reads no proxy variable is told the proxy in its own settings (the launcher set the variables)
mkdir -p /scratch/home/.m2
cat > /scratch/home/.m2/settings.xml <<XML
<settings><proxies><proxy><id>tb-bench</id><active>true</active><protocol>https</protocol>
<host>tb-bench-proxy</host><port>3128</port><nonProxyHosts>localhost|127.0.0.1</nonProxyHosts></proxy></proxies></settings>
XML
export HOME=/scratch/home
export ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/tb-bench/job_started.sh
cd /scratch/runner
exec ./run.sh --jitconfig "$config"
