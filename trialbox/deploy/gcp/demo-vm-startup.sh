#!/bin/bash
# TrialBox click-through demo on the small CPU VM (trialbox-demo, e2-standard-4, asia-east1-b; D-111).
# Startup script: installs Docker, loads the demo image from the GCS object named in metadata "tb-demo-image"
# (gs://.../trialbox-demo.tar.gz, made by `make demo-bundle`), and runs it on :80 with the password from metadata
# "tb-demo-password". The image seeds and checks the whole step 1-4 flow on synthetic data (about 70 s), then serves
# the console. Nothing here creates or starts the VM: see docs/RUNBOOK.md §11.
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
# D-138: the container is (re)created by one script, so tools/apply_update.sh --target demo can recreate it on a new
# image; the password stays in a root-only env file, never on a command line
install -d -m 0700 /etc/trialbox-demo
{ set +x; } 2>/dev/null
umask 077
printf 'TB_DEMO_PASSWORD=%s\nTB_CONSOLE_SECURE_COOKIE=0\nTB_DEMO_LANG=%s\nTB_DEMO_TOOL=%s\n' \
  "$PW" "${TB_DEMO_LANG:-ja}" "$TOOL" > /etc/trialbox-demo/demo.env
umask 022
set -x
cat > /etc/trialbox-demo/run.sh <<'EOS'
#!/bin/sh
exec docker run -d --name trialbox-demo -p 80:8080 --restart unless-stopped \
  --env-file /etc/trialbox-demo/demo.env "${1:-trialbox-demo:step5}"
EOS
chmod 0700 /etc/trialbox-demo/run.sh
sh /etc/trialbox-demo/run.sh trialbox-demo:step5
for i in $(seq 1 60); do curl -sf -o /dev/null http://127.0.0.1/login && break; sleep 5; done
docker logs trialbox-demo 2>&1 | grep -E "^(PASS|FAIL)|e2e_simple|console on|checks pass" | sed 's/^/TBD /'
echo DEMO-STARTUP-DONE
