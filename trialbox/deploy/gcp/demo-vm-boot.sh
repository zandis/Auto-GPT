#!/bin/bash
# TrialBox small demo VM: its startup script (made and given to the VM by deploy/gcp/demo-vm.sh; runs at every boot).
# It never builds and never clones: it runs the demo image (demo/Dockerfile, the same image CI's demo-boot job starts)
# with the stub model on the synthetic hospital, behind Caddy on tcp:443. docs/runbook/11-cloud-runs.md.
#
#   the image   metadata tb-demo-image: REGISTRY/PATH@sha256:<64 hex> (pulled), or gs://BUCKET/...tar.gz (`make
#               demo-bundle`) whose sha256 must equal metadata tb-demo-image-sha256 (copied, checked, loaded)
#   the login   one account per person (metadata tb-demo-people, e.g. owner:investigator;guest:coordinator), each
#               opened with the product's own one-time enrolment code (console.auth.UserStore.open_by_code, D-719):
#               the person opens https://<address>/enrol, types the user name and the code, and chooses the password
#               there (the product's rule: at least 12 characters); the code is then spent, and an unused one expires
#               after metadata tb-demo-enrol-hours. Only the codes' hashes are kept in the demo's database. The codes
#               go to ONE private object in the bucket (metadata tb-demo-handoff, gs://BUCKET/PATH; the VM's service
#               account has objectAdmin there): never the metadata, the serial console, a log or a file left on the
#               VM. The lead reads it once (`demo-vm.sh links`, which deletes it) and hands each line to its person.
#               The seed's own accounts (admin, crc, pi, subpi, cra, viewer, stw) share a password this boot makes
#               (48 random bytes, base64) into a root-only env file: nobody knows it; the boot uses it once, inside
#               the container, to switch demo mode on. No Secret Manager, no password from anyone.
#   sign-ins    failures count per account and per browser address (D-279: 5 in 15 minutes lock that account from
#               that address; many from one address slow it). The console trusts Caddy's X-Forwarded-For
#               (FORWARDED_ALLOW_IPS=*: only Caddy reaches 127.0.0.1:8080, and Caddy replaces the header a client
#               sends), so a stranger's failures do not lock the owner out from his own address.
#   demo mode   the audited flag demo.mode (D-328: banner, uploads and pasted text refused) is switched on AFTER the
#               seed and BEFORE Caddy opens tcp:443: the boot signs in as admin inside the container and sets it on
#               /ops/flags with a reason (the owner's audited path), then proves a multipart post is refused. Never
#               TB_DEMO_MODE=on in the container: the demo seeds through the console's own routes in the same
#               process, and demo mode refuses the seed's protocol paste (POST /pilot/protocol, 403): the container
#               then restarted for ever (lane G rehearsal, 2026-11-14). The container does not restart by itself:
#               every start reseeds with demo mode off, so only this script may open it (a dead demo is a 502).
#   the model   TB_LLM_MODE=stub, TB_DEMO_TOOL=demo: fixed here; no metadata key changes them (tb-llm-* stops it)
#   TLS         Caddy (pinned by digest, as deploy/gcp/hosted-demo-startup.sh) with `tls internal` for the VM's own
#               external address: the browser warns once. Only :443 is bound (no :80 listener, no redirect). The
#               firewall (demo-vm.sh) lets tcp:443 in from the allowed ranges only, and nothing else.
#   no SSH      sshd is stopped and disabled at every boot (the project's `default` network has a rule that opens
#               tcp:22 to the world; demo-vm.sh puts a deny-all on the VM's tag before it, and this is the second
#               lock). The metadata block-project-ssh-keys=TRUE keeps the project's SSH keys off the VM.
#   hard stop   metadata tb-demo-hours (whole hours): `shutdown -P` is armed at every boot, so the VM powers itself
#               off that long after it started (Compute Engine's max-run-duration stops it at the same time).
#
#   demo-vm-boot.sh                    the boot run, as root
#   demo-vm-boot.sh --dry-run          print what it would do; metadata from TB_MD_<KEY> (e.g. TB_MD_TB_DEMO_IMAGE)
#   demo-vm-boot.sh --print-caddyfile  the Caddyfile only (TB_MD_EXTERNAL_IP for the address)
#   demo-vm-boot.sh --print-demo-switch  the Python that switches demo mode on (run inside the container)
#   demo-vm-boot.sh --print-people     the Python that opens the people's accounts (run inside the container)
# No `set -x` (review A-12): nothing secret reaches the serial log.
set -euo pipefail

