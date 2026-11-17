#!/usr/bin/env bash
# Box-install rehearsal (D-176), the box side: runs inside the clean Ubuntu 24.04 container that tools/rehearse_box/
# rehearse.sh starts, one phase per call, and exits non-zero when the phase's assertion fails. Every TrialBox file it
# uses comes from the offline media in $TB_RH_MEDIA (the release tree, the signed bundle, the vendor key).
#
#   box.sh wsl2|media-negative|install|reinstall|doctor|served|offline|console|screen|after-restart|restic-restore|terminology|wrong-name|missing-key
#
# Environment (set by rehearse.sh): TB_RH_DIR (work dir, the same path on the Docker host), TB_RH_MEDIA (the media
# folder), TB_RH_BUNDLE (the bundle file name), TB_RH_BOX (where the box is installed: the site's /opt/trialbox).
set -uo pipefail
PHASE="${1:?phase}"
W="${TB_RH_DIR:?}"; MEDIA="${TB_RH_MEDIA:?}"; BOX="${TB_RH_BOX:?}"; BUNDLE="$MEDIA/linux/${TB_RH_BUNDLE:?}"
SHIMS="$W/run/shims"
export PATH="$SHIMS:$PATH"   # the GPU driver stand-in (one RTX PRO 6000), Windows interop for the WSL2 checks
fail() { echo "REHEARSAL FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }
dc() { (cd "$BOX" && docker compose --project-directory deploy "$@"); }   # COMPOSE_FILE comes from deploy/.env
envget() { sed -n "s/^$1=//p" "$BOX/deploy/.env" | tail -1; }
envset() { sed -i "/^$1=/d" "$BOX/deploy/.env"; [ -z "${2+x}" ] || printf '%s=%s\n' "$1" "$2" >> "$BOX/deploy/.env"; }
IMAGE_PY="trialbox-py:1.0.0"

# install_box: the real installer as a site runs it (--rehearsal). The rehearsal box is VALIDATION (D-887, the
# integrator's (i)): D3 stays on the box, so SCREEN reaches the pinned builds; VALIDATION seals the site keys and
# FAILs what only a site's host has, so every rehearsal runs as a validation run on a plain VM does: no TPM, the
# passphrase KEK, TB_HOST_PROFILE=poc. The validation variant adds a root-owned deploy/site and the second install
install_box() (
  cd "$BOX" || exit 1
  # the host's zone is the site's, as a site's IT sets it (doctor's site_tz, D-315); this host has no timedatectl
  tz="$(sed -n "s/^tz: *['\"]\{0,1\}\([A-Za-z0-9_+\/-]*\).*/\1/p" tools/rehearse_box/site_answers.yaml | head -1)"
  [ -n "$tz" ] && printf '%s\n' "$tz" > /etc/timezone
  if [ "${TB_RH_VARIANT:-test}" = validation ]; then
    # a site's IT makes deploy/site as root; the pin step's container must still write there (I-4, D-835)
    install -d -m 0755 deploy/site && chown -R root:root deploy/site
  fi
  # no TPM on this host: the passphrase back end, a throwaway synthetic passphrase (never printed, kept 0600)
  [ -s "$W/vendor/kek-pass" ] || (umask 077 && head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$W/vendor/kek-pass")
  TB_KEK_PASSPHRASE="$(cat "$W/vendor/kek-pass")"
  export TB_HOST_PROFILE=poc TB_KEK_BACKEND=passphrase TB_KEK_PASSPHRASE
  TB_TLS_CHECK_ADDR="${TB_RH_TLS_ADDR:-127.0.0.1}" TB_COMPOSE_OVERRIDE="$BOX/tools/rehearse_box/standins.yml" TB_INSTALL_UP_TIMEOUT=900 \
    deploy/install.sh "$BUNDLE" --tier large --answers "$BOX/tools/rehearse_box/site_answers.yaml" --ctgov offline --rehearsal --yes
)

unpack_release() {  # the release tree from the media into a fresh folder: what the site copies to /opt/trialbox
  local to="$1"
  rm -rf "$to" && mkdir -p "$to" && tar -xf "$MEDIA/trialbox-release.tar" -C "$to" || fail "cannot unpack the release"
  install -d "$to/deploy/keys"
}

# doctor <args...>: trialbox doctor where the gateway's model network is (as install.sh runs it), with the box's env
doctor() {  # the model key as the gateway reads it: the key file only (D-437, D-450), not deploy/.env's copy
  # D-887: what the host check hands the doctor too: the release tree the deploy/ links point into (D-570), the site
  # keys where the services read them, and the KEK when the box has one
  local more=() sec
  [ -L "$BOX/current" ] && more+=(-v "$(readlink -f "$BOX/current"):/app/current:ro")
  sec="$(docker volume inspect -f '{{.Mountpoint}}' trialbox_tb-secrets 2>/dev/null)"
  [ -n "$sec" ] && [ -d "$sec" ] && more+=(-v "$sec:/run/secrets/trialbox:ro")
  [ -d /run/trialbox ] && more+=(-v /run/trialbox:/run/trialbox:ro)
  # D-991: the loaded code systems, read-only, as the host check gives them
  docker volume inspect trialbox_tb-terminology >/dev/null 2>&1 && more+=(-v trialbox_tb-terminology:/data/terminology:ro)
  # ...and every compose file of COMPOSE_FILE outside deploy/ (the stand-ins) at its own path, as the host check does
  local cf; local IFS=:
  for cf in $(sed -n 's/^COMPOSE_FILE=//p' "$BOX/deploy/.env" | tail -1); do
    case "$cf" in "$BOX/deploy/"*) ;; /*) [ -f "$cf" ] && more+=(-v "$cf:$cf:ro") ;; esac
  done
  unset IFS
  docker run --rm --network trialbox-model-net --env-file "$BOX/deploy/.env" -v "$BOX/deploy:/app/deploy:ro" \
    ${more[@]+"${more[@]}"} -e TB_LLM_API_KEY= -e TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key \
    --user 0:0 "$IMAGE_PY" python -m tools.trialbox doctor --settings /app/deploy/settings.yaml \
    --env-file /app/deploy/.env "$@"   # D-887: as the host check gives it (db_passwords, chartno_rule read the box)
}

# in_svc <service> <python source on stdin>: run Python inside a box service as that service (its token, its networks)
in_svc() { dc exec -T "$1" python -; }

wait_healthy() {  # every running box container healthy, within $1 seconds
  local deadline=$((SECONDS + ${1:-600})) bad
  while :; do
    bad="$(dc ps --format '{{.Service}} {{.State}} {{.Health}}' | awk '$2 != "running" || ($3 != "" && $3 != "healthy")')"
    n="$(dc ps -q | wc -l)"
    [ -z "$bad" ] && [ "$n" -ge 12 ] && { ok "$n containers running and healthy"; return 0; }
    [ "$SECONDS" -ge "$deadline" ] && { dc ps; fail "not healthy within ${1:-600} s: $bad"; }
    sleep 5
  done
}

standin_stats() {  # the stand-ins' answer counts, asked inside each stand-in (model-guard passes no /standin path)
  local h out="{"
  for h in llm-service llm-verifier; do
    out="$out\"$h\": $(in_svc "$h" <<'EOF'
import json, os, urllib.request
req = urllib.request.Request("http://127.0.0.1:8000/standin/stats",
                             headers={"Authorization": f"Bearer {os.environ['VLLM_API_KEY']}"})
print(json.dumps(json.load(urllib.request.urlopen(req, timeout=10))))
EOF
)" || return 1
    [ "$h" = llm-service ] && out="$out, "
  done
  echo "$out}"
}

# gateway_probe <expect: ok|refused>: one judge call per pinned build through the gateway, as the orchestrator
gateway_probe() {
  in_svc orchestrator <<EOF
import sys
from tb_common.llm import load_prompt, render
from tb_contracts import inline_schema
from tb_llm import CallLabels, GatewayClient, GatewayError, json_schema_format

expect = "$1"
p = load_prompt("judge")
body_vars = {"criterion_text": "Age >= 18 years", "note_question": "Is the patient an adult?", "index_date": "2026-10-05",
             "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "Synthetic note: 54-year-old outpatient."}]}
bad = 0
for alias in ("j-workhorse", "v-verifier"):
    # D3 as a SCREEN's note question: on topology A in PRODUCTION the orchestrator may send it without a study step
    # outside DEV and TEST the gateway needs the registered prompt's sha256 (D-300), as the orchestrator sends it
    labels = CallLabels("D3", "screening", "REHEARSAL", "s3_note_judgement", "judge", f"judge@{p.meta.version}",
                        prompt_sha=p.sha256)
    try:
        res = GatewayClient("http://gateway:8020/v1", "orchestrator", model=alias).chat(
            render(p, body_vars), labels,
            response_format=json_schema_format("judge", inline_schema(p.meta.output_schema)), max_tokens=p.meta.max_tokens)
        print(f"{alias}: answered by {res.model} (build sha {res.build_sha[:12]})")
        bad += expect != "ok"
    except GatewayError as e:
        policy = "no_route" in str(e) or "(403" in str(e)  # the gateway's own policy, not the model server
        print(f"{alias}: {'policy-refused' if policy else 'refused'}: {e}")
        bad += expect == "ok" or policy
sys.exit(1 if bad else 0)
EOF
}

case "$PHASE" in
# ------------------------------------------------------------------------------------------------ Windows / WSL2
wsl2)
  # The Windows side (preflight.ps1, BitLocker, the WSL import) cannot run on Linux. The WSL2 side runs for real
  # against a /proc that looks like a WSL2 kernel with systemd, and Windows interop answered by the cmd.exe shim.
  unpack_release "$W/wsl"
  P="$W/wsl-proc"; rm -rf "$P"; mkdir -p "$P/sys/kernel" "$P/1"
  echo "6.6.87.2-microsoft-standard-WSL2" > "$P/sys/kernel/osrelease"
  printf 'processor\t: 0\nflags\t\t: fpu vme hypervisor\n' > "$P/cpuinfo"
  echo "MemTotal:       134217728 kB" > "$P/meminfo"
  echo systemd > "$P/1/comm"
  out="$(TB_PREFLIGHT_PROC="$P" TB_MIN_FREE_GB=1 bash "$W/wsl/deploy/windows/preflight.sh" "$W/wsl" 2>&1)"; rc=$?
  echo "$out"
  [ "$rc" = 0 ] && echo "$out" | grep -q "all checks passed" || fail "WSL2 preflight on a WSL2-like host did not pass"
  ok "WSL2 preflight: every line PASS (WSL2 kernel, Windows build via interop, GPU via nvidia-smi, disk, memory, systemd)"
  out="$(TB_MIN_FREE_GB=1 bash "$W/wsl/deploy/windows/preflight.sh" "$W/wsl" 2>&1)"; rc=$?
  echo "$out"
  [ "$rc" != 0 ] && echo "$out" | grep -q "^FAIL  WSL2" || fail "the WSL2 preflight passed on a plain Linux container"
  ok "the same preflight on this plain Linux container FAILs the WSL2 line, as it must"
  rm -rf "$W/wsl" "$P"
  ;;

# ------------------------------------------------------------------------------------------------ negative: media
media-negative)
  NEG="$W/box-neg"
  unpack_release "$NEG"
  cp "$MEDIA/linux/vendor_ed25519.pub" "$NEG/deploy/keys/"
  cd "$NEG" || exit 1
  out="$(deploy/install.sh /media/usb-not-mounted/linux/trialbox-missing.tar --tier large --yes 2>&1)"; rc=$?
  echo "$out"
  [ "$rc" != 0 ] && echo "$out" | grep -q "no such bundle" || fail "a missing bundle did not stop the installer clearly"
  [ ! -e deploy/.env ] && [ ! -e deploy/settings.yaml ] || fail "the installer wrote settings without a bundle"
  ok "missing offline media: exit $rc, 'no such bundle', nothing written"
  # a bundle that is not the vendor's (a tar with a forged manifest and no valid signature)
  mkdir -p "$W/forged/files" && echo '{"bundle_id": "forged", "files": []}' > "$W/forged/manifest.json"
  tar -cf "$W/forged.tar" -C "$W/forged" manifest.json files
  out="$(deploy/install.sh "$W/forged.tar" --tier large --yes 2>&1)"; rc=$?
  echo "$out" | tail -5
  [ "$rc" != 0 ] && echo "$out" | grep -q "not a valid signed TrialBox release" || fail "a forged bundle was not refused"
  [ ! -e deploy/.env ] || fail "the installer wrote settings for a forged bundle"
  ok "forged media: exit $rc, 'not a valid signed TrialBox release; nothing was changed'"
  # the vendor key missing from the box (it comes out of band, and on the media)
  rm -f deploy/keys/vendor_ed25519.pub
  out="$(deploy/install.sh "$BUNDLE" --tier large --yes 2>&1)"; rc=$?
  echo "$out" | tail -3
  [ "$rc" != 0 ] && echo "$out" | grep -q "vendor public key missing" || fail "a missing vendor key was not refused"
  ok "missing vendor key: exit $rc, 'vendor public key missing'"
  cd / && rm -rf "$NEG" "$W/forged" "$W/forged.tar"
  ;;

# ------------------------------------------------------------------------------------------------ install
install)
  unpack_release "$BOX"
  cp "$MEDIA/linux/vendor_ed25519.pub" "$BOX/deploy/keys/"
  (cd "$MEDIA" && sha256sum -c SHA256SUMS >/dev/null) || fail "the media's SHA256SUMS do not match"
  ok "media checksums match ($(wc -l < "$MEDIA/SHA256SUMS") files)"
  cd "$BOX" || exit 1
  # T-632: the site's feed folder on the host (a copy of the synthetic export), never the fixture in the release
  install -d deploy/site && rm -rf deploy/site/feed-a && cp -r tests/fixtures/synthetic_patients/site-a deploy/site/feed-a \
    || fail "cannot stage the feed folder"
  install_box || fail "deploy/install.sh failed"
  grep -q '^TB_LLM_API_KEY=.\{32,\}' deploy/.env || fail "install.sh made no model-server key"
  grep -q '^VLLM_API_KEY=.\{32,\}' deploy/secrets/model/vllm.env || fail "no key in the vLLM servers' env file (D-450)"
  [ -f deploy/site/mapping/tw_core/rehearsal_a.yaml ] || fail "the site mapping is not in deploy/site/mapping"
  grep -q '^TB_SOURCE_DIR=./site/feed-a' deploy/.env || fail "the wizard wrote no feed folder"
  grep -q '^TB_TLS_HOSTNAME=trialbox.hospa.test' deploy/.env || fail "TLS is not on"
  ok "site inputs: mapping in deploy/site/mapping (not the image), feed folder mounted, TLS on"
  wait_healthy 300
  ;;

# ------------------------------------------------------------------------------------------------ reinstall
reinstall)
  # D-887 (I-2, D-833): the same bundle installed again on the box it made: the installer continues, the keys stay
  sec="$(docker volume inspect -f '{{.Mountpoint}}' trialbox_tb-secrets)" || fail "no secrets volume"
  [ -f "$sec/kek.json" ] || fail "the first install sealed no keys (no kek.json in $sec)"
  before="$(sha256sum "$sec/kek.json" | cut -d' ' -f1)"
  ok "first install: keys sealed under the passphrase KEK (kek.json)"
  install_box || fail "the second install of the same bundle failed"
  [ "$(sha256sum "$sec/kek.json" | cut -d' ' -f1)" = "$before" ] || fail "the second install replaced the KEK"
  [ "$(stat -c %u "$BOX/deploy/site")" = 0 ] || fail "deploy/site is no longer root's"
  grep -q '^TB_HOST_PROFILE=poc' "$BOX/deploy/.env" || fail "the poc host profile was not kept"
  ok "second install of the same bundle: continued, the KEK kept, deploy/site root's, host profile poc"
  wait_healthy 600
  # D-888 (lane G's box): a start without install.sh (the systemd unit, an update) mounts the site's settings too
  sh "$BOX/deploy/settings_guard.sh" "$BOX/deploy" || fail "the settings guard refused the installed box"
  dc up -d --force-recreate --no-deps adapter >/dev/null || fail "the adapter did not start without the installer"
  src="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/trialbox/settings.yaml"}}{{.Source}}{{end}}{{end}}' \
    "$(dc ps -q adapter)")"
  case "$src" in */deploy/settings.yaml) ok "restarted without the installer: the adapter mounts $src" ;;
    *) fail "restarted without the installer, the adapter mounts ${src:-nothing} at /etc/trialbox/settings.yaml, not deploy/settings.yaml" ;; esac
  wait_healthy 600
  ;;

# ------------------------------------------------------------------------------------------------ doctor
doctor)
  # the site's TLS proxy in front of the console (RUNBOOK §9) is not part of the rehearsal; the doctor's secure-cookie
  # check needs it in PRODUCTION, so the rehearsal sets what such a site sets
  grep -q '^TB_CONSOLE_SECURE_COOKIE=1' "$BOX/deploy/.env" || { envset TB_CONSOLE_SECURE_COOKIE 1; dc up -d --wait console; }
  out="$(doctor --live 2>&1)"; rc=$?
  echo "$out"
  # D-887: the rehearsal box is VALIDATION, which FAILs what only a site's host has; these, and nothing else, are
  # said as not reached by a rehearsal (no NTP in a container, no systemd timer, no hospital share for the anchor)
  host_only='^FAIL  (clock|ops_runner|audit_heads) '
  echo "$out" | grep -E "$host_only" | sed 's/^FAIL /not reached by a rehearsal (a site host has it): /'
  other="$(echo "$out" | grep -E '^FAIL ' | grep -Ev "$host_only")"
  [ -z "$other" ] || fail "trialbox doctor --live failed: $other"
  { [ "$rc" = 0 ] && echo "$out" | grep -q "^doctor passed"; } || echo "$out" | grep -qE "$host_only" \
    || fail "trialbox doctor --live did not pass"
  echo "$out" | grep -q "^WARN  rehearsal .*REHEARSAL BOX: placeholder models, synthetic data only" \
    || fail "the doctor does not carry the standing REHEARSAL BOX line"
  echo "$out" | grep -q "^PASS  serving" || fail "the live serving check did not PASS"
  echo "$out" | grep -q "^PASS  registry_pins" || fail "registry_pins did not PASS"
  # D-887: the pins are the media's placeholders, and the doctor says so where it shows them
  echo "$out" | grep -q "^PASS  serving.*rehearsal placeholder" || fail "the serving line does not name the rehearsal placeholder"
  ok "trialbox doctor --live: passed"
  ;;

