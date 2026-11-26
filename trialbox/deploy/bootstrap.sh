#!/usr/bin/env bash
# TrialBox: the install's first command (H-22, D-996; RUNBOOK §1). It runs from the USB stick, before the release's
# host tree or any TrialBox file is on the machine, and needs only what Ubuntu 24.04 has: tar, base64, openssl,
# sha256sum and python3's standard library.
#
#   sudo bash trialbox-bootstrap.sh trialbox-<version>.tar --pub <vendor_ed25519.pub, given apart from the stick> \
#       -- --tier large --answers <folder>/site.yaml
#
# Before it runs, RUNBOOK §1 checks this file's own signature (trialbox-bootstrap.sh.sig beside it, the vendor key's
# raw Ed25519 signature) with openssl. Then, in order, and nothing is written until the first two pass:
#   1. the bundle's manifest.json.sig checks with the vendor key given out of band (nothing of the manifest is read
#      before it does);
#   2. files/trialbox-host.tar, the release's host tree, has the sha256 the signed manifest names;
#   3. the tree goes to /opt/trialbox, unpacked beside it and moved whole, never over a folder that holds anything
#      else. A folder that already holds a TrialBox tree is kept as the site's data: when it is not exactly this
#      release, the release is staged in it (releases/<bundle id>, nothing switched: LR-18) and its installer runs
#      from there; the kept tree's own code never runs (H-110), and only the installer's update step switches;
#   4. the key goes to /opt/trialbox/deploy/keys/vendor_ed25519.pub, where the installer's first step looks for it
#      (refused if a different key is already there);
#   5. deploy/install.sh (the tree's, or the staged release's) runs with the bundle and the arguments after `--`;
#      with --box, deploy/box-install.sh does
#      (the box form, HS-1: the stick's `install` launcher, deploy/launcher.sh, runs it so).
# Run it again at any time (an install that stopped is run again by the same command): nothing it did is done twice.
#
# The fingerprint it shows is the one the stick's launcher shows and the delivery sheet carries (HS-1).
# A KEK passphrase goes to the installer after `--` as --kek-passphrase-file FILE (full path) or --kek-passphrase-stdin;
# one in the environment (TB_KEK_PASSPHRASE) is refused before anything (H-96: sudo logs the variables it keeps).
# Knobs for the tests only: TB_BOOTSTRAP_NO_ROOT=1, TB_BOOTSTRAP_ROOT (/opt/trialbox).
set -euo pipefail
die() { echo "trialbox-bootstrap: $*" >&2; exit 1; }
# H-96 (F-45, H-94 (5); the integrator's ruling 7094934985): a KEK passphrase in the environment is refused here, before anything
# is read or written, with the words of the installers' KEK-INPUT block (this file runs before they are on the machine)
for kp_var in TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE; do
  if [ -n "${!kp_var:-}" ]; then
    echo "trialbox-bootstrap: $kp_var is set in the environment: refused, nothing was changed. A passphrase given by the environment can be in the system journal (sudo logs the variables it keeps, with their values): treat that passphrase as exposed and rotate it (RUNBOOK §23, rotate the KEK passphrase). Give it in a file only root can read: --kek-passphrase-file FILE (a regular file, owned by root, mode 0600), or on stdin: --kek-passphrase-stdin. Then unset $kp_var." >&2
    exit 2  # H-94 (5)
  fi
done
unset TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE kp_var
# the fingerprint: the first 24 hex digits of the sha256 of the key's DER form, in groups of four
# (the same line is in the stick's launcher and the bundle builder; a test holds the three together)
fingerprint() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-24 | sed 's/..../& /g; s/ $//'; }
usage() {
  echo "usage: sudo bash trialbox-bootstrap.sh trialbox-<version>.tar --pub <vendor key> [--box] [-- <install.sh or box-install.sh options>]" >&2  # H-94 (1): without the bundle and the key given apart nothing can be checked
  exit 2
}
BUNDLE=""; PUB=""; BOX=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pub) [ -n "${2:-}" ] || usage; PUB="$2"; shift ;;
    --box) BOX=1 ;;
    --) shift; break ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    -*) echo "trialbox-bootstrap: unknown option $1 (the installer's options go after --)" >&2; usage ;;
    *) [ -z "$BUNDLE" ] || usage; BUNDLE="$1" ;;
  esac
  shift
