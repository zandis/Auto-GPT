#!/bin/bash
# The small demo VM's boot, rehearsed on this machine (runbook 11, "The small demo VM"): the REAL
# deploy/gcp/demo-vm-boot.sh, run as root against a local Docker, with shims for what only a GCE VM has. US$0.
#
#   tests/rehearsal/demo-vm-local.sh run IMAGE_TARBALL     boot it (the tarball of `make demo-bundle`), wait for
#                                                          DEMO-VM-READY, then check from outside: /login over TLS
#                                                          (Caddy's local CA), no :80, demo mode on (banner, a
#                                                          visitor's and a signed-in person's upload refused, the
#                                                          acknowledgement first) and switched on before Caddy; the
#                                                          people's one-time codes in the private object only; a
#                                                          code sets a password once and is then dead; an expired
#                                                          code is refused; a wrong password is refused; the chosen
#                                                          one signs in; no code or password in a log or metadata
#   tests/rehearsal/demo-vm-local.sh clean                 remove the two containers and the VM's folders
#
# Shims (in a temporary folder first on PATH; nothing else is changed):
#   curl      only http://metadata.google.internal/... is faked (the metadata from $W/md/<path>; the VM's external
#             address is 127.0.0.1); every other URL goes to the real curl
#   gcloud    `storage cp gs://local/<file> DEST` links (else copies) from $W/bucket; `storage cp FILE
#             gs://local/<path>` copies into $W/bucket (the codes' object); `auth configure-docker` does nothing
#   shutdown  records the hard stop in $W/shutdown.txt: this machine is NEVER powered off
#   apt-get, systemctl  record only (Docker is already here)
# It writes /etc/tb-demo-vm, /var/lib/tb-demo-vm, /var/log/tb-demo-vm.log and /root/trialbox-demo.tar.gz, as the VM
# does; `clean` removes them. The tarball is hard-linked, not copied, where it can be (disk is tight here). Needs root, Docker, and tcp:443 and 127.0.0.1:8080 free.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BOOT="$HERE/../../deploy/gcp/demo-vm-boot.sh"
W="${TB_REHEARSAL_DIR:-${TMPDIR:-/tmp}/tb-demo-vm-local}"

clean() {
  docker rm -f tb-demo tb-demo-caddy >/dev/null 2>&1 || true
  rm -rf /etc/tb-demo-vm /var/lib/tb-demo-vm /root/trialbox-demo.tar.gz
  rm -f /var/log/tb-demo-vm.log
}

case "${1:-}" in
  clean) clean; rm -rf "$W"; echo "clean"; exit 0 ;;
  run) TARBALL="${2:?run needs the image tarball (make demo-bundle: dist/trialbox-demo.tar.gz)}" ;;
  *) sed -n 2,21p "$0"; exit 2 ;;
esac
[ "$(id -u)" = 0 ] || { echo "run as root (the boot script is root's, as on the VM)" >&2; exit 2; }
clean
rm -rf "$W"; mkdir -p "$W/bin" "$W/md/instance/attributes" "$W/md/project" \
  "$W/md/instance/network-interfaces/0/access-configs/0" "$W/bucket"
REAL_CURL="$(command -v curl)"

# the metadata: what demo-vm.sh up would give the VM
SHA="$(sha256sum "$TARBALL" | cut -d' ' -f1)"
ln -f "$TARBALL" "$W/bucket/trialbox-demo.tar.gz" 2>/dev/null || cp "$TARBALL" "$W/bucket/trialbox-demo.tar.gz"
printf %s 127.0.0.1 > "$W/md/instance/network-interfaces/0/access-configs/0/external-ip"
printf %s local-project > "$W/md/project/project-id"
printf %s gs://local/trialbox-demo.tar.gz > "$W/md/instance/attributes/tb-demo-image"
printf %s "$SHA" > "$W/md/instance/attributes/tb-demo-image-sha256"
printf %s "${TB_DEMO_VM_HOURS:-12}" > "$W/md/instance/attributes/tb-demo-hours"
printf %s 'owner:investigator;guest:coordinator' > "$W/md/instance/attributes/tb-demo-people"
printf %s 24 > "$W/md/instance/attributes/tb-demo-enrol-hours"
printf %s gs://local/demo-vm > "$W/md/instance/attributes/tb-demo-handoff"
printf %s ja > "$W/md/instance/attributes/tb-demo-lang"
cp "$BOOT" "$W/md/instance/attributes/startup-script"

cat > "$W/bin/curl" <<EOS
#!/bin/bash
for a in "\$@"; do
  case "\$a" in
    http://metadata.google.internal/computeMetadata/v1/*)
      p="$W/md/\${a#http://metadata.google.internal/computeMetadata/v1/}"
      if [ -d "\$p" ]; then ls "\$p"; exit 0; fi
      [ -f "\$p" ] && { cat "\$p"; exit 0; }
      exit 22 ;;
  esac