DRY=0; PRINT_CADDY=0; PRINT_SWITCH=0; PRINT_PEOPLE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --print-caddyfile) PRINT_CADDY=1; DRY=1 ;;
    --print-demo-switch) PRINT_SWITCH=1; DRY=1 ;;
    --print-people) PRINT_PEOPLE=1; DRY=1 ;;
    -h | --help) sed -n 2,45p "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# the same pin as deploy/gcp/hosted-demo-startup.sh (tests/unit/test_g1_demo_vm.py keeps them equal)
CADDY_IMAGE_PIN="caddy:2.11.9@sha256:0c2243efcf437ab7f7a978f1027fcf0d4f9be8a75df27b1b3fbc5dbe0ffa8cf0"
ETC=/etc/tb-demo-vm          # root-only: the env files, the Caddyfile
DATA=/var/lib/tb-demo-vm     # Caddy's data (its local CA)
MD=http://metadata.google.internal/computeMetadata/v1
# the first answer on /login: CI's demo-boot budget is 600 s (demo/README.md, measured 166 to 339 s); twice that
SEED_WAIT_S=1200

say() { echo "TB-DEMO-VM $(date -u +%H:%M:%S) $*"; }
die() { echo "TB-DEMO-VM refused: $*" >&2; exit 3; }
run() { if [ "$DRY" = 1 ]; then printf '+'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
gone() { if [ "$DRY" = 1 ]; then echo "+ docker rm -f $1"; else docker rm -f "$1" >/dev/null 2>&1 || true; fi; }
md() {  # md PATH [DEFAULT]: an instance metadata value; in a dry run the environment variable TB_MD_<KEY>
  local key=$1 def=${2-} var
  if [ "$DRY" = 1 ]; then
    var="TB_MD_$(printf '%s' "${key##*/}" | tr 'a-z-' 'A-Z_')"
    printf '%s' "${!var:-$def}"
    return 0
  fi
  curl -sf -H Metadata-Flavor:Google "$MD/$key" || printf '%s' "$def"
}

# demo mode on, inside the container (`docker exec -i tb-demo python - URL`), standard library only. It signs in as
# admin with the container's own TB_DEMO_PASSWORD (never on a command line, never printed), sets demo.mode on
# /ops/flags with a reason (audited: flag.set, actor console:admin), then posts a multipart form, which must be
# refused (403, the demo banner on the refusal page). Cookies are kept by hand: they are Secure and this is plain
# http on the container's loopback. Exit 0 only when the refusal was seen.
demo_switch() {
  cat <<'PY'
import os, re, sys, urllib.error, urllib.parse, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
FLAG = sys.argv[2] if len(sys.argv) > 2 else "demo.mode"  # steps mode: steps.acting_role (D-1063)
REASON = "demo VM boot (deploy/gcp/demo-vm-boot.sh): demo mode on after the seed, before tcp:443 opens (D-328)"
if FLAG != "demo.mode":
    REASON = f"demo VM boot (deploy/gcp/demo-vm-boot.sh), steps mode: {FLAG} on (D-1062, D-1063)"
jar = {}


class Keep(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # every redirect is read here, with the cookies
        return None


opener = urllib.request.build_opener(Keep)


def call(method, path, form=None, multipart=None):
    headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())} if jar else {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if multipart is not None:
        b = "tb-demo-vm-boot-probe"
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in multipart.items()]
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="charts"; filename="probe.txt"\r\n'
                     f"Content-Type: text/plain\r\n\r\nsynthetic probe of the demo VM boot\r\n--{b}--\r\n")
        data = "".join(parts).encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        r = opener.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        r = e
    for v in r.headers.get_all("Set-Cookie") or []:
        name, _, rest = v.partition("=")
        value = rest.split(";", 1)[0]
        if value and "max-age=0" not in v.lower():
            jar[name.strip()] = value
        else:
            jar.pop(name.strip(), None)
    return r.status, r.headers.get("Location", ""), r.read().decode("utf-8", "replace")


def field(name, html, what):
    m = re.search(f'name="{name}" value="([^"]+)"', html)
    if not m:
        sys.exit(f"demo switch: no {name} on {what}")
    return m.group(1)


pw = os.environ.get("TB_DEMO_PASSWORD") or sys.exit("demo switch: no TB_DEMO_PASSWORD in the container")
st, _, html = call("GET", "/login")
st, loc, _ = call("POST", "/login", {"username": "admin", "password": pw, "login_csrf": field("login_csrf", html, "/login")})
if st != 303 or loc.startswith(("/login", "/account")):
    sys.exit(f"demo switch: admin sign-in answered {st} -> {loc or '-'}")
st, _, html = call("GET", "/ops/flags")
if st != 200:
    sys.exit(f"demo switch: /ops/flags answered {st}")
form = {"csrf": field("csrf", html, "/ops/flags"), "name": FLAG, "value": "on", "reason": REASON,
        "confirm": "yes", "old": "off"}
st, loc, html = call("POST", "/ops/flags", form)
if st != 303:
    keys = sorted(set(re.findall(r"flags\.err\.[a-z]+", html)))
    sys.exit(f"demo switch: setting {FLAG} answered {st} {keys}")
if FLAG != "demo.mode":
    print(f"{FLAG} on (flag.set by console:admin with the boot's reason)")
    sys.exit(0)
st, _, html = call("POST", "/pilot/case", multipart={"csrf": form["csrf"], "ruleset": "GZQO"})
if st != 403 or 'data-testid="demo-banner"' not in html:
    sys.exit(f"demo switch: a multipart post answered {st}, not the demo refusal: demo mode is NOT on")
print("demo mode on (flag.set by console:admin with the boot's reason); a multipart post is refused (403)")
PY
}
if [ "$PRINT_SWITCH" = 1 ]; then demo_switch; exit 0; fi