done
[ -n "$BUNDLE" ] && [ -n "$PUB" ] || usage
[ "${TB_BOOTSTRAP_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo bash $0 ...)"  # H-94 (4)
[ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"  # H-94 (1)
[ -f "$PUB" ] || die "--pub: no such file: $PUB"  # H-94 (1): the key given apart
for tool in tar base64 openssl sha256sum python3; do
  command -v "$tool" >/dev/null || die "this machine has no $tool (Ubuntu 24.04 has it: RUNBOOK §1 step 1)"  # H-94 (2)
done
BUNDLE="$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")"
# the installer's update step refuses such a path late, after the tree is unpacked: refused here, before anything
case "$BUNDLE" in
  *[[:space:]*?\[]*) die "the bundle's path has a space or a glob character: $BUNDLE. Rename the stick TRIALBOX (nothing was changed)" ;;  # H-94 (1): a path the checks below cannot hold
esac
ROOT="${TB_BOOTSTRAP_ROOT:-/opt/trialbox}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ----------------------------------------------------------------------------------------- 1. the signed manifest
tar -xf "$BUNDLE" -C "$WORK" --no-same-owner manifest.json manifest.json.sig 2>/dev/null \
  || die "$(basename "$BUNDLE") is not a TrialBox bundle (no manifest.json and manifest.json.sig)"  # H-94 (1)
base64 -d "$WORK/manifest.json.sig" > "$WORK/sig.raw" 2>/dev/null || die "manifest.json.sig is not base64"  # H-94 (1)
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$WORK/manifest.json" -sigfile "$WORK/sig.raw" >/dev/null 2>&1 \
  || die "the bundle's signature does not check with the vendor key $PUB: the bundle is refused"  # H-94 (1)
echo "bundle: signed by the vendor key (fingerprint: $(fingerprint "$PUB"))"

# ----------------------------------------------------------------------------------------------- 2. the host tree
HOST="$(python3 -I -c '
import json, re, sys
hosts = [f for f in json.load(open(sys.argv[1], encoding="utf-8"))["files"] if f.get("kind") == "host"]
if len(hosts) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", hosts[0]["path"]) \
        or not re.fullmatch(r"[0-9a-f]{64}", hosts[0]["sha256"]):
    sys.exit("the signed manifest names no single host tree")
print(hosts[0]["path"], hosts[0]["sha256"])
' "$WORK/manifest.json")" || die "the signed manifest names no host tree (a bundle from before T-631)"  # H-94 (1)
HOST_NAME="${HOST% *}"; HOST_SHA="${HOST#* }"
tar -xf "$BUNDLE" -C "$WORK" --no-same-owner "files/$HOST_NAME" 2>/dev/null || die "the bundle carries no files/$HOST_NAME"  # H-94 (1)
[ "$(sha256sum "$WORK/files/$HOST_NAME" | cut -d' ' -f1)" = "$HOST_SHA" ] \
  || die "files/$HOST_NAME does not have the sha256 the signed manifest names: the bundle is refused"  # H-94 (1)

# ---------------------------------------------------------------------------------------------- 3. /opt/trialbox
# H-110 (a): what a kept tree holds against the checked host tar: each signed file there (links followed) with its
# bytes, and no file the release does not hold among its code (the two library folders, a module at the top that a
# python3 started there would import). Prints the differences, nothing when the tree is exactly the signed release
kept_diff() {
  python3 -I -c '
import hashlib, importlib.machinery, os, shutil, stat, sys, tarfile
tar, root = sys.argv[1], sys.argv[2]
only_tops = len(sys.argv) > 3 and sys.argv[3] == "tops"  # LR-18: what the switch of the update step leaves in place
only_nested = len(sys.argv) > 3 and sys.argv[3] == "nested"  # review 7186452446 H-2: the residuals of the kept tree
rroot = os.path.realpath(root)
uids = (0, os.getuid())
def inside(p):
    return p == rroot or p.startswith(rroot + os.sep)
def loose(p, sticky_ok=False):  # another user could change what is read there: not owned by root (or this user) alone
    st = os.lstat(p)
    return st.st_uid not in uids or (st.st_mode & 0o022 and not (sticky_ok and st.st_mode & stat.S_ISVTX))
def sha(f):
    h = hashlib.sha256()
    for b in iter(lambda: f.read(1 << 20), b""):
        h.update(b)
    return h.hexdigest()
signed = {}
with tarfile.open(tar, "r:") as tf:
    for m in tf:
        if m.isfile() and m.name != "HOST-SHA256SUMS":
            signed[m.name] = sha(tf.extractfile(m))
bad, top_bad, nested = [], [], []
for name, want in sorted(signed.items()):
    try:
        with open(os.path.join(root, name), "rb") as f:
            got = sha(f)
    except OSError:
        got = None
    if got != want:
        bad.append(name + (": missing" if got is None else ": not the signed bytes"))
        continue
    # OCR 1455-1 (part 3): the bytes checked must stay the bytes used. The file, read through any link, is inside the
    # tree, and it and every folder from the tree down to it are owned by root alone (no group or other write)
    real = os.path.realpath(os.path.join(root, name))
    if not inside(real):
        bad.append(name + ": a link out of the tree")
        continue
    parts, d = os.path.relpath(real, rroot).split(os.sep), rroot
    for x in [None] + parts:
        d = d if x is None else os.path.join(d, x)
        if loose(d):
            bad.append(name + ": " + ("" if d == real else os.path.relpath(d, rroot) + "/ ") + "not owned by root alone")
            break
# OCR 1455-1: bytecode caches are never compared, and python3 runs a cache whose header names the mtime and size of
# its source in place of that source: the caches in the two library folders go (made again from the signed files). Only a
# real folder inside the tree is removed, never one reached through a link that leaves it
seen = set()
for top in ("tools", "libs"):
    for d, dirs, _ in os.walk(os.path.join(root, top), followlinks=True):
        rd = os.path.realpath(d)
        if not inside(rd) or rd in seen:
            dirs[:] = []
            continue
        seen.add(rd)
        for x in [x for x in dirs if x == "__pycache__"]:
            c = os.path.join(d, x)
            if not os.path.islink(c) and inside(os.path.realpath(c)):
                shutil.rmtree(c)
            else:
                bad.append(os.path.relpath(c, root) + ": a link where a cache folder is")
        dirs[:] = [x for x in dirs if x != "__pycache__"]
for top in ("tools", "libs"):
    for d, dirs, files in os.walk(os.path.join(root, top), followlinks=True):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".cache", ".venv")]
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
            # review 7186452446 H-1: a .pyc or .pyo outside a cache folder is a module python3 imports with no source
            # (a bare one): it is counted like any file the release does not hold (the cache folders went above)
            if rel not in signed:
                bad.append(rel + ": not in the release")