# ------------------------------------------------------------------------------------------------ served names
served)
  stats="$(standin_stats)" || fail "cannot ask the stand-ins"
  echo "stand-ins: $stats"
  python3 - "$BOX/deploy/site/registry.site.yaml" "$stats" "$(envget JUDGE_MODEL)" "$(envget VERIFIER_MODEL)" <<'EOF' || fail "pins and served names differ"
import json, os, sys, yaml
stats = json.loads(sys.argv[2])
if not os.path.exists(sys.argv[1]):
    # D-887: the media's placeholder weights are never the release's, so a rehearsal box pins nothing (install.sh
    # says so); the stand-ins must serve exactly the names the gateway calls (JUDGE_MODEL, VERIFIER_MODEL)
    for host, name in (("llm-service", sys.argv[3]), ("llm-verifier", sys.argv[4])):
        assert name and stats[host]["served"] == [name], f"{host} serves {stats[host]['served']}, the gateway calls {name!r}"
        print(f"ok: {host} serves exactly {name!r}, the name the gateway calls (no pin on a rehearsal box)")
    sys.exit(0)
pins = yaml.safe_load(open(sys.argv[1]))["builds"]
want = {"serving": ("llm-service", "gemma-4-26b-a4b-it"), "verifier": ("llm-verifier", "qwen3.5-9b")}
for build, b in sorted(pins.items()):
    for ep, name in (b.get("served") or {}).items():
        host, default = want[ep]
        served = stats[host]["served"]
        assert served == [name], f"{build}: pinned {name!r} on {ep}, {host} serves {served}"
        # D-887: the media's placeholder weights, pinned as candidate on a rehearsal box only: not a model
        trust = (b.get("weights") or {}).get("trust")
        assert trust == "rehearsal_placeholder" and b.get("status") == "candidate" and b.get("sha256"), \
            f"{build}: not a rehearsal placeholder candidate pin (trust {trust!r}, status {b.get('status')!r})"
        print(f"ok: {build} pinned {name!r} ({b['sha256'][:12]}, rehearsal placeholder, candidate) = what {host} serves")
