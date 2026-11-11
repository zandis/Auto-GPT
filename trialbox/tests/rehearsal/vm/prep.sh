#!/bin/bash
# One-time preparation of the rehearsal "VM" disk (runs INSIDE the Ubuntu 24.04 container, as root): what the GCE base
# image of tb-gpu-sim has before complete-run-vm.sh runs, and nothing of the script's own setup. Deliberately absent,
# because the script must bring them itself: git, python3-venv, PostgreSQL, tesseract, Node.js, uv.
#   * apt through the sandbox's HTTPS proxy (the VM uses the GCE mirrors), the proxy's CA trusted system-wide;
#   * curl, iproute2, python3 (the GCE image has them); nginx, which stands in for the nginx container;
#   * a docker0 address 172.17.0.1 (the door binds it): a dummy interface, else on lo (the container shares the host's
#     network namespace, so rehearse.sh removes it again);
#   * the two weight folders the pre-flight looks for (one synthetic config.json each, for the serving record);
#   * policy-rc.d: no service starts from apt (no systemd here; the VM's postgresql service is not used either).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 755 /usr/sbin/policy-rc.d
cat > /etc/apt/apt.conf.d/99rehearsal <<EOF
Acquire::https::Proxy "${HTTPS_PROXY:-}";
Acquire::https::CaInfo "/rehearsal/ca.crt";
Acquire::Retries "3";
EOF
sed -i 's#http://archive.ubuntu.com#https://archive.ubuntu.com#; s#http://security.ubuntu.com#https://security.ubuntu.com#' \
  /etc/apt/sources.list.d/ubuntu.sources
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl iproute2 python3 nginx procps xz-utils >/dev/null
cp /rehearsal/ca.crt /usr/local/share/ca-certificates/rehearsal-proxy.crt && update-ca-certificates >/dev/null
sed -i 's#^Acquire::https::CaInfo.*##' /etc/apt/apt.conf.d/99rehearsal   # the system store has the CA now
mkdir -p /models/hub/models--nvidia--Gemma-4-26B-A4B-NVFP4 /models/hub/models--cyankiwi--Qwen3.5-9B-AWQ-4bit /srv
for w in /models/hub/models--*; do  # one small synthetic file per snapshot: the serving record hashes it (T-119)
  mkdir -p "$w/snapshots/rehearsal" && printf '{"rehearsal": "%s"}\n' "${w##*/}" > "$w/snapshots/rehearsal/config.json"
done
if ! ip -4 -o addr show docker0 >/dev/null 2>&1; then
  if ip link add docker0 type dummy 2>/dev/null; then
    ip addr add 172.17.0.1/16 dev docker0 && ip link set docker0 up
  else
    ip -4 -o addr show lo | grep -q 172.17.0.1 || ip addr add 172.17.0.1/32 dev lo
  fi
fi
grep -q host.docker.internal /etc/hosts || echo "172.17.0.1 host.docker.internal" >> /etc/hosts
echo "prep done: $(. /etc/os-release; echo "$PRETTY_NAME"), python $(python3 -V 2>&1 | cut -d' ' -f2)"