# OCR 1455-1: anything at the top that a python3 started there would import (a module of any suffix, a package
# folder, a .pth, a cache folder) and the release does not hold is code of the kept tree
tops = {n.split("/", 1)[0] for n in signed}
sfx = tuple(importlib.machinery.all_suffixes()) + (".pth",)
for f in sorted(os.listdir(root)):
    p = os.path.join(root, f)
    pkg = any(os.path.exists(os.path.join(p, "__init__" + x)) for x in sfx)
    if f not in tops and (f.endswith(sfx) or f == "__pycache__" or pkg):
        bad.append(f + ": not in the release")
        top_bad.append(f + ": not in the release")
# OCR 1455-1 (residual): a release folder outside the two library folders that holds a signed script python3 runs
# by path (deploy/hardening/*.py, from check_host.sh) comes first on the path of that script: an unsigned module,
# package or cache folder there is code of the kept tree (the release brought in links the folder through current)
for d in sorted({os.path.dirname(n) for n in signed if n.endswith(".py") and n.split("/", 1)[0] not in ("tools", "libs")}):
    full = os.path.join(root, d)
    if not os.path.isdir(full):
        continue
    for f in sorted(os.listdir(full)):
        p, rel = os.path.join(full, f), (d + "/" + f) if d else f
        pkg = any(os.path.exists(os.path.join(p, "__init__" + x)) for x in sfx)
        if rel not in signed and (f.endswith(sfx) or f == "__pycache__" or pkg):
            bad.append(rel + ": not in the release")
            nested.append(rel + ": not in the release")  # review 7186452446 H-2: reported on the kept tree too