assert {ep for b in pins.values() for ep in (b.get("served") or {})} == {"serving", "verifier"}, "a pair member is missing"
EOF
  ;;

# ------------------------------------------------------------------------------------------------ offline media
offline)
  # 1. images: every running box container runs an image the bundle loaded (rehearse.sh removed them all before the
  #    install, by id), the third-party ones too, and the daemon pulled nothing. A service image (release.json of the
  #    signed bundle: `runs: service`, or no `runs`) must be run by a box container; a job image (`runs: job`, D-968:
  #    the nightly backup's, a one-off container) must be on the box with exactly the bundle's image id
  python3 - "$W/vendor/bundle-images.txt" "$W/logs/image-events.log" "$BUNDLE" <<'EOF' || fail "an image is not the bundle's"
import json, subprocess, sys, tarfile
def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, check=True).stdout
bundle = dict(line.split() for line in open(sys.argv[1]))  # vendor reference -> image id
ids = set(bundle.values())
with tarfile.open(sys.argv[3]) as tf:
    rel = json.load(tf.extractfile("release.json"))
jobs = {img["source"] for img in rel["images"].values() if img.get("runs") == "job"}
cts = sh("docker", "ps", "-q", "--filter", "label=com.docker.compose.project=trialbox").split()
used = {}
for c in json.loads(sh("docker", "inspect", *cts)):
    svc = c["Config"]["Labels"]["com.docker.compose.service"]
    assert c["Image"] in ids, f"{svc}: runs {c['Config']['Image']} = {c['Image']}, not an image of the bundle"
    used.setdefault(c["Image"], []).append(svc)