# the people's accounts, inside the container (`docker exec -i tb-demo python - PEOPLE HOURS [STUDIES]`), after the
# seed: each opened with the product's own enrolment code (UserStore.open_by_code: a random password nobody sees,
# holder_set off, the code's hash and its expiry), on every demo study's delegation log (investigator: sub-PI,
# coordinator: CRC; all four study tasks; the seed's `pi` stays the PI), so the person sees what that role sees.
# Prints one line per person: name, role, code, expiry (UTC). The boot writes them to the private bucket object only.
people() {
  cat <<'PY'
import os, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

for p in (Path.cwd(), Path.cwd() / "libs", Path.cwd() / "services"):
    sys.path.insert(0, str(p))
from console.auth import UserStore  # noqa: E402
from console.teamstore import TASKS, TeamStore  # noqa: E402
from tools import pglocal  # noqa: E402

people = [x.split(":", 1) for x in sys.argv[1].split(",")]
hours = int(sys.argv[2])
url = pglocal.for_work(Path(os.environ.get("TB_DEMO_DIR") or pglocal.scratch_root() / "tb-demo"))
users, team = UserStore(url), TeamStore(url)
users.enrol_ttl = timedelta(hours=hours)
now = datetime.now(UTC)
today = now.date()
if len(sys.argv) > 3 and sys.argv[3]:
    studies = sys.argv[3].split(",")
else:  # every demo study whose delegation log names a PI (the seed writes one on each)
    root = Path.cwd() / "rulesets"
    studies = sorted(d.name for d in root.iterdir() if (d / "ir").is_dir() and team.pi_of(d.name, today))
LOG_ROLE = {"investigator": "sub_pi", "coordinator": "crc"}
for name, role in people:
    if users.role_of(name):
        sys.exit(f"people: an account {name} exists already")
    code = users.open_by_code(name, role, f"{name}@hospa.test", "demo-vm-boot")
    for study in studies if role in LOG_ROLE else ():
        team.add_entry(study, username=name, name=name, role=LOG_ROLE[role], tasks=list(TASKS), start=today.isoformat(),
                       end=None, training_day=today.isoformat(), training_ref="demo VM boot (synthetic)",
                       by="demo-vm-boot", at=now.isoformat())
    expires = (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M UTC")
    print(f"{name}\t{role}\t{code}\t{expires}")
PY
}
# steps mode (D-1062, D-1063, D-1065): one account per person with the roles they may act in (name:role+role), opened
# by the console's own boot tool (console.steps_roles: a one-time code each, a test box only). With SHARED (D-1065, the
# owner's ruling) the boot makes one password, redeems each person's code with it through the product's own first
# sign-in (UserStore.redeem), and prints it as the first line (name "*"); only the private bucket object ever holds it.
people_steps() {
  cat <<'PY'
import os, secrets, sys
from pathlib import Path

for p in (Path.cwd(), Path.cwd() / "libs", Path.cwd() / "services"):
    sys.path.insert(0, str(p))
# the demo's own environment (tools/demo.py sets the same default in the serving process; `docker exec` does not
# inherit it). A container started with another TB_ENV keeps it, and steps_roles then refuses.
os.environ.setdefault("TB_ENV", "DEV")
from console import steps_roles  # noqa: E402
from console.auth import UserStore  # noqa: E402
from console.teamstore import TeamStore  # noqa: E402
from tools import pglocal  # noqa: E402

people = [(n, tuple(r.split("+"))) for n, r in (x.split(":", 1) for x in sys.argv[1].split(","))]
hours, shared = int(sys.argv[2]), len(sys.argv) > 3 and sys.argv[3] == "shared"
url = pglocal.for_work(Path(os.environ.get("TB_DEMO_DIR") or pglocal.scratch_root() / "tb-demo"))
users, team = UserStore(url), TeamStore(url)
from datetime import UTC, datetime  # noqa: E402

today = datetime.now(UTC).date()
root = Path.cwd() / "rulesets"
studies = sorted(d.name for d in root.iterdir() if (d / "ir").is_dir() and team.pi_of(d.name, today))
rows = steps_roles.open_people(users, team, people, studies, hours)
if shared:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes; 4 x 5 of 31: about 99 bits
    pw = "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))
    for name, _roles, code, _expires in rows:
        if users.redeem(name, code, pw, spend=True) != "ok":
            sys.exit(f"people: {name}'s code could not be redeemed with the shared password")
    print(f"*\tshared\t{pw}\t-")
for name, roles, code, expires in rows:
    print(f"{name}\t{'+'.join(roles)}\t{code}\t{expires}")
PY
}
if [ "$PRINT_PEOPLE" = 1 ]; then people; exit 0; fi

# the serial console (demo-vm.sh status reads it); tests/rehearsal/demo-vm-local.sh points it at a file
[ "$DRY" = 1 ] || exec > >(tee -a /var/log/tb-demo-vm.log "${DEMO_VM_SERIAL:-/dev/ttyS0}") 2>&1

IP=$(md instance/network-interfaces/0/access-configs/0/external-ip "")
[[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "no external IPv4 address on this VM ('$IP')"

caddyfile() {  # tls internal for the VM's own address; a client without SNI (an IP in the address bar) gets it too
  cat <<CF
{
	admin off
	auto_https disable_redirects
	skip_install_trust
	default_sni $IP
}

https://$IP:443 {
	tls internal
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
		-Server
	}
	reverse_proxy 127.0.0.1:8080
}
CF
}
if [ "$PRINT_CADDY" = 1 ]; then caddyfile; exit 0; fi

# T-119: secrets come from Secret Manager only. A secret-looking metadata key stops the boot before anything starts
# (its value is never read); so does any key that would change the model.
metadata_keys() {
  if [ "$DRY" = 1 ]; then env | sed -n 's/^TB_MD_\([A-Z0-9_]*\)=.*/\1/p' | tr 'A-Z_' 'a-z-'; return 0; fi
  curl -sf -H Metadata-Flavor:Google "$MD/instance/attributes/" || true
}
for k in $(metadata_keys); do
  [[ "$k" =~ (password$|passwd|token|accounts|private-key|^tb-key$) ]] \
    && die "metadata $k looks like a secret: put it in Secret Manager and remove it from the metadata"
  [[ "$k" =~ ^tb-llm|^tb-demo-tool ]] && die "metadata $k: the demo VM runs the stub model and the demo tool only"
done

IMAGE=$(md instance/attributes/tb-demo-image "")
IMAGE_SHA=$(md instance/attributes/tb-demo-image-sha256 "")
PEOPLE=$(md instance/attributes/tb-demo-people "")
ENROL_HOURS=$(md instance/attributes/tb-demo-enrol-hours 24)
HANDOFF=$(md instance/attributes/tb-demo-handoff "")
HOURS=$(md instance/attributes/tb-demo-hours "")
LANG_UI=$(md instance/attributes/tb-demo-lang ja)
SITE_LANG=$(md instance/attributes/tb-demo-site-lang "")

[[ "$HOURS" =~ ^[1-9][0-9]*$ ]] || die "metadata tb-demo-hours must be a whole number of hours (got '$HOURS')"
# name:role pairs, ';' between them (gcloud splits --metadata on commas); the seed's own names are taken; admin has no
# patient-level page (D-280), so it is not offered
# tb-demo-mode=steps (D-1062): demo mode stays off, so a study can be walked from its first step, and a person may
# hold the administrator's or the steward's account too
MODE=$(md instance/attributes/tb-demo-mode demo)
case "$MODE" in demo) ROLES_RE="investigator|coordinator|viewer" ;; steps) ROLES_RE="investigator|coordinator|viewer|admin|steward" ;;
  *) die "metadata tb-demo-mode must be demo or steps (got '$MODE')" ;; esac