# the folders above the tree: owned by root alone, or shared only with the sticky bit (as /tmp is)
up = os.path.dirname(rroot)
while True:
    if loose(up, sticky_ok=True):
        bad.append(up + "/: not owned by root alone")
    if up == os.path.dirname(up):
        break
    up = os.path.dirname(up)
bad = top_bad if only_tops else nested if only_nested else bad
print(", ".join(bad[:5]) + (f" and {len(bad) - 5} more" if len(bad) > 5 else ""))
' "$WORK/files/$HOST_NAME" "${1:-$ROOT}" ${2:+"$2"}
}
RUN_ROOT="$ROOT"  # the tree whose installer runs: the box's own, or the release staged in it (below)
if [ -f "$ROOT/deploy/install.sh" ]; then
  # H-110 (a): the installer that runs is always the signed release's; a kept tree is the site's data, never its code.
  # A tree that is not exactly this release gets the release staged first, by the release's own host-tree module read
  # from the checked tar (its stage: releases/<bundle id>, its site paths linked back to the box's own files), and
  # the installer runs from there. LR-18: nothing is switched here. `current` and the box's links stay on the release
  # the box runs until the update path (the installer's load) switches them, after the whole bundle is verified and
  # with its rollback point, which then names the release the box ran as the one before. A bundle older than the one
  # the box records is never staged
  KEPT_DIFF="$(kept_diff)" || die "the TrialBox tree at $ROOT could not be compared with the signed host tree: nothing was run"  # H-94 (1)
  if [ -n "$KEPT_DIFF" ]; then
    echo "kept: $ROOT holds a TrialBox tree that is not this release's ($KEPT_DIFF): none of its code is run"
    python3 -I -c '
import json, os, sys, tarfile, types
tar, root, manifest = sys.argv[1], sys.argv[2], sys.argv[3]
m = json.load(open(manifest, encoding="utf-8"))
seq = int(m.get("release_seq") or 0)
rec = os.path.join(root, "deploy", "updates", "installed.json")
if os.path.isfile(rec) and not os.path.islink(rec):
    try:
        have = int(json.load(open(rec, encoding="utf-8")).get("release_seq") or 0)
    except (OSError, ValueError, AttributeError):
        sys.exit(f"{rec} cannot be read: the release is not brought in")
    if have > seq:
        sys.exit(f"this box records release_seq {have}; the bundle is release_seq {seq}: an older release is not brought in")
with tarfile.open(tar, "r:") as tf:  # the module of the release, from the checked tar, never from the kept tree
    src = tf.extractfile("tools/host_tree.py").read()