for ref, iid in sorted(bundle.items()):
    if ref in jobs and iid not in used:
        r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True)
        assert r.returncode == 0, f"{ref}: a job image of the bundle, not on the box: {r.stderr.strip()}"
        got = r.stdout.strip()
        assert got == iid, f"{ref}: a job image of the bundle, but the box has {got}, not the bundle's {iid}"
        print(f"ok: job image {ref} = bundle image {iid[:19]}, loaded from the media (release.json: runs: job)")
        continue
    assert iid in used, f"{ref}: in the bundle, but no box container runs it"
    kind = "TrialBox" if ref.startswith("trialbox-") else "third-party"
    print(f"ok: {kind} {ref} = bundle image {iid[:19]}, run by {', '.join(sorted(used[iid]))}")
pulls = [ln for ln in open(sys.argv[2]) if ln.startswith("pull ")]
assert not pulls, f"the daemon pulled: {pulls}"
print(f"ok: {len(cts)} containers, every image from the media; no pull since the images were removed")
EOF
  # on a store without digests (overlay2) the digest pins point at the bundle's image ids (tools/image_pins.py)
  grep -E '^(POSTGRES|HAPI)_IMAGE=' "$BOX/deploy/.env" | sed 's/^/ok: pinned by image id: /' || ok "digest references resolved by the image store itself"
  # 2. CQL translator jars: what the criteria-compiler runs is byte for byte the vendor's set, and it translates
  dc exec -T criteria-compiler sh -c 'cd "$TB_CQL_TRANSLATOR_LIB" && sha256sum *.jar' | sort -k2 > "$W/box-cql-jars.sha256"
  diff "$W/vendor/cql-jars.sha256" "$W/box-cql-jars.sha256" || fail "the CQL jars in the box differ from the media's"
  ok "CQL translator: $(wc -l < "$W/box-cql-jars.sha256") jars, sha256 equal to the vendor's"
  in_svc criteria-compiler <<'EOF' || fail "CQL did not translate on the box"
