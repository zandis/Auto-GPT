#!/usr/bin/env bash
# The bench CI job container's start (card H-105): one single-use runner for one job, as the image's non-root user.
# The root mint step wrote the runner's one-job configuration into this job's scratch folder (runner.jit, mode 0600):
# it is read, deleted, and unpacked into the runner's own files, never passed as an argument (the review's F9). The
# runner is copied into the scratch folder (the image stays read-only), runs its one job and ends, and the container
# with it. Before the job's first step the runner runs job_started.sh: the host's gate, then the CI cards' check.
set -euo pipefail
umask 077
if [ "$(id -u)" = 0 ]; then echo "bench CI: the job container runs as its own user, never as root" >&2; exit 1; fi
JIT=/scratch/.tb-bench/runner.jit
[ -s "$JIT" ] || { echo "bench CI: no one-job runner configuration in the job's folder" >&2; exit 2; }
mkdir -p /scratch/home /scratch/runner /scratch/tmp
cp -a /opt/runner/. /scratch/runner/
python3 -I /opt/tb-bench/unpack_jit.py "$JIT" /scratch/runner || { rm -f "$JIT"; exit 2; }
rm -f "$JIT"
proxy_host="${HTTPS_PROXY#http://}"
proxy_host="${proxy_host%%:*}"
# the build tool that reads no proxy variable is told the proxy in its own settings (the launcher set the variables)
mkdir -p /scratch/home/.m2
cat > /scratch/home/.m2/settings.xml <<XML
<settings><proxies><proxy><id>tb-bench</id><active>true</active><protocol>https</protocol>
<host>${proxy_host}</host><port>3128</port><nonProxyHosts>localhost|127.0.0.1</nonProxyHosts></proxy></proxies></settings>
XML
if [ "${BENCH_PROFILE:-cpu}" != cpu ]; then
  # the nested rootless engine: no fuse device (F5), so its storage is plain folders under the job's home
  mkdir -p /scratch/home/.config/containers
  printf '[storage]\ndriver = "vfs"\n' > /scratch/home/.config/containers/storage.conf
fi
export HOME=/scratch/home
export ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/tb-bench/job_started.sh
cd /scratch/runner
exec ./run.sh