ht = types.ModuleType("host_tree")
sys.modules["host_tree"] = ht
exec(compile(src, "host_tree.py", "exec"), ht.__dict__)
from pathlib import Path
bid = str(m["bundle_id"])
ht.stage(Path(tar), Path(root), bid)
print(f"staged: the signed release {bid} at {root}/releases/{bid}, switched to only by its own update step")
' "$WORK/files/$HOST_NAME" "$ROOT" "$WORK/manifest.json" \
      || die "the signed release could not be staged in $ROOT (above): none of the kept tree's code was run"  # H-94 (1)
    RUN_ROOT="$ROOT/releases/$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["bundle_id"])' "$WORK/manifest.json")"
    KEPT_DIFF="$(kept_diff "$RUN_ROOT")" || die "the staged release at $RUN_ROOT could not be compared with the signed host tree: nothing was run"  # H-94 (1)
    [ -z "$KEPT_DIFF" ] || die "the staged release at $RUN_ROOT does not match the signed host tree ($KEPT_DIFF): nothing was run. Move it aside, then run this command again"  # H-94 (1): only the signed files run
    # what the update step's switch never moves aside (it links the release's own paths only): a module, package,
    # .pth or cache at the top of the box is imported by every root job started there after the switch
    KEPT_TOPS="$(kept_diff "$ROOT" tops)" || die "the TrialBox tree at $ROOT could not be compared with the signed host tree: nothing was run"  # H-94 (1)
    [ -z "$KEPT_TOPS" ] || die "the tree at $ROOT holds code at its top that the release does not ($KEPT_TOPS): nothing was run. Move what it names aside, then run this command again"  # H-94 (1): only the signed files run
    # review 7186452446 H-2: code of the kept tree beside a signed script outside tools/ and libs/ (deploy/hardening): the
    # staged release runs, never it; the update step's switch sets those folders aside. Said, every one of them
    KEPT_NESTED="$(kept_diff "$ROOT" nested)" || die "the TrialBox tree at $ROOT could not be compared with the signed host tree: nothing was run"  # H-94 (1)
    [ -z "$KEPT_NESTED" ] || echo "kept: $ROOT holds code beside its scripts that the release does not ($KEPT_NESTED): it is not run, and the update step sets it aside"
  else
    echo "kept: $ROOT already holds this release's host tree (every file as signed)"
  fi
elif [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
  die "$ROOT exists and is not a TrialBox host tree: it is not replaced"  # H-94 depends (1): never merged over another folder's files (the tree is the signed bundle's alone)
else
  part="$ROOT.unpacking"   # unpacked beside the folder and moved whole: an interrupted unpack never looks like a tree
  rm -rf "$part"
  mkdir -p "$part"
  tar -xf "$WORK/files/$HOST_NAME" -C "$part" --no-same-owner || die "the host tree did not unpack"  # H-94 (1)
  [ -f "$part/deploy/install.sh" ] || { rm -rf "$part"; die "the host tree carries no deploy/install.sh"; }  # H-94 (1)
  [ ! -d "$ROOT" ] || rmdir "$ROOT"   # an empty folder only (checked above)
  mv "$part" "$ROOT"
  echo "unpacked: the release's host tree to $ROOT"
fi

# ------------------------------------------------------------------------------------------------- 4. the key
KEY="$ROOT/deploy/keys/vendor_ed25519.pub"
if [ -f "$KEY" ]; then
  cmp -s "$KEY" "$PUB" || die "the vendor key already at $KEY differs from $PUB: nothing was changed"  # H-94 (1): the key given apart
else
  mkdir -p "$(dirname "$KEY")"
  cp "$PUB" "$KEY"
  chmod 0644 "$KEY"
  echo "placed: the vendor key at $KEY"
fi

# -------------------------------------------------------------------------------------------- 5. the installer
cd "$ROOT"
rm -rf "$WORK"   # exec below replaces this shell, so the EXIT trap would never run (HS-1 finding)
trap - EXIT
if [ "$BOX" = 1 ]; then
  [ -f "$RUN_ROOT/deploy/box-install.sh" ] || die "the host tree at $RUN_ROOT carries no deploy/box-install.sh"  # H-94 (1)
  echo "running: $RUN_ROOT/deploy/box-install.sh $BUNDLE $*"
  exec bash "$RUN_ROOT/deploy/box-install.sh" "$BUNDLE" "$@"
fi
echo "running: $RUN_ROOT/deploy/install.sh $BUNDLE $*"
exec bash "$RUN_ROOT/deploy/install.sh" "$BUNDLE" "$@"