from criteria_compiler.compile_cql.translator import Translator, available
assert available(), "no CQL translator jars or no java in criteria-compiler"
out = Translator().translate({"Rehearsal": "library Rehearsal version '1.0.0'\ndefine \"Two\": 1 + 1\n"})
assert '"Two"' in out.elm["Rehearsal"], out
print("ok: CQL -> ELM translated inside criteria-compiler with the media's jars")
EOF
  # 3. reference data: the pack of the bundle is loaded in the box's database, and ClinicalTrials.gov is offline
  want="$(cat "$W/vendor/refdata-pack-id.txt")"
  st="$(dc exec -T criteria-compiler python -m tb_common.refdata status)" || fail "refdata status failed"
  echo "$st"
  echo "$st" | grep -q "$want" || fail "the reference data pack $want of the media is not loaded"
  [ "$(envget TB_CTGOV_MODE)" = offline ] || fail "ClinicalTrials.gov is not offline"
  [ -z "$(ls "$BOX/deploy/refdata/pending/" 2>/dev/null)" ] || fail "a reference data pack is still pending"
  ok "reference data $want from the media loaded; ClinicalTrials.gov offline"
  ;;

# ------------------------------------------------------------------------------------------------ egress override
egress-override)
  # Only the REHEARSAL's egress: standins.yml makes egress-net internal. The shipped egress-net (not internal) with
  # deploy/network.sh's nftables is NOT rehearsed (no NET_ADMIN here); it is checked at the site's IQ (RUNBOOK §16).
  in_svc criteria-compiler <<'EOF' || fail "criteria-compiler can reach the internet"
import socket
for host in ("clinicaltrials.gov", "repo1.maven.org", "pypi.org"):
    try:
        socket.create_connection((host, 443), timeout=5).close()
        raise SystemExit(f"{host}:443 reachable")
    except OSError as e:
        print(f"ok: {host}:443 not reachable with the rehearsal's internal egress-net ({type(e).__name__})")
EOF
  ;;

# ------------------------------------------------------------------------------------------------ model-guard
guard)
  # D-177: vLLM checks its key on /v1 only. On model-net only model-guard answers to the servers' names: it passes
  # /v1/models, /v1/chat/completions, /v1/completions and /tokenize (D-739) with the key and /health, and nothing
  # else. The stand-ins answer /invocations and /tokenize without a key, as vLLM does, so a box without the guard
  # would show here (the stand-in counts a keyed /tokenize apart from the open calls).
  in_svc gateway <<'EOF' || fail "model-guard let a call through that it must not"
import json, os, urllib.error, urllib.request
key = open(os.environ["TB_LLM_API_KEY_FILE"]).read().strip()  # the compose secret (D-437); the variable is cleared
def call(method, url, k):
    h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {k}"} if k else {})}
    body = json.dumps({"messages": [{"role": "user", "content": "x"}], "prompt": "x"}).encode() if method == "POST" else None
    try:
        return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h, method=method), timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code
for host in ("llm-service", "llm-verifier"):
    base = f"http://{host}:8000"
    st = call("POST", base + "/tokenize", "")
    assert st == 401, f"{host} POST /tokenize (no key): HTTP {st}"  # D-739: with the key only
    st = call("POST", base + "/tokenize", key)
    assert st == 200, f"{host} POST /tokenize (key): HTTP {st}"
    for path in ("/invocations", "/detokenize", "/pooling", "/collective_rpc", "/sleep"):
        for k in ("", key):
            st = call("POST", base + path, k)
            assert st == 404, f"{host} POST {path} ({'key' if k else 'no key'}): HTTP {st}"
    for path in ("/metrics", "/server_info", "/standin/stats"):
        assert call("GET", base + path, key) == 404, f"{host} GET {path}"
    assert call("GET", base + "/v1/models", "") == 401 and call("GET", base + "/v1/models", key) == 200
    print(f"ok: {host}: /invocations, /collective_rpc, /metrics ... 404 with or without the key; /v1 and /tokenize need it")
EOF
  stats="$(standin_stats)" || fail "cannot ask the stand-ins"
  echo "stand-ins: $stats"
  echo "$stats" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert all(not v.get("open") for v in d.values()), d' \
    || fail "a call without the key reached a stand-in's open route"
  ok "the stand-ins' open routes (as vLLM's) were reached by nothing"
  docker inspect trialbox-llm-service-1 --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' | grep -qx 'trialbox-model-backend ' \
    || fail "llm-service is on another network than trialbox-model-backend"
  ok "the model servers are only on trialbox-model-backend"
  ;;

# ------------------------------------------------------------------------------------------------ console
console)
  # T-632: the console is reached only at https://TB_TLS_HOSTNAME through Caddy, with Caddy's root certificate
  host="$(envget TB_TLS_HOSTNAME)"; base="https://$host"
  get=(curl -fsS -m 10 --cacert "$BOX/deploy/secrets/tls/caddy-root.crt" --resolve "$host:443:${TB_RH_TLS_ADDR:-127.0.0.1}")
  for _ in $(seq 1 24); do "${get[@]}" "$base/healthz" && break; sleep 5; done
  "${get[@]}" "$base/healthz" || fail "console /healthz at $base"
  echo
  code="$("${get[@]/-fsS/-s}" -o "$W/login.html" -w '%{http_code}' "$base/login")"
  [ "$code" = 200 ] && grep -qi "password" "$W/login.html" || fail "console sign-in page: HTTP $code"
  ok "console up at $base: /healthz and the sign-in page (certificate checked)"
  # console-net (D-176) carries the published port only: no outside name resolves, nothing outside answers, the box's
  # own names still do. The rehearsal host has no NET_ADMIN, so deploy/network.sh is not applied: the compose file
  # alone must hold.
  # the host itself from the console: reported, not asserted (deploy/network.sh's input hook drops it at a site; it
  # is not applied here)
  gw="$(docker network inspect trialbox-console --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')"
  in_svc console <<EOF || true