done
exec "$REAL_CURL" "\$@"
EOS
cat > "$W/bin/gcloud" <<EOS
#!/bin/bash
case "\$1 \$2 \$3" in
  "storage cp gs://local/"*) ln -f "$W/bucket/\${3#gs://local/}" "\$4" 2>/dev/null || cp "$W/bucket/\${3#gs://local/}" "\$4" ;;
  "storage cp "*)
    case "\$4" in gs://local/*) mkdir -p "\$(dirname "$W/bucket/\${4#gs://local/}")"; cp "\$3" "$W/bucket/\${4#gs://local/}" ;;
      *) echo "local gcloud: not rehearsed: \$*" >&2; exit 1 ;; esac ;;
  "auth configure-docker"*) true ;;
  *) echo "local gcloud: not rehearsed: \$*" >&2; exit 1 ;;
esac
EOS
printf '#!/bin/sh\necho "shutdown $*" >> "%s/shutdown.txt"\n' "$W" > "$W/bin/shutdown"
printf '#!/bin/sh\necho "$(basename "$0") $*" >> "%s/calls.txt"\n' "$W" > "$W/bin/apt-get"
cp "$W/bin/apt-get" "$W/bin/systemctl"
chmod +x "$W/bin/"*
export PATH="$W/bin:$PATH"
[ "$(command -v shutdown)" = "$W/bin/shutdown" ] || { echo "the shutdown shim is not first on PATH: stopped" >&2; exit 3; }

echo "== the real boot script (its log: $W/boot.log)"
start=$(date +%s)
DEMO_VM_SERIAL="$W/serial.log" bash "$BOOT" > "$W/boot.log" 2>&1 || { tail -20 "$W/boot.log"; exit 1; }
grep -E '^(TB-DEMO-VM|DEMO-VM-)' "$W/boot.log"
echo "boot to its end: $(( $(date +%s) - start )) s"
grep -q DEMO-VM-READY "$W/boot.log" || { echo "FAIL: not ready"; docker logs tb-demo 2>&1 | grep -v -i password | tail -30; exit 1; }

echo "== from outside"
fail=0
ok() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
ROOT_CRT=/var/lib/tb-demo-vm/caddy/pki/authorities/local/root.crt
# demo mode (D-328) was switched on after the seed and before Caddy started: nobody outside saw it off
order=$(grep -nE 'TB-DEMO-VM .* (demo mode on \(|caddy on :443)' "$W/boot.log" | cut -d: -f1 | tr '\n' ' ')
grep -q '^demo mode on (flag.set by console:admin' "$W/boot.log" && [ "$(echo "$order" | wc -w)" = 2 ] \
  && [ "${order%% *}" -lt "$(echo "$order" | cut -d' ' -f2)" ] \
  && ok "demo mode switched on (audited, its refusal proven) before Caddy opened :443" || bad "demo mode order: $order"
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' tb-demo | grep -qx no \
  && ok "the demo container does not restart by itself (a restart would reseed with demo mode off)" || bad "restart policy"
