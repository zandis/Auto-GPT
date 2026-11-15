#!/bin/bash
# The small demo VM's boot, rehearsed on this machine (runbook 11, "The small demo VM"): the REAL
# deploy/gcp/demo-vm-boot.sh, run as root against a local Docker, with shims for what only a GCE VM has. US$0.
#
#   tests/rehearsal/demo-vm-local.sh run IMAGE_TARBALL     boot it (the tarball of `make demo-bundle`), wait for
#                                                          DEMO-VM-READY, then check from outside: /login over TLS
#                                                          (Caddy's local CA), a sign-in with the password, no :80,
#                                                          demo mode on (banner, a visitor's upload refused, the
#                                                          acknowledgement first) and switched on before Caddy
#   tests/rehearsal/demo-vm-local.sh clean                 remove the two containers and the VM's folders
#
# Shims (in a temporary folder first on PATH; nothing else is changed):
#   curl      only http://metadata.google.internal/... is faked (the metadata from $W/md/<path>; the VM's external
#             address is 127.0.0.1); every other URL goes to the real curl
#   gcloud    `secrets versions access` reads $W/secret (a random password made here, never printed);
#             `storage cp gs://local/<file>` links (else copies) from $W/bucket; `auth configure-docker` does nothing
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
  *) sed -n 2,17p "$0"; exit 2 ;;
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
printf %s tb-demo-password > "$W/md/instance/attributes/tb-demo-password-secret"
printf %s ja > "$W/md/instance/attributes/tb-demo-lang"
cp "$BOOT" "$W/md/instance/attributes/startup-script"
(umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(18), end="")' > "$W/secret")

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
  "secrets versions access") cat "$W/secret" ;;
  "storage cp "*) ln -f "$W/bucket/\${3#gs://local/}" "\$4" 2>/dev/null || cp "$W/bucket/\${3#gs://local/}" "\$4" ;;
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
docker logs tb-demo 2>&1 | grep -qF -- "$(cat "$W/secret")" && bad "the password is in the container log" || ok "the password is not in the container log"
grep -qF -- "$(cat "$W/secret")" "$W/boot.log" && bad "the password is in the boot log" || ok "the password is not in the boot log"
# sign in as admin with the password from the secret (read by Python from the file, never printed)
if python3 - "$ROOT_CRT" "$W/secret" <<'PY'
import http.client, re, ssl, sys, urllib.parse
ctx = ssl.create_default_context(cafile=sys.argv[1])
pw = open(sys.argv[2]).read()
def req(method, path, body=None, cookies=None):
    c = http.client.HTTPSConnection("127.0.0.1", 443, context=ctx, timeout=30)
    h = {"Cookie": "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())}
    if body is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
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
st, _, jar, html = req("GET", "/login")
tok = re.search(r'name="login_csrf" value="([^"]+)"', html).group(1)
body = urllib.parse.urlencode({"username": "admin", "password": pw, "login_csrf": tok})
st, hdr, jar2, _ = req("POST", "/login", body, jar)
session = {k: v for k, v in jar2.items() if v and k not in jar}
assert st == 303 and session, f"sign-in answered {st}"
path = hdr.get("location", "/home")
for _ in range(4):  # a role's home may redirect
    st, h3, _, _ = req("GET", path, None, session)
    if st not in (302, 303) or h3.get("location", "").startswith("/login"):
        break
    path = h3["location"]
assert st == 200, f"{path} answered {st}"
assert path.startswith("/demo/ack"), f"demo mode: the first page after sign-in is {path}, not the acknowledgement"
print(f"admin: signed in, {path} answers {st} (the demo acknowledgement first)")
PY
then ok "admin signs in over https with the password from the secret (Secure cookies), lands on /demo/ack"; else bad "sign-in"; fi
[ "$fail" = 0 ] && echo "DEMO-VM-LOCAL: all checks pass" || { echo "DEMO-VM-LOCAL: FAILED"; exit 1; }
