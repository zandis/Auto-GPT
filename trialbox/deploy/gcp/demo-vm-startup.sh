#!/bin/bash
# TrialBox click-through demo on the small CPU VM (trialbox-demo, e2-standard-4, asia-east1-b; D-111).
# Startup script: installs Docker, loads the demo image from the GCS object named in metadata "tb-demo-image"
# (gs://.../trialbox-demo.tar.gz, made by `make demo-bundle`), and runs it on :80 with the password from metadata
# "tb-demo-password". The image seeds and checks the whole step 1-4 flow on synthetic data (about 70 s), then serves
# the console. Nothing here creates or starts the VM: see docs/DEMO_VM.md.
exec > >(tee -a /var/log/tb-demo-startup.log /dev/ttyS0) 2>&1
set -x
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
IMG=$(curl -sf -H Metadata-Flavor:Google "$MD/tb-demo-image" || true)
{ set +x; } 2>/dev/null  # never trace the password into the serial log
PW=$(curl -sf -H Metadata-Flavor:Google "$MD/tb-demo-password" || true)
set -x
TOOL=$(curl -sf -H Metadata-Flavor:Google "$MD/tb-demo-tool" || echo demo)  # demo | public_e2e
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if [ -n "$IMG" ]; then
  gcloud storage cp "$IMG" /root/trialbox-demo.tar.gz && gunzip -c /root/trialbox-demo.tar.gz | docker load
fi
docker rm -f trialbox-demo 2>/dev/null
{ set +x; } 2>/dev/null
docker run -d --name trialbox-demo -p 80:8080 --restart unless-stopped \
  -e TB_DEMO_PASSWORD="$PW" -e TB_CONSOLE_SECURE_COOKIE=0 -e TB_DEMO_LANG="${TB_DEMO_LANG:-ja}" -e TB_DEMO_TOOL="$TOOL" trialbox-demo:step5
set -x
for i in $(seq 1 60); do curl -sf -o /dev/null http://127.0.0.1/login && break; sleep 5; done
docker logs trialbox-demo 2>&1 | grep -E "^(PASS|FAIL)|e2e_simple|console on|checks pass" | sed 's/^/TBD /'
echo DEMO-STARTUP-DONE
