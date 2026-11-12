# shellcheck shell=bash
# The GPU run's door over TLS (T-119, CR-048; D-150 "Not done": the key crossed plain HTTP and sat in the metadata).
# Sourced by deploy/gcp/complete-run.sh (and by tests/unit/test_cloud_door.py); defines functions only.
#
#   door_make DIR            a fresh door for one VM and run, all files 0600 in DIR:
#                              tb-key       the bearer key of the door and the two model servers
#                              door.key     the TLS private key of the VM's nginx (P-256, made here, never printed)
#                              door.crt     its self-signed certificate (CN and SAN "tb-door", 3 days): public, it
#                                           goes to the VM as metadata tb-door-cert
#                              door.pin     sha256 of the certificate's public key (curl --pinnedpubkey)
#                              door-secret.json  {"key", "tls_key"}: what the VM reads from Secret Manager
#   door_curl DIR HOST METHOD PATH [curl args...]
#                            one call to https://tb-door/tb/PATH on HOST: TLS only (--proto =https), the VM's own
#                            certificate as the only trust root AND its public key pinned, the key in a header read
#                            from a file (never argv), no proxy. Plain HTTP, another certificate or key: refused.
#   door_firewall_check PY VM_JSON RULES_JSON
#                            the firewall rules that reach the VM (its network, tags, service account): exit 1 and
#                            say which when tcp:80 is open to it from outside the VPC (the door is 443 only) or
#                            nothing opens tcp:443 from outside (internal and IAP-only rules do not count).
#
# The key and the TLS key reach the VM through Secret Manager (secret tb-gpu-door, one version per VM and run, made
# by setup-gcp.sh; the driver adds the version, the VM reads it with its own service account, the driver destroys
# it once the results are collected). Nothing secret is ever in the instance metadata.
# shellcheck disable=SC2034  # used by the scripts that source this file
DOOR_SECRET="tb-gpu-door"
DOOR_NAME="tb-door"
DOOR_PORT="${DOOR_PORT:-443}"

door_make() {
  local dir=$1 py=${PY:-python3}
  (
    umask 077
    "$py" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$dir/tb-key"
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3 -subj "/CN=$DOOR_NAME" \
      -addext "subjectAltName=DNS:$DOOR_NAME" -keyout "$dir/door.key" -out "$dir/door.crt" >/dev/null 2>&1
    openssl x509 -in "$dir/door.crt" -pubkey -noout | openssl pkey -pubin -outform der 2>/dev/null \
      | openssl dgst -sha256 -binary | openssl base64 -A > "$dir/door.pin"
    "$py" -c 'import json, sys; d = sys.argv[1]
json.dump({"key": open(d + "/tb-key").read().strip(), "tls_key": open(d + "/door.key").read()}, open(d + "/door-secret.json", "w"))' "$dir"
  )
  [ -s "$dir/door.crt" ] && [ -s "$dir/door.pin" ] && [ -s "$dir/door-secret.json" ]
}

door_curl() {
  local dir=$1 host=$2 m=$3 p=$4; shift 4
  [ -s "$dir/door.crt" ] && [ -s "$dir/door.pin" ] && [ -s "$dir/tb-key" ] || { echo "door: no door files in $dir" >&2; return 2; }
  # --noproxy: straight to the VM, as the plain-HTTP door went; an HTTPS proxy that re-signs would fail the pin anyway.
  # --connect-timeout (DOOR_CONNECT_TIMEOUT_S, 20 s; OD-10: a setting with a reason): a VM that answers connects in
  # well under a second; a dropped SYN must not hold a poll for curl's own 300 s (the driver's waits are wall-clock)
  curl -fsS --connect-timeout "${DOOR_CONNECT_TIMEOUT_S:-20}" --max-time 600 --noproxy '*' --proto =https --tlsv1.2 --cacert "$dir/door.crt" \
    --pinnedpubkey "sha256//$(cat "$dir/door.pin")" --resolve "$DOOR_NAME:$DOOR_PORT:$host" \
    -X "$m" -H @<(printf 'Authorization: Bearer %s\n' "$(cat "$dir/tb-key")") "https://$DOOR_NAME:$DOOR_PORT/tb/$p" "$@"
}

door_firewall_check() {
  "$1" - "$2" "$3" <<'PY'
import ipaddress, json, sys

vm = json.load(open(sys.argv[1]))
rules = json.load(open(sys.argv[2]))
net = (vm.get("networkInterfaces") or [{}])[0].get("network", "").rsplit("/", 1)[-1]
tags = set((vm.get("tags") or {}).get("items") or [])
sas = {s.get("email") for s in vm.get("serviceAccounts") or []}


def reaches(r):
    if r.get("disabled") or r.get("direction", "INGRESS") != "INGRESS" or not r.get("allowed"):
        return False
    if r.get("network", "").rsplit("/", 1)[-1] != net:
        return False
    if r.get("targetTags") and not tags & set(r["targetTags"]):
        return False
    return not (r.get("targetServiceAccounts") and not sas & set(r["targetServiceAccounts"]))


def public(r):  # from outside the VPC: a source range that is not private (IAP's range counts as inside)
    iap = ipaddress.ip_network("35.235.240.0/20")
    for c in r.get("sourceRanges") or []:
        n = ipaddress.ip_network(c, strict=False)
        if not (n.is_private or (n.version == 4 and n.subnet_of(iap))):
            return True
    return False


def opens(r, port):
    for a in r.get("allowed") or []:
        if a.get("IPProtocol") not in ("tcp", "all"):
            continue
        if not a.get("ports"):
            return True
        for spec in a["ports"]:
            lo, _, hi = spec.partition("-")
            if int(lo) <= port <= int(hi or lo):
                return True
    return False


bad = []
for r in rules:
    if reaches(r) and public(r) and opens(r, 80):
        bad.append(f"firewall rule {r['name']} opens tcp:80 to the VM (from {','.join(r.get('sourceRanges') or ['?'])}): "
                   f"the door is TLS on 443 only; close it: gcloud compute firewall-rules delete {r['name']} "
                   f"(or remove the VM's tag {','.join(sorted(tags & set(r.get('targetTags') or [])) or ['-'])})")
if not any(reaches(r) and public(r) and opens(r, 443) for r in rules):
    bad.append(f"no firewall rule opens tcp:443 to the VM on network {net or '?'}: gcloud compute firewall-rules create "
               f"tb-gpu-door --network {net or '<network>'} --direction INGRESS --allow tcp:443 "
               "--source-ranges <the driver's address>/32 --target-tags tb-gpu-door, then gcloud compute instances "
               "add-tags <vm> --zone <zone> --tags tb-gpu-door")
for b in bad:
    print(b, file=sys.stderr)
sys.exit(1 if bad else 0)
PY
}