import socket
for port in (22, 2375, 5432):
    try:
        socket.create_connection(("$gw", port), timeout=3).close(); print(f"note: host $gw:{port} answers the console (network.sh not applied here)")
    except OSError as e:
        print(f"note: host $gw:{port} does not answer the console ({type(e).__name__})")
EOF
  net="$(docker network inspect trialbox-console --format '{{json .Options}} ipv6={{.EnableIPv6}}')"; echo "console-net: $net"
  echo "$net" | grep -q '"com.docker.network.bridge.enable_ip_masquerade":"false"' && echo "$net" | grep -q 'ipv6=false' \
    || fail "console-net is not closed (no NAT out, no IPv6)"
  in_svc console <<'EOF' || fail "the console can reach outside the box"
import socket
socket.getaddrinfo("orchestrator", 8010)
print("ok: console resolves the box's own names (orchestrator)")
for host in ("example.com", "pypi.org"):
    try:
        socket.getaddrinfo(host, 443)
        raise SystemExit(f"{host} resolves inside the console")
    except socket.gaierror as e:
        print(f"ok: {host} does not resolve in the console ({e.strerror})")
for ip in ("1.1.1.1", "8.8.8.8"):
    try:
        socket.create_connection((ip, 443), timeout=5).close()
        raise SystemExit(f"{ip}:443 reachable from the console")
    except OSError as e:
        print(f"ok: {ip}:443 not reachable from the console ({type(e).__name__})")
EOF
  ;;

# ------------------------------------------------------------------------------------------------ SCREEN
screen)
  tag="${2:-first}"
  if [ ! -f "$W/ingested" ]; then
    # D-887: today's snapshot, as the nightly ingest makes it (a fixed date grew older than the box accepts, D-383)
    dc exec -T adapter python -m adapter.cli run --source csv --path /data/source/site-a --snapshot "$(date -u +%F)" \
      | tail -5 || fail "ingest of synthetic hospital A failed"
    touch "$W/ingested"
  fi
  # D-887: a VALIDATION box seeds no example study (D-640); the operator's synthetic-run install of the example, as
  # RUNBOOK §1 step 2 gives it (idempotent: the same approved content again is the same tag)
  dc exec -T criteria-compiler sh -c 'cd /app/rulesets && python -m zipfile -c /tmp/GZQO.zip GZQO &&
    python -m criteria_compiler.import_ruleset /tmp/GZQO.zip --by "synthetic-run:box-rehearsal"' \
    || fail "the example study GZQO could not be installed (criteria_compiler.import_ruleset)"
  before="$(standin_stats)" || fail "cannot ask the stand-ins"
  mails_before="$(dc logs --no-log-prefix mail-sink 2>/dev/null | grep -c '"smtp_sink"' || true)"
  in_svc mail-gateway <<EOF || fail "SCREEN did not finish"
import time
import httpx
from tb_common.service_auth import auth_headers

orch = "http://orchestrator:8010"
# D-464: the mail gateway's token starts mail commands and reads the jobs that came in by mail (a message id)
body = {"type": "SCREEN", "ruleset": "GZQO", "options": {"version": "1.0.0"}, "comment": "rehearsal-$tag",
        "requested_by": "crc1@hospa.test", "message_id": "<rehearsal-$tag@hospa.test>"}
job = httpx.post(f"{orch}/jobs", json=body, headers=auth_headers(), timeout=60)
assert job.status_code == 200, f"POST /jobs: {job.status_code} {job.text[:300]}"
jid = job.json()["job_id"]
deadline = time.monotonic() + 1200
while time.monotonic() < deadline:
    j = httpx.get(f"{orch}/jobs/{jid}", headers=auth_headers(), timeout=60).json()
    if j["state"] in ("done", "failed", "cancelled", "rejected"):
        break
    time.sleep(5)
print({k: j.get(k) for k in ("job_id", "type", "state", "error")})
print("metrics:", {k: v for k, v in (j.get("metrics") or {}).items() if not isinstance(v, (dict, list))})
assert j["state"] == "done", f"SCREEN ended {j['state']}: {j.get('error')}"
assert (j.get("metrics") or {}).get("patients_scoped", 0) > 0, "no patient in scope"
EOF
  after="$(standin_stats)" || fail "cannot ask the stand-ins"
  python3 - "$before" "$after" <<'EOF' || fail "the SCREEN did not go through the gateway to both pinned models"
import json, sys
b, a = (json.loads(x) for x in sys.argv[1:3])
for host in ("llm-service", "llm-verifier"):
    d = {k: a[host]["counts"].get(k, 0) - b[host]["counts"].get(k, 0) for k in ("200", "400", "401", "404")}
    print(f"{host} during the SCREEN: {d}")
    assert d["404"] == 0 and d["401"] == 0, f"{host}: refused calls during the SCREEN"
    assert d["200"] > 0, f"{host}: no model call reached it"
EOF
  mails="$(( $(dc logs --no-log-prefix mail-sink 2>/dev/null | grep -c '"smtp_sink"' || true) - mails_before ))"
  [ "$mails" -gt 0 ] || fail "the SCREEN mailed nothing to the site's SMTP relay"
  ok "SCREEN GZQO on synthetic hospital A: done, model calls through the gateway to both pinned builds, no 401/404, $mails mail(s) to the relay"
  ;;

# ------------------------------------------------------------------------------------------------ after a restart
after-restart)
  wait_healthy 600
  st="$(dc exec -T criteria-compiler python -m tb_common.refdata status)" && echo "$st" | grep -q "$(cat "$W/vendor/refdata-pack-id.txt")" \
    || fail "the reference data did not survive the restart"
  ok "reference data still loaded"
  # D-464: listing jobs is the console's, not the mail gateway's
  in_svc console <<'EOF' || fail "the first SCREEN's job did not survive the restart"
import httpx
from tb_common.service_auth import auth_headers
jobs = httpx.get("http://orchestrator:8010/jobs", params={"type": "SCREEN"}, headers=auth_headers(), timeout=60).json()
done = [j for j in jobs if j.get("comment") == "rehearsal-first" and j["state"] == "done"]
assert done, "no finished SCREEN from before the restart"
print(f"ok: SCREEN {done[0]['job_id']} from before the restart is still on the box")
EOF
  ;;

