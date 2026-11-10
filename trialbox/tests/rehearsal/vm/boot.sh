#!/bin/bash
# One power-on of the rehearsal "VM" (inside the container, as root): what GCE does at boot, then the metadata's
# startup-script, unchanged, as google_metadata_script_runner runs it. The fake gcloud's `instances start` calls this.
#   * the serial console /dev/ttyS0: a FIFO copied into /rehearsal/s/console.log;
#   * docker's embedded DNS on 127.0.0.11 (dns_standin.py);
#   * PATH with the shims first (metadata server, docker, systemd, nvidia-smi); the proxy and its CA in the
#     environment, as the VM's network.
S=/rehearsal/s
H=/rehearsal/h
echo RUNNING > $S/status
[ -p /dev/ttyS0 ] || { rm -f /dev/ttyS0; mkfifo /dev/ttyS0; }
nohup bash -c "while :; do cat /dev/ttyS0 >> $S/console.log; done" >/dev/null 2>&1 &
nohup python3 $H/dns_standin.py >> $S/units/dns.log 2>&1 &
sleep 0.5
echo "=== power on $(date -u +%FT%TZ) run $(cat $S/metadata/tb-run-id 2>/dev/null) collect-only $(cat $S/metadata/tb-collect-only 2>/dev/null)" >> $S/console.log
cp $S/metadata/startup-script /var/run/google.startup.script
export PATH=$H/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
  PIP_CERT=/etc/ssl/certs/ca-certificates.crt NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt UV_NATIVE_TLS=1 \
  npm_config_https_proxy="${HTTPS_PROXY:-}" REHEARSE_LOAD_S="${REHEARSE_LOAD_S:-10}"
cd /
exec bash /var/run/google.startup.script > $S/startup-stdout.log 2>&1