SHARED=$(md instance/attributes/tb-demo-shared-login 0)
case "$SHARED" in 0) ;; 1) [ "$MODE" = steps ] || die "metadata tb-demo-shared-login is for tb-demo-mode=steps only (D-1065)" ;;
  *) die "metadata tb-demo-shared-login must be 0 or 1 (got '$SHARED')" ;; esac
ONE="($ROLES_RE)"; [ "$MODE" != steps ] || ONE="($ROLES_RE)(\+($ROLES_RE))*"   # steps mode: name:role+role (D-1063)
[[ "$PEOPLE" =~ ^[a-z][a-z0-9._-]{1,31}:$ONE(\;[a-z][a-z0-9._-]{1,31}:$ONE)*$ ]] \
  || die "metadata tb-demo-people must be name:role pairs (${ROLES_RE//|/, }), separated by ;"
PEOPLE=${PEOPLE//;/,}
for _p in ${PEOPLE//,/ }; do
  case "${_p%%:*}" in admin | crc | pi | subpi | cra | viewer | stw) die "metadata tb-demo-people: ${_p%%:*} is a seeded account" ;; esac
done
[[ "$ENROL_HOURS" =~ ^[1-9][0-9]?$ ]] && [ "$ENROL_HOURS" -le 72 ] \
  || die "metadata tb-demo-enrol-hours must be 1 to 72 (the product's range, TB_CONSOLE_ENROL_CODE_HOURS)"
[[ "$HANDOFF" =~ ^gs://[a-z0-9._-]{3,63}(/[A-Za-z0-9._-]+)*$ ]] || die "metadata tb-demo-handoff must be gs://BUCKET[/PATH]"
case "$LANG_UI" in ja | zh-TW | en) ;; *) die "metadata tb-demo-lang must be ja, zh-TW or en" ;; esac
case "$SITE_LANG" in "" | ja | zh-TW) ;; *) die "metadata tb-demo-site-lang must be ja or zh-TW" ;; esac
if [[ "$IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then KIND=digest
elif [[ "$IMAGE" =~ ^gs://[a-z0-9._-]+/.+\.tar\.gz$ ]]; then
  KIND=tarball
  [[ "$IMAGE_SHA" =~ ^[0-9a-f]{64}$ ]] || die "metadata tb-demo-image-sha256 must be the tarball's sha256"
else die "metadata tb-demo-image must be an image by digest or a gs:// .tar.gz (got '$IMAGE')"; fi

# the hard stop first, before anything that could hang: a forgotten demo cannot bill for a week
say "hard stop: this VM powers off $HOURS h after this boot"
run shutdown -P "+$((HOURS * 60))" "TrialBox demo VM: the hard stop (tb-demo-hours=$HOURS)"

say "no SSH: sshd stopped and disabled (the firewall's deny-all on the VM's tag is the first lock)"
run systemctl disable --now ssh.service || say "no ssh service to stop on this image"

if [ "$DRY" = 1 ] || ! command -v docker >/dev/null; then
  run apt-get update -qq
  run apt-get install -y -qq docker.io  # Debian's package; never a script piped from the network (OPS-008)
  run systemctl enable --now docker
fi
run install -d -m 0700 "$ETC"
run install -d -m 0700 "$DATA"

say "the seed's accounts: a password made here that nobody is told (root-only file; never printed)"
if [ "$DRY" = 1 ]; then
  echo "+ write $ETC/secret.env (mode 0400): TB_DEMO_PASSWORD=<48 random bytes, base64; never printed>"
else
  tmp="$ETC/secret.env.tmp.$$"
  ( umask 077; printf 'TB_DEMO_PASSWORD=%s\n' "$(head -c 48 /dev/urandom | base64 -w0 | tr -d '/+=')" >"$tmp" )
  [ "$(wc -c <"$tmp")" -gt 50 ] || { rm -f "$tmp"; die "the made password is too short"; }
  chmod 0400 "$tmp"; mv -f "$tmp" "$ETC/secret.env"
fi
DEMO_ENV="TB_DEMO_TOOL=demo
TB_LLM_MODE=stub
FORWARDED_ALLOW_IPS=*
TB_DEMO_LANG=$LANG_UI
TB_CONSOLE_SECURE_COOKIE=1
TB_CONSOLE_PUBLIC_URL=https://$IP${SITE_LANG:+
TB_DEMO_SITE_LANG=$SITE_LANG}${PEOPLE:+
TB_DEMO_PEOPLE=$(printf '%s' "$PEOPLE" | sed -E 's/\+[a-z+]+//g')}"  # D-758: the seed names the people recipients of the studies' lists and CASE sheets
if [ "$DRY" = 1 ]; then echo "+ write $ETC/demo.env (mode 0400):"; printf '%s\n' "$DEMO_ENV" | sed 's/^/    | /'
else (umask 077; printf '%s\n' "$DEMO_ENV" >"$ETC/demo.env"); fi

say "the demo image ($KIND)"
if [ "$KIND" = digest ]; then
  case "${IMAGE%%/*}" in *-docker.pkg.dev) run gcloud auth configure-docker "${IMAGE%%/*}" --quiet ;; esac
  run docker pull -q "$IMAGE"
  REF=$IMAGE
elif [ "$DRY" = 1 ]; then
  echo "+ gcloud storage cp $IMAGE /root/trialbox-demo.tar.gz; sha256sum must be $IMAGE_SHA; docker load"
  REF="<the image docker load names>"
else
  gcloud storage cp "$IMAGE" /root/trialbox-demo.tar.gz
  echo "$IMAGE_SHA  /root/trialbox-demo.tar.gz" | sha256sum -c --quiet - || die "the tarball's sha256 is not $IMAGE_SHA"
  REF=$(gunzip -c /root/trialbox-demo.tar.gz | docker load | sed -n 's/^Loaded image: //p' | tail -1)
  [ -n "$REF" ] || die "docker load named no image"
fi
run docker pull -q "$CADDY_IMAGE_PIN"

say "the demo (stub model, synthetic hospital; seeds for 3 to 6 minutes; demo mode off until the seed is done)"
gone tb-demo
gone tb-demo-caddy  # nothing answers on :443 until demo mode is on
run docker run -d --name tb-demo --restart no --memory 6g -p 127.0.0.1:8080:8080 \
  --env-file "$ETC/demo.env" --env-file "$ETC/secret.env" "$REF"

# the seed: the console answers on the VM's loopback only (Caddy is not running yet)
if [ "$DRY" = 1 ]; then echo "+ wait up to $SEED_WAIT_S s for http://127.0.0.1:8080/login (the seed; the VM's loopback)"
else
  ok=0
  for _ in $(seq 1 $((SEED_WAIT_S / 5))); do
    if curl -sf -o /dev/null "http://127.0.0.1:8080/login" 2>/dev/null; then ok=1; break; fi
    if [ "$(docker inspect -f '{{.State.Running}}' tb-demo 2>/dev/null)" != true ]; then
      say "the demo container stopped during the seed (exit $(docker inspect -f '{{.State.ExitCode}}' tb-demo 2>/dev/null)): docker logs tb-demo (on the VM)"
      echo DEMO-VM-NOT-READY; exit 3
    fi
    sleep 5
  done
  [ "$ok" = 1 ] || { say "the seed gave no answer on 127.0.0.1:8080 within $SEED_WAIT_S s: docker logs tb-demo (on the VM)"; echo DEMO-VM-NOT-READY; exit 3; }
fi

if [ "$MODE" = steps ]; then
  say "steps mode (D-1062): demo mode stays OFF; uploads and pasted text are accepted (synthetic or public text only)"
else
say "demo mode on (D-328: banner, uploads and pasted text refused), before tcp:443 opens"
fi
if [ "$MODE" = steps ]; then
  # D-1063: the acting role's flag, switched on as the administrator does it (audited), on a test box only
  if [ "$DRY" = 1 ]; then echo "+ docker exec -i tb-demo python - http://127.0.0.1:8080 steps.acting_role < (the flag switch)"
  elif ! demo_switch | docker exec -i tb-demo python - http://127.0.0.1:8080 steps.acting_role; then
    docker rm -f tb-demo >/dev/null 2>&1 || true
    say "steps.acting_role could not be switched on: the demo was removed and tcp:443 stays closed"
    echo DEMO-VM-NOT-READY; exit 3
  fi
elif [ "$DRY" = 1 ]; then echo "+ docker exec -i tb-demo python - http://127.0.0.1:8080 < (demo-vm-boot.sh --print-demo-switch)"
elif ! demo_switch | docker exec -i tb-demo python - http://127.0.0.1:8080; then
  docker rm -f tb-demo >/dev/null 2>&1 || true
  say "demo mode could not be switched on: the demo was removed and tcp:443 stays closed"
  echo DEMO-VM-NOT-READY; exit 3
fi

SHARED_WORD=codes; [ "$SHARED" != 1 ] || SHARED_WORD=shared
say "the people's accounts ($PEOPLE): one-time enrolment codes, $ENROL_HOURS h, to the private object only"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OBJECT="$HANDOFF/enrol-$STAMP.txt"
if [ "$DRY" = 1 ]; then
  if [ "$MODE" = steps ]; then
    echo "+ docker exec -i tb-demo python - $PEOPLE $ENROL_HOURS $SHARED_WORD < (the steps people script) > $ETC/people.tsv (mode 0600)"
  else
  echo "+ docker exec -i tb-demo python - $PEOPLE $ENROL_HOURS < (demo-vm-boot.sh --print-people) > $ETC/people.tsv (mode 0600)"
  fi
  echo "+ write $ETC/handoff.txt (mode 0600) from it; gcloud storage cp $ETC/handoff.txt $OBJECT; rm both"
else
  rm -f "$ETC/people.tsv" "$ETC/handoff.txt"
  if ! (umask 077
        if [ "$MODE" = steps ]; then people_steps | docker exec -i tb-demo python - "$PEOPLE" "$ENROL_HOURS" "$SHARED_WORD"
        else people | docker exec -i tb-demo python - "$PEOPLE" "$ENROL_HOURS"; fi >"$ETC/people.tsv"); then
    rm -f "$ETC/people.tsv"; docker rm -f tb-demo >/dev/null 2>&1 || true
    say "the people's accounts could not be opened: the demo was removed and tcp:443 stays closed"
    echo DEMO-VM-NOT-READY; exit 3
  fi
  if ! (
    umask 077
    {
      echo "TrialBox demo VM https://$IP/ (boot $STAMP). Synthetic data only. Give each person their own line, privately."
      echo "Each person: open their one-time link (best in a private window; the browser warns once: Caddy's own"
      echo "certificate). The page fills the user name and the code; choose a password of at least 12 characters and"
      echo "sign in. The link then works no more. If the two fields stay empty, type the user name and the code shown."
      echo
      while IFS=$'\t' read -r name role code expires; do
        if [ "$name" = "*" ]; then   # D-1065: the one password every person's account has (steps mode, shared login)
          [[ "$code" =~ ^[a-z0-9-]+$ ]] || exit 4
          printf 'Shared sign-in (D-1065): open https://%s/ and sign in with your user name and this password: %s\n' "$IP" "$code"
          printf 'Each account holds several roles: choose the acting role in the top bar. User names:\n'
          continue
        fi
        if [ "$SHARED" = 1 ]; then printf '  %s (%s)\n' "$name" "$role"; continue; fi
        # D-776: the code after '#' never reaches the box; the console's script fills /enrol from it, then clears it
        [[ "$code" =~ ^[A-Za-z0-9-]+$ ]] || exit 4
        printf '%s (%s): https://%s/enrol#u=%s&c=%s  user name: %s  code: %s  (one-time link; unused, it expires %s)\n' \
          "$name" "$role" "$IP" "$name" "$code" "$name" "$code" "$expires"
      done <"$ETC/people.tsv"
    } >"$ETC/handoff.txt"
  ); then
    rm -f "$ETC/people.tsv" "$ETC/handoff.txt"; docker rm -f tb-demo >/dev/null 2>&1 || true
    say "a one-time code is not of the product's form (letters, digits, hyphens): the demo was removed"
    echo DEMO-VM-NOT-READY; exit 3
  fi
  rm -f "$ETC/people.tsv"
  if ! gcloud storage cp "$ETC/handoff.txt" "$OBJECT" >/dev/null 2>&1; then
    rm -f "$ETC/handoff.txt"; docker rm -f tb-demo >/dev/null 2>&1 || true
    say "the codes could not be written to $OBJECT (the VM's service account needs objectAdmin there): the demo was removed"
    echo DEMO-VM-NOT-READY; exit 3
  fi
  rm -f "$ETC/handoff.txt"
fi
say "codes for $(printf '%s' "$PEOPLE" | sed 's/:[a-z+]*//g') written to $OBJECT (only there; demo-vm.sh links reads and deletes it)"

say "caddy on :443 (tls internal for $IP)"
if [ "$DRY" = 1 ]; then echo "+ write $ETC/Caddyfile:"; caddyfile | sed 's/^/    | /'
else (umask 022; caddyfile >"$ETC/Caddyfile"); fi
run docker run -d --name tb-demo-caddy --restart unless-stopped --network host \
  -v "$ETC/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DATA:/data" "$CADDY_IMAGE_PIN"

if [ "$DRY" = 1 ]; then
  echo "+ wait up to $SEED_WAIT_S s for https://$IP/login (through Caddy, from the VM itself)"
  echo DEMO-VM-DRY-RUN-DONE
  exit 0
fi
ok=0
for _ in $(seq 1 $((SEED_WAIT_S / 5))); do
  if curl -sf -o /dev/null --cacert "$DATA/caddy/pki/authorities/local/root.crt" --resolve "$IP:443:127.0.0.1" \
       "https://$IP/login" 2>/dev/null; then ok=1; break; fi
  sleep 5
done
ROOT_FP=$(openssl x509 -noout -fingerprint -sha256 -in "$DATA/caddy/pki/authorities/local/root.crt" 2>/dev/null \
  | sed 's/^.*=//' || true)
if [ "$ok" = 1 ]; then
  say "ready https://$IP/ (each person: /enrol with their code from $OBJECT, then sign in)"
  say "certificate: Caddy's local CA, root SHA-256 ${ROOT_FP:-unknown} (the browser warns once; compare this)"
  echo DEMO-VM-READY
else
  say "no answer on https://$IP/login within $SEED_WAIT_S s: docker logs tb-demo (on the VM)"
  docker ps --format '{{.Names}} {{.Status}}' | sed 's/^/TB-DEMO-VM /'
  echo DEMO-VM-NOT-READY
fi