# ------------------------------------------------------------------------------------------------ terminology
terminology)
  # D-991 (TERM-VOL): a code system loaded at install reaches the services. A synthetic site list (two made-up local
  # codes) is staged in deploy/site/terminology and loaded by deploy/terminology.sh, the volume's one writer; then
  # criteria-compiler, orchestrator and console each read it from their read-only mount, none can write there, and the
  # doctor's terminology line names it
  stage="$BOX/deploy/site/terminology"
  [ -d "$stage" ] || fail "the installer made no staging folder deploy/site/terminology"
  printf 'local_code,local_name,code,display\nRH-0001,rehearsal synthetic chest pain,I20.9,Angina pectoris unspecified\nRH-0002,rehearsal synthetic seizure,G40.909,Epilepsy unspecified\n' \
    > "$stage/rehearsal_local.csv"
  (cd "$BOX" && deploy/terminology.sh site-list /stage/rehearsal_local.csv --name rehearsal --system icd10cm) \
    || fail "deploy/terminology.sh could not load the synthetic site list"
  # the same check in each reader: the table is there, vouched for by its manifest line, with its two rows
  read_it='from criteria_compiler.terminology import installed as i
t = {x.name: x for x in i.status(i.installed_dir())}.get("site_rehearsal")
assert t and not t.problem and t.rows == 2, t
print(f"{t.name} {t.rows} rows")'
  for svc in criteria-compiler orchestrator console; do
    out="$(dc exec -T "$svc" python -c "$read_it")" || fail "$svc does not read the table loaded at install"
    if dc exec -T "$svc" sh -c 'touch /data/terminology/.written-by-a-service' 2>/dev/null; then
      fail "$svc can write the terminology volume (it must be read-only there)"
    fi
    ok "$svc reads $out from /data/terminology, read-only"
  done
  doctor 2>&1 | grep -E '(^|[^a-z_])terminology' | grep -q "site_rehearsal 2 rows" \
    || { doctor 2>&1 | grep -i terminology; fail "the doctor's terminology line does not name the loaded table"; }
  ok "doctor: terminology names site_rehearsal (loaded at install, read through the volume)"
  ;;

# ------------------------------------------------------------------------------------------------ restic-restore
restic-restore)
  # PERF-010 R4 (D-978, the integrator's option A): this box's KEK is the passphrase one (no TPM here), which no
  # custodians' shares cover, so its own nightly keeps the single .tbbak (D-977). The restic path is rehearsed with a
  # throwaway shamir KEK in this work folder: the nightly's own backup step, the bundle's backup image, the box's
  # real volumes read-only; then the custodians' path (two shares, no box KEK) restores the lake into a temporary
  # folder and checks every file against the sealed manifest. The live lake is only ever read.
  cd "$BOX" || fail "no box at $BOX"
  export PYTHONPATH="libs:services:."
  sec="$(docker volume inspect -f '{{.Mountpoint}}' trialbox_tb-secrets)" || fail "no secrets volume"
  python3 - "$BOX/deploy" "$sec" <<'EOF' || fail "the box's own nightly did not keep the single backup for its passphrase KEK"
import sys
from pathlib import Path
from tools.trialbox import backup_schedule as bs
ops = bs.ComposeOps(Path(sys.argv[1]))
ops.env["TB_SECRETS_DIR"] = sys.argv[2]  # the secrets volume where this host sees it
use, why = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
assert use is False and "not covered" in why and "passphrase" in why, (use, why)
print(f"ok: the box's own nightly keeps the single encrypted backup: {why}")
EOF
  rr="$W/restic-rehearsal"
  rm -rf "$rr" && mkdir -p "$rr/sec" "$rr/kek" "$rr/nas" "$rr/record/site" "$rr/verify-deploy/site" || fail "no work folder"
  chmod 0700 "$rr"
  (unset TB_KEK_PASSPHRASE; python3 -m tools.keys init --secrets "$rr/sec" --backend shamir --threshold 2 --shares 3 \
    --shares-out "$rr/shares" >/dev/null) || fail "cannot make the throwaway shamir KEK"
  mapfile -t shares < <(ls "$rr"/shares/share-*-of-3.txt)
  [ "${#shares[@]}" = 3 ] || fail "the throwaway KEK has ${#shares[@]} shares, not 3"
  python3 -m tools.keys unseal --secrets "$rr/sec" --share "${shares[0]}" --share "${shares[1]}" --out "$rr/kek/kek" \
    >/dev/null || fail "cannot unseal the throwaway KEK with two shares"
  # the host's python3 has no zstandard (the backup's own module): the key pair and the restore run in the job image
  img="$(envget TB_BACKUP_IMAGE)"; img="${img:-trialbox-backup:1.0.0}"   # the bundle's job image, restic inside
  docker run --rm --network none --user 0 -v "$rr:$rr" "$img" python -m tools.trialbox backup-keygen \
    --private "$rr/backup.key" --public "$rr/backup.pub" >/dev/null || fail "cannot make the throwaway backup key pair"
  ok "throwaway shamir KEK (2 of 3), unsealed into the work folder, and a backup key pair: never the box's"
  file="$(python3 - "$BOX/deploy" "$rr" <<'EOF'
import json, sys
from pathlib import Path
from tools.trialbox import backup_schedule as bs
ops, rr = bs.ComposeOps(Path(sys.argv[1])), Path(sys.argv[2])
# the nightly's own step with the throwaway folders: the host checks this KEK and makes restic.key under it, the job
# runs in the release's backup image with these secrets and this KEK, against the box's real volumes read-only
ops.env.update(TB_SECRETS_DIR=str(rr / "sec"), TB_KEK_FILE=str(rr / "kek" / "kek"), TB_KEK_HOST_DIR=str(rr / "kek"))
cfg = bs.Config(deploy=rr / "record", targets=[rr / "nas"], public_key=rr / "backup.pub", production=False, keep=3,
                site=ops.env.get("TB_SITE_ID", ""))