grep -q "^shutdown -P +$(( ${TB_DEMO_VM_HOURS:-12} * 60 )) " "$W/shutdown.txt" && ok "the hard stop was armed (shimmed)" || bad "no hard stop"
code=$("$REAL_CURL" -s -o "$W/login.html" -w '%{http_code}' --cacert "$ROOT_CRT" https://127.0.0.1/login) || true
[ "$code" = 200 ] && grep -q 'name="login_csrf"' "$W/login.html" && ok "https://127.0.0.1/login answers 200 over TLS (Caddy's local CA)" || bad "/login over TLS: $code"
"$REAL_CURL" -s -o /dev/null https://127.0.0.1/login 2>/dev/null && bad "a client that does not trust Caddy's CA was not warned" \
  || ok "without Caddy's root the TLS check fails (the browser's one warning)"
"$REAL_CURL" -s -o /dev/null --max-time 5 http://127.0.0.1:80/ 2>/dev/null && bad "something answers on :80" || ok "nothing on :80"
grep -q 'data-testid="demo-banner"' "$W/login.html" && ok "the demo banner is on the sign-in page" || bad "no demo banner on /login"
# a visitor (no session) uploads a chart file through Caddy: refused before the body is read
code=$(printf 'synthetic visitor chart\n' | "$REAL_CURL" -s -o "$W/upload.html" -w '%{http_code}' --cacert "$ROOT_CRT" \
  -F csrf=x -F ruleset=GZQO -F 'charts=@-;filename=chart.txt' https://127.0.0.1/pilot/case) || true
[ "$code" = 403 ] && grep -q 'data-testid="demo-banner"' "$W/upload.html" \
  && ok "a visitor's upload is refused (403, the demo refusal page)" || bad "a visitor's upload answered $code"
code=$("$REAL_CURL" -s -o /dev/null -w '%{http_code}' --cacert "$ROOT_CRT" --data-urlencode 'criteria=synthetic' \
  https://127.0.0.1/pilot/protocol) || true
[ "$code" = 403 ] && ok "a visitor's pasted protocol text is refused (403)" || bad "a visitor's paste answered $code"
hsts=$("$REAL_CURL" -s -D - -o /dev/null --cacert "$ROOT_CRT" https://127.0.0.1/login | tr -d '\r' | grep -i '^strict-transport-security' || true)
[ -n "$hsts" ] && ok "HSTS header" || bad "no HSTS header"
[ "$(docker port tb-demo)" = "8080/tcp -> 127.0.0.1:8080" ] \
  && ok "the console listens on 127.0.0.1:8080 only" || bad "the console is not on 127.0.0.1:8080 only"
# the people's codes: in the private object only, nothing left on the VM
OBJ=$(ls "$W"/bucket/demo-vm/enrol-*.txt 2>/dev/null | tail -1 || true)
[ -n "$OBJ" ] && grep -q '^owner (investigator): https://127.0.0.1/enrol ' "$OBJ" && grep -q '^guest (coordinator): ' "$OBJ" \
  && ok "the one-time codes for owner and guest are in the private object ($(basename "$OBJ"))" || bad "no codes object"
[ ! -e /etc/tb-demo-vm/people.tsv ] && [ ! -e /etc/tb-demo-vm/handoff.txt ] \
  && ok "no file with the codes is left on the VM" || bad "a codes file is left in /etc/tb-demo-vm"
(umask 077; sed -n 's/^.*  code: \([^ ]*\)  .*$/\1/p' "$OBJ" > "$W/codes")
sed -n 's/^TB_DEMO_PASSWORD=//p' /etc/tb-demo-vm/secret.env > "$W/seedpw"  # the seed accounts' made password
# the people: enrol once, the code then dead, a wrong password refused, the chosen one signs in, an upload refused
(umask 077; python3 -c 'import secrets; print("Owner-" + secrets.token_urlsafe(15), end="")' > "$W/chosen")
if python3 - "$ROOT_CRT" "$OBJ" "$W/chosen" <<'PY'
import http.client, re, ssl, sys, urllib.parse
ctx = ssl.create_default_context(cafile=sys.argv[1])
lines = {m.group(1): m.group(2) for m in re.finditer(r"^(\S+) \(\w+\): \S+  user name: \S+  code: (\S+)  ", open(sys.argv[2]).read(), re.M)}
chosen = open(sys.argv[3]).read()
def req(method, path, body=None, cookies=None, ctype="application/x-www-form-urlencoded"):
    c = http.client.HTTPSConnection("127.0.0.1", 443, context=ctx, timeout=30)
    h = {"Cookie": "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())}
    if body is not None:
        h["Content-Type"] = ctype
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    text = r.read().decode("utf-8", "replace")
    jar = {}
    for k, v in r.getheaders():
        if k.lower() == "set-cookie":
            name, _, rest = v.partition("=")
            jar[name] = rest.split(";", 1)[0]
            if "max-age=0" not in v.lower():  # a deletion carries no value; every cookie that is set is Secure
                assert "secure" in v.lower(), f"cookie {name} set without Secure"
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), jar, text
def enrol(name, code, pw):
    st, _, jar, html = req("GET", "/enrol")
    tok = re.search(r'name="login_csrf" value="([^"]+)"', html).group(1)
    body = urllib.parse.urlencode({"username": name, "enrol_code": code, "password": pw, "password2": pw, "login_csrf": tok})
    return req("POST", "/enrol", body, jar)
def sign_in(name, pw):
    st, _, jar, html = req("GET", "/login")
    tok = re.search(r'name="login_csrf" value="([^"]+)"', html).group(1)
    body = urllib.parse.urlencode({"username": name, "password": pw, "login_csrf": tok})
    return req("POST", "/login", body, jar)
def follow(path, session):
    for _ in range(4):  # a role's home may redirect
        st, h, _, _ = req("GET", path, None, session)
        if st not in (302, 303) or h.get("location", "").startswith("/login"):
            break
        path = h["location"]
    return st, path
assert set(lines) == {"owner", "guest"}, sorted(lines)
st, hdr, jar, _ = enrol("owner", lines["owner"], chosen)
assert st == 303 and hdr.get("location") == "/", f"enrol answered {st} -> {hdr.get('location')}"
st, path = follow("/", {k: v for k, v in jar.items() if v})
assert st == 200 and path.startswith("/demo/ack"), f"after enrol: {path} {st}"
print("PASS owner: the code and a chosen password open the account; the first page is the demo acknowledgement")
st, _, _, _ = enrol("owner", lines["owner"], "Someone-else-tries-1")
assert st == 401, f"the spent code answered {st}"
print("PASS owner: the same code again is refused (401): the link is dead")
st, _, _, _ = sign_in("owner", "Someone-else-tries-1")
assert st == 401, f"a wrong password answered {st}"
print("PASS a wrong password is refused (401)")
st, hdr, jar, _ = sign_in("owner", chosen)
session = {k: v for k, v in jar.items() if v}
assert st == 303 and session and not hdr.get("location", "").startswith("/login"), f"sign-in answered {st}"
print("PASS owner signs in with the password he chose (Secure cookies)")
b = "tb-rehearsal-probe"
body = (f'--{b}\r\nContent-Disposition: form-data; name="csrf"\r\n\r\nx\r\n--{b}\r\nContent-Disposition: form-data; '
        f'name="charts"; filename="c.txt"\r\nContent-Type: text/plain\r\n\r\nsynthetic\r\n--{b}--\r\n')
st, _, _, html = req("POST", "/pilot/case", body, session, f"multipart/form-data; boundary={b}")
assert st == 403 and 'data-testid="demo-banner"' in html, f"a signed-in upload answered {st}"
print("PASS a signed-in person's upload is refused (403, demo mode)")
PY
then ok "the people's enrolment, sign-in and refusals"; else bad "the people's enrolment"; fi
# an expired code: the guest's real code, checked by the product's own store with its clock 25 h on
GUEST_CODE=$(sed -n 's/^guest (coordinator): .*  code: \([^ ]*\)  .*$/\1/p' "$OBJ")
if docker exec -i tb-demo python - <<PYX
import os, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
for p in (Path.cwd(), Path.cwd() / "libs", Path.cwd() / "services"):
    sys.path.insert(0, str(p))
from console.auth import UserStore
from tools import pglocal
url = pglocal.for_work(Path(os.environ.get("TB_DEMO_DIR") or pglocal.scratch_root() / "tb-demo"))
now = UserStore(url)
later = UserStore(url, clock=lambda: datetime.now(UTC) + timedelta(hours=25))
code = "$GUEST_CODE"  # from the heredoc, never on a command line
assert now.check_enrol_code("guest", code), "the guest's code is not live now"
assert not later.check_enrol_code("guest", code), "the guest's code is still good 25 h on"
assert later.redeem("guest", code, "Late-guest-password-1", spend=True) == "wrong"
PYX
then ok "an unused code is live now and refused 25 h on (expired)"; else bad "the expiry of an unused code"; fi
# failed sign-ins count under the browser's address (Caddy's X-Forwarded-For), not one shared proxy address
src=$(docker exec tb-demo sh -c 'grep -rh --include="*.jsonl" "\"console.login_failed\"" /tmp /var/tmp 2>/dev/null | tail -1' | python3 -c 'import json,sys; print(json.loads(sys.stdin.read() or "{}").get("detail", {}).get("source", ""))' || true)
# (the client here is 127.0.0.1 through Caddy; without the trust it would be the Docker bridge's gateway, 172.17.0.1)
[ "$src" = 127.0.0.1 ] && ok "a failed sign-in counts under the browser's own address ($src)" || bad "failed sign-in source: '$src'"
# nothing secret in the logs or the metadata: the codes, the chosen password, the seed accounts' made password
for f in "$W/boot.log" "$W/serial.log" /var/log/tb-demo-vm.log; do
  if grep -qF -f "$W/codes" "$f" || grep -qF -f "$W/chosen" "$f" || grep -qF -f "$W/seedpw" "$f"; then bad "a secret is in $f"; else ok "no code or password in $(basename "$f")"; fi
done
docker logs tb-demo > "$W/container.log" 2>&1; docker logs tb-demo-caddy >> "$W/container.log" 2>&1
if grep -qF -f "$W/codes" "$W/container.log" || grep -qF -f "$W/chosen" "$W/container.log" || grep -qF -f "$W/seedpw" "$W/container.log"
then bad "a secret is in a container log"; else ok "no code or password in the container logs"; fi
if grep -rqF -f "$W/codes" "$W/md" || grep -rqF -f "$W/seedpw" "$W/md" || grep -rqiE 'password=|code:' "$W/md/instance/attributes" --exclude=startup-script
then bad "a secret is in the metadata"; else ok "the metadata holds no code and no password"; fi
rm -f "$W/codes" "$W/chosen" "$W/seedpw" "$W/container.log"
[ "$fail" = 0 ] && echo "DEMO-VM-LOCAL: all checks pass" || { echo "DEMO-VM-LOCAL: FAILED"; exit 1; }
