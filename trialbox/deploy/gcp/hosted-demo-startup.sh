#!/bin/bash
# TrialBox hosted click-through demo on the CPU VM trialbox-demo (e2-standard-4, asia-east1-b; D-111).
# Two sites from the one demo image, stub model, no GPU, behind Caddy with TLS on <ip>.sslip.io:
#   https://<ip>.sslip.io/        public-data site (tools.public_e2e: 268 real public notes, SIGIR + MedTxt)
#   https://roles-<ip>.sslip.io/  synthetic hospital (tools.demo: the e2e_simple flow on 5,000 synthetic patients)
# Code: a clone of the repo at metadata "tb-base" (a commit), plus the optional gzip+base64 patch in metadata
# "tb-patch" (local commits not yet on GitHub). Password: metadata "tb-admin-password" (never traced to the log).
# Cookies are not marked Secure (the demo seeds itself over in-process http); Caddy still serves https only.
# Re-runs on every boot; a restart reseeds both sites. Stop the VM when the demo is over (docs/RUNBOOK.md §11).
set -u
exec > >(tee -a /var/log/trialbox-setup.log /dev/ttyS0) 2>&1
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
MD=http://metadata.google.internal/computeMetadata/v1
A=$MD/instance/attributes
get() { curl -sf -H Metadata-Flavor:Google "$1"; }
IP=$(get $MD/instance/network-interfaces/0/access-configs/0/external-ip)
PW=$(get $A/tb-admin-password)
BASE=$(get $A/tb-base || echo master)
D=$(echo "$IP" | tr . -)
HOST="$D.sslip.io"; ROLEHOST="roles-$D.sslip.io"
step "startup $HOST base $BASE"
if ! command -v docker >/dev/null; then
  apt-get update -qq && apt-get install -y -qq docker.io git curl unzip >/dev/null && systemctl enable --now docker
fi
command -v unzip >/dev/null || apt-get install -y -qq unzip >/dev/null
# the older hosted stack (POC compose, role demo) is not part of this demo: stop it and keep it stopped
for c in $(docker ps -q); do
  n=$(docker inspect -f '{{.Name}}' "$c" | tr -d /)
  case "$n" in tb-public|tb-synth|trialbox-caddy) ;; *) docker update --restart=no "$c" >/dev/null; docker stop "$c" >/dev/null ;; esac
done
R=/opt/trialbox/demo-src
[ -d $R/.git ] || git clone -q https://github.com/zandis/Auto-GPT.git $R
cd $R && git fetch -q origin && git checkout -q -f "$BASE" && git clean -qfd -e .cache
if get $A/tb-patch > /tmp/tb-patch.b64; then
  base64 -d /tmp/tb-patch.b64 | gunzip > /tmp/tb.patch && git apply --whitespace=nowarn /tmp/tb.patch && step "patch applied ($(grep -c '^diff --git' /tmp/tb.patch) files)"
fi
cd $R/trialbox
# MedTxt (CC BY 4.0, NAIST) for the Japanese notes, and the one jar the compiler reads FHIRHelpers from
if [ ! -d ".cache/medtxt/Test collection" ]; then
  mkdir -p .cache/medtxt && curl -fsSL -o /tmp/medtxt.zip "https://sociocom.naist.jp/download/real-mednlp-test-collection/?wpdmdl=4864" \
    && (cd .cache/medtxt && unzip -q -o /tmp/medtxt.zip 'Test collection/*.xml' -x '__MACOSX/*')
fi
mkdir -p .cache/jvm/cql-translator/lib
[ -s .cache/jvm/cql-translator/lib/quick-5.4.0.jar ] || curl -fsSL -o .cache/jvm/cql-translator/lib/quick-5.4.0.jar \
  https://repo1.maven.org/maven2/org/cqframework/quick/5.4.0/quick-5.4.0.jar
step "building the demo image"
DOCKER_BUILDKIT=1 docker build -q -f demo/Dockerfile -t trialbox-demo:hosted . || step "BUILD FAILED"
docker rm -f tb-public tb-synth >/dev/null 2>&1
{ set +x; } 2>/dev/null
docker run -d --name tb-public --restart unless-stopped -p 127.0.0.1:8081:8080 -e TB_DEMO_PASSWORD="$PW" \
  -e TB_CONSOLE_SECURE_COOKIE=0 -e TB_DEMO_TOOL=public_e2e -e TB_DEMO_LANG=ja trialbox-demo:hosted >/dev/null
docker run -d --name tb-synth --restart unless-stopped -p 127.0.0.1:8082:8080 -e TB_DEMO_PASSWORD="$PW" \
  -e TB_CONSOLE_SECURE_COOKIE=0 -e TB_DEMO_TOOL=demo -e TB_DEMO_LANG=ja trialbox-demo:hosted >/dev/null
step "caddy"
mkdir -p /opt/trialbox/caddy
cat > /opt/trialbox/caddy/Caddyfile <<CF
$HOST {
  reverse_proxy 127.0.0.1:8081
}
$ROLEHOST {
  reverse_proxy 127.0.0.1:8082
}
CF
docker rm -f trialbox-caddy >/dev/null 2>&1
docker run -d --name trialbox-caddy --restart unless-stopped --network host \
  -v /opt/trialbox/caddy/Caddyfile:/etc/caddy/Caddyfile:ro -v trialbox-caddy-data:/data caddy:2 >/dev/null
for p in 8081 8082; do
  for i in $(seq 1 60); do curl -sf -o /dev/null http://127.0.0.1:$p/login && break; sleep 5; done
done
docker logs tb-public 2>&1 | grep -E "checks pass" | sed 's/^/TBD public /'
docker logs tb-synth 2>&1 | grep -E "^(PASS|FAIL)|e2e_simple" | tail -3 | sed 's/^/TBD synth /'
docker ps --format '{{.Names}} {{.Status}}'
step "ready https://$HOST roles https://$ROLEHOST"
echo DEMO-STARTUP-DONE