res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None,
                 classify=lambda p: bs.Target(str(p), "rehearsal folder", True))
inc = res.get("incremental") or {}
print(json.dumps({"ok": res["ok"], "errors": res["errors"], "incremental": inc}), file=sys.stderr)
assert res["ok"], res["errors"]
assert inc.get("restic") is True, inc
from tools.trialbox import restic_repo
assert (rr / "nas" / restic_repo.repo_dir(cfg.site) / "config").is_file(), "no restic repository beside the backup"
print(rr / "nas" / res["file"]["name"])
EOF
)" || fail "the nightly's backup with restic failed"
  [ -f "$file" ] || fail "no backup file in $rr/nas"
  ok "the nightly's backup sent the lake to restic: $(basename "$file") and its repository in the rehearsal folder"
  # the custodians' path: a dead box's backup opened with two shares (not the pair that unsealed), no box KEK, offline
  out="$(docker run --rm --network none --user 0 -v "$rr:$rr" "$img" \
    python -m tools.trialbox backup-verify "$file" --key "$rr/backup.key" --deploy "$rr/verify-deploy" \
    --restic-share "${shares[0]}" --restic-share "${shares[2]}")" || { echo "$out"; fail "the custodians could not restore the lake from restic"; }
  echo "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
r = d.get("restic") or {}
assert d["ok"] and r.get("snapshot") and r.get("files", 0) > 0, d
n, snap, rest = r["files"], r["snapshot"][:12], d["files"]
print(f"ok: restored by the custodians path: {n} lake files from restic snapshot {snap}, each equal to the sealed manifest; {rest} files in the .tbbak")
' || fail "the restore did not bring the lake back from restic"
  rm -rf "$rr"
  ok "the live lake was only read; the throwaway keys and the rehearsal's backup removed"
  ;;

# ------------------------------------------------------------------------------------------------ negative: name
wrong-name)
  # someone changes the served name of the judge (deploy/.env JUDGE_MODEL) and restarts its server; the pins keep
  # the old name. The installer's serving check and the doctor must FAIL and name both; the gateway must refuse.
  # The name is put back whatever happens, so the next step starts from a good box.
  good="$(envget JUDGE_MODEL)"
  pinned="$(standin_stats | python3 -c 'import json,sys; print(json.load(sys.stdin)["llm-service"]["served"][0])')" \
    || fail "cannot ask the judge stand-in its served name"
  wrong="${pinned##*/}-renamed"
  restore() {
    if [ -n "$good" ]; then envset JUDGE_MODEL "$good"; else envset JUDGE_MODEL; fi
    dc up -d --wait llm-service || fail "the judge stand-in did not come back"
  }
  envset JUDGE_MODEL "$wrong"
  dc up -d --wait llm-service || { restore; fail "the stand-in with the wrong name did not start"; }
  out="$(doctor --serving 2>&1)"; rc=$?
  echo "$out"
  [ "$rc" = 1 ] && echo "$out" | grep -q "FAIL  serving" && echo "$out" | grep -qF "pinned to the served name '$pinned'" \
    && echo "$out" | grep -qF "$wrong" || { restore; fail "the doctor did not catch the wrong served name"; }
  ok "doctor --serving (the installer's check): FAIL, names the pin ($pinned) and what is served ($wrong)"
  gateway_probe refused > "$W/probe-wrong-name.txt" 2>&1   # the verifier still answers: only the judge line counts
  cat "$W/probe-wrong-name.txt"
  grep -q "^j-workhorse: refused" "$W/probe-wrong-name.txt" || { restore; fail "the gateway did not refuse the judge"; }
  ok "gateway: the judge call is refused (upstream 404), not answered by another model"
  stats="$(standin_stats)"; echo "stand-ins: $stats"
  echo "$stats" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["llm-service"]["counts"].get("404",0)>0' \
    || { restore; fail "the stand-in counted no 404"; }
  restore
  doctor --serving >/dev/null || fail "the box did not recover after the name was restored"
  ok "name restored: doctor --serving passes again"
  ;;

# ------------------------------------------------------------------------------------------------ negative: key
missing-key)
  # the gateway loses the key, gateway restarted; the servers keep theirs. Under the secrets overlay the gateway reads
  # the compose secret deploy/secrets/model/llm.key, not deploy/.env (D-437), so the drill empties the file (D-450).
  # model-guard mounts the same file but read its key at start and is not restarted; the vLLM servers read vllm.env
  keyfile="$BOX/deploy/secrets/model/llm.key"
  key="$(cat "$keyfile")" && [ -n "$key" ] || fail "no model key file at $keyfile"
  putback() { printf '%s\n' "$key" > "$keyfile"; dc up -d --no-deps --wait gateway; }
  : > "$keyfile"
  dc up -d --no-deps --wait gateway || { putback; fail "the gateway did not restart"; }
  out="$(doctor --serving 2>&1)"; rc=$?
  echo "$out"
  [ "$rc" = 1 ] && echo "$out" | grep -q "refused the key (HTTP 401)" || { putback; fail "the doctor did not catch the missing key"; }
  ok "doctor --serving: FAIL, 'refused the key (HTTP 401)'"
  gateway_probe refused > "$W/probe-no-key.txt" 2>&1; rc=$?
  cat "$W/probe-no-key.txt"
  [ "$rc" = 0 ] && grep -q "^j-workhorse: refused" "$W/probe-no-key.txt" && grep -q "^v-verifier: refused" "$W/probe-no-key.txt" \
    || { putback; fail "the gateway's calls without the key were not refused"; }
  ok "gateway: both calls refused (upstream 401)"
  printf '%s\n' "$key" > "$keyfile"
  dc up -d --no-deps --wait gateway || fail "the gateway did not come back"
  doctor --serving >/dev/null || fail "the box did not recover with the key back"
  gateway_probe ok || fail "the gateway does not answer with the key back"
  ok "key restored: doctor --serving passes, both builds answer through the gateway"
  ;;

*) echo "box.sh: unknown phase $PHASE" >&2; exit 2 ;;
esac
