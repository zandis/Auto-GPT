"""The box run's helper ON the cloud VM (deploy/gcp/box-install-run.sh; tests G-2, G-6, G-9, G-10 and R2's bundle).

Standard library only: it runs with the VM's own ``python3`` before any TrialBox code is on the disk. The driver
(deploy/gcp/box-run.sh) hands it to the VM as the metadata value ``tb-helper``; the VM script writes it to its sbin
folder and calls one subcommand at a time:

  bundle-check BUNDLE --notes F [--release-out F] [--host-out F] [--production] [--commit SHA]
      every payload of the signed bundle (``files/<path>``) against its manifest row (size, sha256) and the three
      meta files (compat.json, release.json, images.lock) against the manifest's own sha256 of them, streamed: the
      ~12 GB bundle is never unpacked to the disk. Anything else in the tar is refused. With --production the
      release record must say what a PRODUCTION box accepts (D-633, D-726): no ``rehearsal``, ``source.dirty``
      false, and the commit when --commit is given. The signature itself is the installer's check (install.sh,
      tools/verify_update.py) and the build's (step b06)
  wizard --issue F --answers F [--connect HOST:PORT] [--cacert F] [--wait S]
      the box's first-run wizard (console.firstrun) as its owner answers it in a browser: the one-time code read off
      the box's own screen (the issue file deploy/box-install.sh writes), POST /login/first-run, the answers page
      (its form token and the authenticator key it shows), a code from that key, POST the answers. No shell
      on the box, no file of the console touched: the same HTTP a browser sends
  doctor-verdict DOCTOR_JSON [--expected NAME,NAME]   ``trialbox doctor --json``: FAILs not listed as expected, and
      any rehearsal mark, make it fail (G-2)
  sample --names a,b --out F --stop F [--interval S] [--cgroup-root R]
      the memory of each named container's cgroup (memory.current) every S seconds until the stop file exists;
      at the start and the end also memory.peak, memory.max and memory.events' oom_kill
  stage-memory SAMPLES   per container: the sampled peak, the cgroup's peak, the cap, OOM kills during the stage
  compare-lists A B      two candidate lists ({"rows": [{"pid", "tier"}]}): equal or not, and what differs
  top-costs PARTS_DIR    G-6's stages by wall time and by peak memory, the three largest of each
  cmd-arg CMD_JSON --flag=F  the value of a flag in a container's command (the judge's --chat-template)
  identity --box F --lock F --template-sha S --images F --weights-exit N
      what the box serves against what the release pins: chat template, image digests, weights, prompt versions

  redact                 stdin to stdout with the lines that carry a password or an enrolment code masked (the
      installer prints the first administrator's once: a VALIDATION install's log goes to the bucket)
  acc-merge-feed --into DIR SITE_HOSPITAL_DIR ...   the hospital CSV feeds of several built public sets as one feed
      (the box's feed folder): the rows of each table, one header, a row once
  acc-set --set NAME --built DIR --work DIR --onbox F --dc "docker compose ..." --sender A --reviewer A --run-id ID
      [--compile-only] [--job-minutes N] [--notes F] [--beat F]
      one public accuracy set through the INSTALLED box's product path, protocol by protocol: FEAS by mail with the
      protocol attached, the review workbook from the job's files, APPROVE by mail from the box's named reviewer,
      SCREEN by mail scoped to the trial's investigator (pract=), the candidate and excluded lists, the box's
      pseudonym of each chart number; resumable (work/progress.json: a protocol finished is never sent again, a
      job started is waited for, never started twice: the message id is the run's). A protocol the gateway's PHI
      tripwire refused is counted as "refused_by_tripwire" (a product defect count), never dropped. Writes
      work/answers.json in the shape tools.public_accuracy.score reads, and work/pidmap.json. [--new-attempt TAG]
      (D-1129): a set that ended on its own budget, taken up again by a resume with a new budget: the set's clock
      starts a new attempt once per TAG, and only the protocols its budget cut (or never started) are run
  acc-attempt --work DIR   the set's attempt and when it started ("<n>\t<UTC start>"; attempt 1: an empty start)
  acc-merge-attempt --kind audit|traces --into F --new F --attempt N   one attempt's gateway audit or raw traces
      added to the set's file (each attempt read with its own since, so nothing is counted twice)

Every subcommand prints one JSON object on stdout (and ``--notes`` lines ``key<TAB>json`` where it takes them).
Nothing here prints a secret: the answers file's values are sent, never echoed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import socket
import ssl
import struct
import sys
import tarfile
import threading
import time
import urllib.parse
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

META = {"compat.json": "compat_sha256", "release.json": "release_sha256", "images.lock": "images_lock_sha256"}
SIGNED = ("manifest.json", "manifest.json.sig")


# ------------------------------------------------------------------------------------------------ the bundle
def bundle_check(
    bundle: Path,
    *,
    production: bool = False,
    commit: str = "",
    release_out: Path | None = None,
    host_out: Path | None = None,
    beat: Path | None = None,
) -> dict[str, Any]:
    """The signed bundle's payloads and meta files against its manifest, streamed. Returns the facts and the list
    ``refused`` (empty: the bundle is the one its manifest describes)."""
    bad: list[str] = []
    out: dict[str, Any] = {"bundle_bytes": bundle.stat().st_size}
    with tarfile.open(bundle) as tar:
        members = {m.name.removeprefix("./"): m for m in tar.getmembers()}
        if "manifest.json" not in members:
            return {**out, "refused": ["no manifest.json in the bundle"]}
        mf = tar.extractfile(members["manifest.json"])
        manifest = json.load(mf) if mf else {}
        rows = {f"files/{f['path']}": f for f in manifest.get("files") or []}
        out["manifest_files"] = len(rows)
        out["bundle_id"] = manifest.get("bundle_id", "")
        out["release_seq"] = manifest.get("release_seq")
        out["key_id"] = manifest.get("key_id")
        sig = members.get("manifest.json.sig")
        sigf = tar.extractfile(sig) if sig is not None and sig.isfile() else None
        out["signature_sha256"] = hashlib.sha256(sigf.read()).hexdigest() if sigf else None
        out["manifest_sha256"] = hashlib.sha256(json.dumps(manifest).encode()).hexdigest() if manifest else None
        release: dict[str, Any] | None = None
        for name, m in members.items():
            if m.isdir():
                continue
            unsafe = name.startswith("/") or ".." in name.split("/") or not m.isfile()
            if unsafe:
                bad.append(f"{name}: not a plain file inside the bundle")
            elif name in SIGNED:
                continue
            elif name in META:
                want = manifest.get(META[name])
                fh = tar.extractfile(m)
                data = fh.read() if fh is not None else b""
                if want != hashlib.sha256(data).hexdigest():
                    bad.append(f"{name}: its sha256 is not the manifest's {META[name]}")
                elif name == "release.json":
                    release = json.loads(data)
                    if release_out is not None:
                        release_out.write_bytes(data)
            elif name not in rows:
                bad.append(f"{name}: in the bundle, not in its manifest")
        for name, row in rows.items():
            got = members.get(name)
            if got is None:
                bad.append(f"{row['path']}: listed, not in the bundle")
                continue
            m = got
            if not m.isfile():
                continue  # refused above
            if m.size != row["size"]:
                bad.append(f"{row['path']}: {m.size} bytes, the manifest says {row['size']}")
                continue
            h, src = hashlib.sha256(), tar.extractfile(m)
            keep = host_out if (host_out is not None and row.get("kind") == "host") else None
            with open(keep, "wb") if keep else open(os.devnull, "wb") as dst:
                while src is not None and (chunk := src.read(1 << 20)):
                    h.update(chunk)
                    dst.write(chunk)
                    if beat is not None:
                        beat.touch()  # a 12 GB payload is progress, not silence
            if h.hexdigest() != row["sha256"]:
                bad.append(
                    f"{row['path']}: sha256 {h.hexdigest()[:16]}... is not the manifest's {row['sha256'][:16]}..."
                )
                if keep:
                    keep.unlink(missing_ok=True)
            elif keep:
                out["host_payload"] = row["path"]
    rel = release or {}
    rsrc: dict[str, Any] = rel["source"] if isinstance(rel.get("source"), dict) else {}
    out["release"] = {
        "version": rel.get("version"),
        "commit": rsrc.get("commit"),
        "dirty": rsrc.get("dirty"),
        "rehearsal": rel.get("rehearsal") is True,
    }
    if production:
        bad += production_refusals(release, commit)
    if host_out is not None and "host_payload" not in out and not bad:
        bad.append("the bundle carries no host tree (a payload of kind host): nothing to bootstrap the installer from")
    out["refused"] = bad
    return out


def production_refusals(release: dict[str, Any] | None, commit: str = "") -> list[str]:
    """What a PRODUCTION box refuses in a release record (tools/trialbox/update.py ``_from_a_commit``; D-633, D-726)."""
    if release is None:
        return ["the bundle has no release record (release.json): a PRODUCTION box cannot tell it came from a commit"]
    out = []
    if release.get("rehearsal") is True:
        out.append(
            "a rehearsal bundle (release.json says rehearsal; make_bundle.sh --rehearsal): "
            "PRODUCTION refuses it (D-726)"
        )
    src: dict[str, Any] = release["source"] if isinstance(release.get("source"), dict) else {}
    if src.get("dirty") is not False:
        out.append(
            f"release.json source.dirty is {src.get('dirty')!r}, not false: built from a working tree (D-631, D-633)"
        )
    got = str(src.get("commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", got):
        out.append(f"release.json names no commit (source.commit {got!r})")
    elif commit and got != commit:
        out.append(f"release.json says commit {got[:12]}, the run declared {commit[:12]}")
    return out


# ------------------------------------------------------------------------------------------------ the wizard
def totp(secret_b32: str, at: float) -> str:
    """RFC 6238 (HMAC-SHA1, 6 digits, 30 s): what the console's ``console.totp.totp`` computes."""
    s = secret_b32.strip().replace(" ", "").upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(at // 30)), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[off : off + 4])[0] & 0x7FFFFFFF) % 1_000_000).zfill(6)


def read_screen(issue: Path) -> tuple[str, str]:
    """The address and the one-time code the installer put on the box's screen (``/etc/issue.d``)."""
    text = issue.read_text(encoding="utf-8", errors="replace")
    url = re.search(r"(https?://\S+?)/login/first-run", text)
    code = re.search(r"One-time code:\s+(\S+)", text)
    if not url or not code:
        raise ValueError(f"{issue}: no address or no one-time code on the box's screen")
    return url.group(1), code.group(1)


class _Conn(http.client.HTTPSConnection):
    """HTTPS to ``connect`` (an address of this machine) with the box's own name for SNI and the Host header."""

    def __init__(self, host: str, connect: tuple[str, int], ctx: ssl.SSLContext) -> None:
        super().__init__(host, connect[1], context=ctx, timeout=60)
        self._addr, self._ctx = connect, ctx

    def connect(self) -> None:
        raw = socket.create_connection(self._addr, timeout=60)
        self.sock = self._ctx.wrap_socket(raw, server_hostname=self.host)


class Browser:
    """The one cookie of the first run, kept as a browser keeps it; nothing else of a browser."""

    def __init__(self, base: str, connect: str = "", cacert: str = "") -> None:
        u = urllib.parse.urlsplit(base)
        self.scheme, self.host = u.scheme, u.hostname or ""
        self.port = u.port or (443 if u.scheme == "https" else 80)
        addr = connect.rsplit(":", 1) if connect else [self.host, str(self.port)]
        self.addr = (addr[0], int(addr[1]))
        self.ctx = ssl.create_default_context(cafile=cacert or None)
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, form: dict[str, str] | None = None) -> tuple[int, str, dict[str, str]]:
        conn: http.client.HTTPConnection
        if self.scheme == "https":
            conn = _Conn(self.host, self.addr, self.ctx)
        else:
            conn = http.client.HTTPConnection(self.addr[0], self.addr[1], timeout=60)
        headers = {"Host": self.host if self.port in (80, 443) else f"{self.host}:{self.port}"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        text = r.read().decode("utf-8", errors="replace")
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                value = rest.split(";", 1)[0]
                if value in ('""', "") or "max-age=0" in v.lower():
                    self.cookies.pop(name.strip(), None)
                else:
                    self.cookies[name.strip()] = value
        conn.close()
        return r.status, text, {k.lower(): v for k, v in r.getheaders()}


def wizard(
    issue: Path, answers: dict[str, str], connect: str = "", cacert: str = "", now: float | None = None
) -> dict[str, Any]:
    """The first run, as the owner's browser does it. Returns the facts (never a value of the answers)."""
    base, code = read_screen(issue)
    b = Browser(base, connect, cacert)
    st, _text, _hdr = b.request("POST", "/login/first-run", {"code": code})
    if st != 303 or "tb_firstrun" not in b.cookies:
        raise RuntimeError(f"the one-time code was not taken (HTTP {st})")
    st, text, _ = b.request("GET", "/login/first-run/answers")
    key = re.search(r'id="totp-key"[^>]*value="([A-Z2-7 ]+)"', text)
    csrf = re.search(r'name="fr_csrf" value="([^"]+)"', text)
    if st != 200 or not key or not csrf:
        raise RuntimeError(f"the answers page did not come (HTTP {st}, form token {bool(csrf)}, key {bool(key)})")
    form = {k: str(v) for k, v in answers.items()}
    form.setdefault("password2", form.get("password", ""))
    if "kek" in form:
        form.setdefault("kek2", form["kek"])
    form["fr_csrf"] = csrf.group(1)
    form["totp"] = totp(key.group(1), time.time() if now is None else now)
    st, text, _ = b.request("POST", "/login/first-run/answers", form)
    if st != 200 or 'data-testid="firstrun-done"' not in text:
        errs = sorted(set(re.findall(r'data-testid="err-([a-z0-9_]+)"', text)))
        raise RuntimeError(f"the answers were not taken (HTTP {st}; fields refused: {', '.join(errs) or 'not named'})")
    return {"wizard": "done", "address": base, "fields_sent": len(form), "owner": form.get("owner_username", "")}


# ------------------------------------------------------------------------------------------------ doctor (G-2)
def doctor_verdict(checks: list[dict[str, Any]], expected: Iterable[str]) -> dict[str, Any]:
    """G-2's rule on ``trialbox doctor --json``: no FAIL beyond the ones named in advance, and no rehearsal mark."""
    want = {e.strip() for e in expected if e.strip()}
    fails = sorted(str(c.get("name")) for c in checks if c.get("status") == "FAIL")
    warns = sorted(str(c.get("name")) for c in checks if c.get("status") == "WARN")
    rehearsal = sorted(str(c.get("name")) for c in checks if "rehearsal" in str(c.get("detail", "")).lower())
    unexpected = [f for f in fails if f not in want]
    return {
        "checks": len(checks),
        "fails": fails,
        "warns": warns,
        "expected_fails": sorted(want),
        "unexpected_fails": unexpected,
        "rehearsal_marks": rehearsal,
        "pass": not unexpected and not rehearsal and bool(checks),
    }


# ------------------------------------------------------------------------------------------------ memory (G-6)
def cgroup_dir(root: Path, cid: str) -> Path | None:
    """The cgroup v2 folder of a container: systemd's driver (system.slice/docker-<id>.scope) or cgroupfs'."""
    for d in (root / "system.slice" / f"docker-{cid}.scope", root / "docker" / cid):
        if (d / "memory.current").exists():
            return d
    return None


def _read_int(p: Path) -> int | None:
    try:
        raw = p.read_text().strip()
    except OSError:
        return None
    return None if raw == "max" else int(raw) if raw.isdigit() else None


def _oom(d: Path) -> int | None:
    try:
        for line in (d / "memory.events").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k == "oom_kill":
                return int(v)
    except (OSError, ValueError):
        return None
    return 0


def cg_facts(d: Path | None) -> dict[str, Any]:
    if d is None:
        return {"cgroup": None}
    return {
        "cgroup": str(d),
        "peak": _read_int(d / "memory.peak"),
        "max": _read_int(d / "memory.max"),
        "oom_kill": _oom(d),
    }


def sample(names: list[str], ids: dict[str, str], out: Path, stop: Path, interval: float, root: Path) -> None:
    """memory.current of each container every ``interval`` seconds into ``out`` (JSON lines) until ``stop``."""
    dirs = {n: cgroup_dir(root, ids.get(n, "")) for n in names}
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.time(), "start": {n: cg_facts(d) for n, d in dirs.items()}}) + "\n")
        while True:
            row = {n: _read_int(d / "memory.current") if d else None for n, d in dirs.items()}
            fh.write(json.dumps({"t": time.time(), "mem": row}) + "\n")
            fh.flush()
            if stop.exists():
                break
            time.sleep(interval)
        dirs = {n: d or cgroup_dir(root, ids.get(n, "")) for n, d in dirs.items()}
        fh.write(json.dumps({"t": time.time(), "end": {n: cg_facts(d) for n, d in dirs.items()}}) + "\n")


def stage_memory(lines: Iterable[str]) -> dict[str, Any]:
    """Per container: the sampled peak, the cgroup's own peak (since the container started: it counts for the stage
    only when it rose during it), the cap, the OOM kills during the stage. Bytes."""
    start: dict[str, Any] = {}
    end: dict[str, Any] = {}
    peaks: dict[str, int] = {}
    t0 = t1 = None
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        t0 = row["t"] if t0 is None else t0
        t1 = row["t"]
        start = row.get("start", start)
        end = row.get("end", end)
        for n, v in (row.get("mem") or {}).items():
            if v is not None:
                peaks[n] = max(peaks.get(n, 0), int(v))
    out: dict[str, Any] = {}
    for n in sorted(set(start) | set(end) | set(peaks)):
        s, e = start.get(n) or {}, end.get(n) or {}
        rose = e.get("peak") is not None and s.get("peak") is not None and e["peak"] > s["peak"]
        best = max(peaks.get(n, 0), e["peak"] if rose else 0)
        ooms = None if e.get("oom_kill") is None or s.get("oom_kill") is None else e["oom_kill"] - s["oom_kill"]
        out[n] = {
            "peak_bytes": best or None,
            "sampled_peak_bytes": peaks.get(n),
            "cap_bytes": e.get("max"),
            "oom_kills": ooms,
            "cgroup": e.get("cgroup") or s.get("cgroup"),
        }
    return {"seconds": round((t1 or 0) - (t0 or 0), 1), "containers": out}


def top_costs(parts: Path) -> dict[str, Any]:
    """G-6 ("the 50k night profiling"): its stages by wall time and by peak memory, the three largest of each."""
    stages = []
    for p in sorted(parts.glob("*-g6-*.json")):
        d = json.loads(p.read_text())
        mem = (d.get("detail") or {}).get("memory") or {}
        peak = max(((c.get("peak_bytes") or 0, n) for n, c in (mem.get("containers") or {}).items()), default=(0, ""))
        stages.append(
            {
                "step": d["step"],
                "seconds": d.get("seconds"),
                "peak_bytes": peak[0] or None,
                "peak_container": peak[1] or None,
            }
        )
    by_t = sorted((s for s in stages if s["seconds"] is not None), key=lambda s: -float(s["seconds"]))[:3]
    by_m = sorted((s for s in stages if s["peak_bytes"]), key=lambda s: -int(s["peak_bytes"]))[:3]
    return {"by_seconds": by_t, "by_peak_memory": by_m, "stages": len(stages)}


# ------------------------------------------------------------------------------------------------ G-9
def compare_lists(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Two candidate lists: the same patients with the same tier, or what differs (pseudonymous ids, at most 20)."""

    def rows(d: dict[str, Any]) -> dict[str, str]:
        return {
            str(r["pid"]): str(r.get("tier", "")) for r in d.get("rows") or [] if isinstance(r, dict) and r.get("pid")
        }

    x, y = rows(a), rows(b)
    only_a = sorted(set(x) - set(y))
    only_b = sorted(set(y) - set(x))
    tier = sorted(p for p in set(x) & set(y) if x[p] != y[p])
    return {
        "equal": not (only_a or only_b or tier),
        "rows_a": len(x),
        "rows_b": len(y),
        "only_in_a": only_a[:20],
        "only_in_b": only_b[:20],
        "tier_differs": tier[:20],
        "differences": len(only_a) + len(only_b) + len(tier),
    }


# ------------------------------------------------------------------------------------------------ identity
def cmd_arg(cmd: list[str], flag: str) -> str:
    """The value after ``flag`` (or of ``flag=value``) in a container's command list; "" when absent."""
    for i, a in enumerate(cmd):
        if a == flag and i + 1 < len(cmd):
            return str(cmd[i + 1])
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return ""


def identity(
    box: dict[str, Any],
    lock: dict[str, Any],
    served_template_sha: str,
    images: dict[str, Any],
    weights_exit: int | None,
) -> dict[str, Any]:
    """What the box serves against what the release pins (G-1's identity half; audit C §4.3 item 3): the judge's
    chat template (the file the server was started with) against ``models/registry.yaml``; each model server's image
    digest against ``deploy/images.lock``; the weights against their pins (``pin_model --verify-all``); and the
    prompt versions the box serves in PRODUCTION. ``box`` is what the orchestrator container read (registry rows,
    served prompts); ``images`` per service: {"ref", "repo_digests"}."""
    pinned = [r.get("chat_template_sha256") for r in box.get("builds") or [] if r.get("chat_template_sha256")]
    digests: set[str] = set()
    for group in ("images", "third_party"):  # ours and the third-party ones (vLLM): the index and each platform's
        for v in (lock.get(group) or {}).values():
            if isinstance(v, dict):
                digests.add(str(v.get("digest")))
                digests |= {str(p.get("manifest")) for p in (v.get("platforms") or {}).values() if isinstance(p, dict)}
    digests.discard("None")
    img = {}
    for svc, v in images.items():
        got = [d.split("@", 1)[-1] for d in v.get("repo_digests") or []]
        img[svc] = {"ref": v.get("ref"), "digests": got, "in_images_lock": any(d in digests for d in got)}
    checks = {
        "chat_template_served_is_pinned": bool(served_template_sha) and served_template_sha in pinned,
        "images_in_images_lock": bool(img) and all(v["in_images_lock"] for v in img.values()),
        "weights_match_pins": weights_exit == 0,
        "served_prompts_named": bool(box.get("served_prompts")),
    }
    return {
        "chat_template": {"served_sha256": served_template_sha or None, "pinned_sha256": pinned},
        "images": img,
        "weights": {
            "verify_all_exit": weights_exit,
            "expected": [
                {k: r.get(k) for k in ("build_id", "manifest_sha256", "revision")} for r in box.get("builds") or []
            ],
        },
        "served_prompts": box.get("served_prompts") or [],
        "checks": checks,
        "pass": all(checks.values()),
    }


def g1_tokens(server: dict[str, Any], hf: dict[str, Any]) -> dict[str, Any]:
    """G-1's token half on the shipped serving (``tools/chat_template_check.py``'s three verdicts, D-739): the ids the
    judge's server gives each prompt through model-guard's keyed ``/tokenize`` against the ids of the weights folder's
    own tokenizer (with the folder's template, and with the template the server was started with), and the two
    template texts by sha256. A side that did not run is ``None`` with its reason, never a pass."""

    def diff(a: list[Any], b: list[Any]) -> list[dict[str, Any]]:
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            if x is None or list(x) != list(y):
                at = next((k for k, (p_, q) in enumerate(zip(x or [], y, strict=False)) if p_ != q),
                          min(len(x or []), len(y)))  # fmt: skip
                out.append({"prompt": i, "first_difference_at": at, "lengths": [len(x or []), len(y)]})
        if len(a) != len(b):
            out.append({"prompt": -1, "lengths": [len(a), len(b)]})
        return out

    srv = server.get("ids") if isinstance(server.get("ids"), list) else None
    folder = hf.get("ids") if isinstance(hf.get("ids"), list) else None
    passed = hf.get("ids_passed") if isinstance(hf.get("ids_passed"), list) else None
    d_srv = diff(srv, folder) if srv is not None and folder is not None else None
    d_pas = diff(passed, folder) if passed is not None and folder is not None else None
    fsha, psha = hf.get("folder_template_sha256"), hf.get("passed_template_sha256")
    verdicts = {
        "server_vs_folder_token_ids": None if d_srv is None else not d_srv,
        "passed_vs_folder_token_ids": None if d_pas is None else not d_pas,
        "passed_vs_folder_text_sha256": None if not (fsha and psha) else fsha == psha,
    }
    not_run = []
    if srv is None:
        not_run.append("the server side (/tokenize): no answer file")
    elif any(x is None for x in srv):
        not_run.append(f"the server side: {sum(1 for x in srv if x is None)} of {len(srv)} prompts unanswered "
                       f"({'; '.join((server.get('errors') or [])[:2])})")  # fmt: skip
    if folder is None:
        not_run.append("the tokenizer side (the model server's image, transformers): no ids")
    return {
        "prompts": len(folder or srv or []),
        "tokens": sum(len(x) for x in folder or []),
        "server": {"url": server.get("url"), "keyed": server.get("keyed")},
        "transformers": hf.get("transformers"),
        "folder_template_sha256": fsha,
        "passed_template_sha256": psha,
        "verdicts": verdicts,
        "server_different": d_srv,
        "passed_different": d_pas,
        "not_run": not_run,
        "pass": d_srv == [] and not not_run,
    }


def models_place(
    root: Path, links: list[str], template: str, embed_list: Path | None, embed_url: str, fetch: Any = None
) -> dict[str, Any]:
    """The box's flat model folders under the VM's weights folder ``root`` (compose's ``/models``), from what the VM
    holds and the public sources the registry names: each ``name=relative/target`` a RELATIVE symlink (it resolves the
    same inside the model servers' ``/models`` mount), the judge's chat template from ``template``
    (``dest=url=sha256``, the registry row's file, revision and hash) and the embedder's files from ``embed_url``
    (``{path}`` filled in) per the ``sha256  path`` list. Every downloaded file is checked against its sha256; a
    folder already there is left as it is (the pin then judges it). Returns what was done and what is missing."""
    import hashlib
    import urllib.request

    def get(url: str) -> bytes:
        """The bytes at an https address (the registry's public source). The opener speaks https only, through the
        environment's proxy when one is set: no ``file:``, ``ftp:`` or plain ``http:`` handler is in it, a redirect is
        followed only to https, and an answer that ended anywhere else is refused."""
        if fetch is not None:
            return bytes(fetch(url))
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError(f"{url}: only an https address is fetched")
        opener = urllib.request.OpenerDirector()
        for handler in (
            urllib.request.ProxyHandler(),
            urllib.request.HTTPSHandler(),
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPDefaultErrorHandler(),
            urllib.request.HTTPErrorProcessor(),
        ):
            opener.add_handler(handler)
        with opener.open(url, timeout=300) as r:
            if urllib.parse.urlsplit(r.geturl()).scheme != "https":
                raise ValueError(f"{url}: the answer came from {r.geturl()}, not an https address")
            return bytes(r.read())

    done: dict[str, Any] = {"linked": [], "kept": [], "missing": [], "fetched": [], "refused": []}
    for item in links:
        name, _, target = item.partition("=")
        dst = root / name
        if dst.exists():
            done["kept"].append(name)
        elif (root / target).is_dir():
            dst.symlink_to(target)
            done["linked"].append(f"{name} -> {target}")
        else:
            done["missing"].append(f"{name}: no {target} under {root}")

    def put(rel: str, url: str, sha: str) -> None:
        dst = root / rel
        if dst.is_file() and hashlib.sha256(dst.read_bytes()).hexdigest() == sha:
            done["kept"].append(rel)
            return
        data = get(url)
        if hashlib.sha256(data).hexdigest() != sha:
            done["refused"].append(f"{rel}: the fetched file is not sha256 {sha[:12]}")
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
        done["fetched"].append(rel)

    if template:
        rel, url, sha = template.split("=", 2)
        put(rel, url, sha)
    if embed_list is not None and embed_list.is_file():
        for line in embed_list.read_text(encoding="utf-8").splitlines():
            sha, _, rel = line.strip().partition("  ")
            if sha and rel:
                put(f"embedder/{rel}", embed_url.format(path=rel), sha)
    done["ok"] = not done["missing"] and not done["refused"]
    return done


def audit_stats(root: Path, since: float, window_s: float = 60.0, now: float | None = None) -> dict[str, Any]:
    """The gateway's audited model calls since ``since`` (epoch seconds), from the audit files (hashes, counts and
    times only; no text is in them): calls, calls a minute, the server's latency (median, p95, max), the queue in
    front of it, the longest prompts in tokens, calls per prompt version, refusals by code, calls over 60 s, and the
    calls of the last ``window_s``. A call still in flight is not in the audit yet: the newest record's age says how
    long the gateway has finished nothing."""
    from datetime import datetime

    now = time.time() if now is None else now
    lat: list[float] = []
    wait: list[float] = []
    tok: list[int] = []
    by_prompt: dict[str, int] = {}
    refusals: dict[str, int] = {}
    recent = over60 = 0
    newest = 0.0
    for f in sorted(root.glob("**/*.jsonl")) if root.is_dir() else []:
        try:
            if f.stat().st_mtime < since:
                continue
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"llm.gateway.' not in line:
                continue
            try:
                rec = json.loads(line)
                t = datetime.fromisoformat(str(rec.get("ts"))).timestamp()
            except (ValueError, TypeError):
                continue
            if t < since:
                continue
            ev, det = str(rec.get("event") or ""), rec.get("detail") or {}
            if ev.endswith(".call"):
                newest = max(newest, t)
                ms = float(det.get("latency_ms") or 0.0)
                lat.append(ms / 1000)
                wait.append(float(det.get("slot_wait_ms") or 0.0) / 1000)
                tok.append(int(det.get("tokens_in") or 0))
                pv = str(rec.get("prompt_version") or det.get("prompt") or "?")
                by_prompt[pv] = by_prompt.get(pv, 0) + 1
                recent += t >= now - window_s
                over60 += ms > 60000
            code = str(det.get("reason") or det.get("code") or rec.get("refusal") or "")
            if code and not ev.endswith(".call"):
                refusals[code] = refusals.get(code, 0) + 1

    def q(xs: list[float], f: float) -> float | None:
        if not xs:
            return None
        ys = sorted(xs)
        return round(ys[min(len(ys) - 1, int(f * (len(ys) - 1) + 0.5))], 2)

    mins = max(1e-9, (now - since) / 60)
    return {
        "calls": len(lat),
        "calls_per_min": round(len(lat) / mins, 1),
        "calls_last_window": recent,
        "latency_s": {"median": q(lat, 0.5), "p95": q(lat, 0.95), "max": q(lat, 1.0)},
        "queue_s": {"median": q(wait, 0.5), "max": q(wait, 1.0)},
        "tokens_in": {"median": q([float(x) for x in tok], 0.5), "max": max(tok) if tok else None},
        "calls_over_60s": over60,
        "by_prompt": by_prompt,
        "refusals": refusals,
        "seconds_since_last_call": round(now - newest, 1) if newest else None,
    }


def qualify_verdict(rec: dict[str, Any]) -> dict[str, Any]:
    """The qualification record's verdict per step (status and reason; hashes, counts and codes only, D-313)."""
    steps = rec.get("steps") or {}
    per_step = {
        k: {"status": (v or {}).get("status"), "reason": str((v or {}).get("reason") or "")[:300]}
        for k, v in steps.items()
        if isinstance(v, dict)
    }
    return {
        "status": rec.get("status"),
        "failed_steps": rec.get("failed_steps"),
        "qualifies_production": rec.get("qualifies_production"),
        "record_id": rec.get("record_id"),
        "git_head": rec.get("git_head"),
        "steps": per_step,
    }


# ------------------------------------------------------------------------------------------------ the command
# ------------------------------------------------------------------------------------------------ the accuracy run
REDACT = re.compile(r"(password|passwort|enrol|enroll|secret|token)", re.I)


def redact(lines: Iterable[str]) -> Iterable[str]:
    for line in lines:
        yield (line.split(":", 1)[0] + ": [redacted]\n") if REDACT.search(line) else line


def merge_feed(into: Path, sites: list[Path]) -> dict[str, Any]:
    """The hospital CSVs of several built sites as one feed: per table one header, each row once, UTF-8 with a BOM
    (as the builder writes them). A table whose headers differ between sites is refused."""
    import csv

    into.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    for site in sites:
        for f in sorted(site.glob("*.csv")):
            with f.open(newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh))
            if not rows:
                continue
            head, body = rows[0], rows[1:]
            have = tables.setdefault(f.name, (head, []))
            if have[0] != head:
                raise ValueError(f"{f}: header {head} differs from {have[0]}")
            have[1].extend(body)
    counts = {}
    for name, (head, body) in sorted(tables.items()):
        seen: set[tuple[str, ...]] = set()
        uniq = [r for r in body if not (tuple(r) in seen or seen.add(tuple(r)))]  # type: ignore[func-returns-value]
        with (into / name).open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(head)
            w.writerows(uniq)
        counts[name] = len(uniq)
    return {"tables": counts, "sites": [str(s) for s in sites]}


TRIPWIRE = "phi_tripwire"
FEAS_ENDS = ("awaiting_approval", "done", "failed", "rejected", "cancelled")
JOB_ENDS = ("done", "failed", "rejected", "cancelled")


def classify(error: Any) -> str:
    """What stopped a protocol, from the job's error text: the gateway's PHI tripwire (a product defect count, the
    owner's ruling of 2026-11-15), a refusal of the gateway or the registry for another reason, or another failure."""
    t = json.dumps(error, default=str) if not isinstance(error, str) else error
    if TRIPWIRE in t or "PHI tripwire" in t:
        return "refused_by_tripwire"
    if any(c in t for c in ("no_route", "no_eligible_build", "class_route_mismatch", "ceiling", "champion")):
        return "refused_by_gateway"
    return "failed"


def draft_criteria(zip_bytes: bytes) -> list[dict[str, Any]]:
    """The compiled criteria in the draft zip (``<RULESET>/ir/<id>.json``), as tools.public_accuracy.box reads them."""
    import io
    import zipfile

    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in sorted(n for n in z.namelist() if "/ir/" in n and n.endswith(".json")):
            c = json.loads(z.read(name).decode("utf-8"))
            text = c.get("text")
            out.append(
                {
                    "id": c.get("id"),
                    "kind": c.get("kind"),
                    "class": c.get("class"),
                    "text": text.get("source") if isinstance(text, dict) else text,
                    "domain": (c.get("logic") or {}).get("domain"),
                    "logic": c.get("logic"),
                    "flags": c.get("flags") or [],
                }
            )
    return out


def list_rows(doc: Any, tier: str = "") -> list[dict[str, Any]]:
    """The rows of a candidate list or an excluded list (``{"rows": [...]}`` or a list), each as the scorer reads a
    patient: pid, tier, actions, verdicts (id, verdict, basis, quote)."""
    rows = doc.get("rows") if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("pid"):
            continue
        verdicts = []
        for c in r.get("criteria") or []:
            ev = c.get("evidence") or {}
            # F25 (2026-11-15): the excluded list (screen.excluded_doc) names only the criteria that excluded the
            # patient, with no "verdict" key (id, source, evidence): each of them is a "fail"; its source is the basis
            verdicts.append(
                {
                    "id": c.get("id"),
                    "verdict": c.get("verdict") or ("fail" if tier == "excluded" else None),
                    "basis": c.get("basis") or c.get("source"),
                    # the excluded list carries the evidence's fields on the criterion itself (quote, reason, ...)
                    "quote": (ev.get("quote") or ev.get("text") if isinstance(ev, dict) else None) or c.get("quote"),
                }
            )
        out.append(
            {"pid": r["pid"], "tier": r.get("tier") or tier, "actions": list(r.get("actions") or []),
             "verdicts": verdicts}
        )  # fmt: skip
    return out


ARGV_MAX = 100_000  # bytes of one onbox argument on the command line (the kernel's cap on one argument: 128 KiB)


class Box:
    """The installed box as the accuracy set reaches it: onbox.py piped into a service's container."""

    def __init__(self, dc: list[str], onbox: Path, log: Path, beat: Path | None) -> None:
        self.dc, self.onbox, self.log, self.beat = dc, onbox, log, beat

    def call(self, svc: str, cmd: str, arg: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        import subprocess

        b64 = base64.b64encode(json.dumps(arg or {}, ensure_ascii=False).encode()).decode()
        program = self.onbox.read_text(encoding="utf-8")
        argv = [*self.dc, "exec", "-T", svc, "python", "-", cmd]
        if len(b64) <= ARGV_MAX:
            argv.append(b64)
        else:  # F30: one command-line argument is capped at 128 KiB; a long one goes in the program text
            main = 'if __name__ == "__main__":'
            if main not in program:
                raise RuntimeError(f"{svc} onbox {cmd}: the argument is too long for the command line")
            program = program.replace(main, f"_ONBOX_ARG_B64 = {b64!r}\n\n{main}", 1)
        with self.log.open("a", encoding="utf-8") as lf:
            lf.write(f"+ {svc} onbox {cmd} {time.strftime('%H:%M:%S')}\n")
            lf.flush()
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=lf, text=True)
            assert p.stdin is not None and p.stdout is not None
            p.stdin.write(program)
            p.stdin.close()
            # line by line, as onbox prints them: `wait` says each change of the job's state, and that line in the
            # step's log (and the beat) is the VM's heartbeat while a job runs; a long answer line is cut in the log
            lines: list[str] = []
            for line in p.stdout:
                lines.append(line)
                lf.write(log_line(line))
                lf.flush()
                if self.beat is not None:
                    self.beat.touch()
            p.wait(timeout=timeout)
            stdout = "".join(lines)
        if self.beat is not None:
            self.beat.touch()
        if p.returncode != 0:
            raise RuntimeError(f"{svc} onbox {cmd}: exit {p.returncode}")
        last = [x for x in stdout.splitlines() if x.startswith(("{", "["))]
        if not last:
            raise RuntimeError(f"{svc} onbox {cmd}: no answer")
        return json.loads(last[-1])


def log_line(line: str, cap: int = 4000) -> str:
    """One onbox answer line as box-calls.log keeps it. D6 (P1b review): an answer that carries files (``fetch``: the
    draft zip, the review workbook, the lists, base64) is written with each file's size and sha256 in place of its
    bytes, so nothing of it is cut and the log names exactly what came; any other line longer than ``cap`` is cut."""
    if len(line) <= cap:
        return line
    with suppress(ValueError):
        obj = json.loads(line)
        if isinstance(obj, dict) and isinstance(obj.get("files"), dict):
            files = {}
            for k, v in obj["files"].items():
                try:
                    raw = base64.b64decode(str(v), validate=True)
                except ValueError:
                    raw = str(v).encode()
                files[k] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            short = json.dumps({**obj, "files": files}, ensure_ascii=False)
            if len(short) <= cap * 4:
                return short + "  (files: size and sha256, not their bytes)\n"
    return line[: cap // 2] + " ... (cut)\n"


def _save(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def acc_set(
    name: str,
    built: Path,
    work: Path,
    box: Box,
    *,
    sender: str,
    reviewer: str,
    run_id: str,
    compile_only: bool,
    job_s: float,
    poll_s: float = 5.0,
    deadline_s: float = 0.0,
    protocols: list[str] | None = None,
    earlier: list[Path] | None = None,
    streams: int = 1,
    min_start_s: float = 600.0,
    new_attempt: str = "",
    site_tz: str = "",
) -> dict[str, Any]:
    """One accuracy set on the installed box (see the module docstring). Resumable from ``work/progress.json``.

    ``protocols``: only these rulesets of the set (a sized subset, recorded by the caller); the rest are not sent.

    ``earlier``: the work folders of this set's attempts before a redo, newest first (F29). The box keeps a ruleset
    version once approved: its FEAS of the same version then fails ("no structured criteria to count" for a ruleset
    of mixed criteria) with no review workbook, and a new APPROVE has nothing to approve. When an earlier attempt
    approved that same version, the set goes on to SCREEN with that draft and approval, and says so
    (``approved_in``).

    ``deadline_s`` (0: none): the set's own time budget from its first start (kept in ``work/set-clock.json``, so a
    resumed set counts its earlier boots). D4 (P1b): no protocol is started when less than its expected time is left
    (``min_start_s``, or the mean of this set's protocols that went through, whichever is longer), and no job is
    waited for longer than what is left (at least a minute), so one stuck call cannot hold the run. A protocol not
    started, or cut off by the budget while a job of it was waited for, is ``not_run_time_budget`` (never
    ``timeout_feas``): its started jobs are kept, and a later attempt with time left (a resume with a larger budget)
    takes it up again and waits for them. ``answers.json`` is rewritten after every protocol: a stop keeps every
    finished protocol.

    ``streams``: protocols in flight at once; the result says the most that were (``in_flight_max``).

    ``new_attempt`` (D-1129, card H-14): a set that ended on its own budget (protocols ``not_run_time_budget``) is
    taken up again by a resume that gives it a new budget. The tag (the resume's tb-retry) starts a new attempt of the
    set once: ``set-clock.json`` moves the attempt before into ``attempts`` (its seconds and budget, kept) and the
    new attempt's clock starts at 0 against ``deadline_s``, which is the new attempt's own budget (a pre-emption
    within the attempt keeps counting its boots, as before). Only the protocols the budget cut, or never started,
    run: a protocol finished in an earlier attempt is never sent to FEAS, APPROVE or SCREEN again, and its answers,
    job ids and screen JSON stay as they are. Each finished protocol says which attempt answered it (``attempt``);
    the result says ``attempts`` (how many, finished in each, still cut) and ``budget_cut``.

    ``site_tz``: the site's zone as the box reports it (onbox ``env``), kept in ``set-clock.json`` as ``tz`` so the
    replay reads the zone the run used; none given keeps what the clock holds."""
    ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
    protos = sorted((built / "site" / "protocols").glob("*.txt"))
    if protocols:  # D1 (P1b): a filter naming an id the set lacks stops the set, it is never a pass over nothing
        have = {p.stem for p in protos}
        unknown = [x for x in protocols if x not in have]
        if unknown:
            raise ValueError(
                f"--protocols names {', '.join(unknown)}, not a protocol of set {name} (its ids: "
                f"{', '.join(sorted(have)[:12])}{' ...' if len(have) > 12 else ''})"
            )
        protos = [p for p in protos if p.stem in set(protocols)]
    if not protos:
        raise ValueError(f"set {name} has no protocol to run")
    prog_p = work / "progress.json"
    prog: dict[str, Any] = json.loads(prog_p.read_text(encoding="utf-8")) if prog_p.exists() else {}
    before: dict[str, Any] = {}  # per ruleset: the newest earlier attempt that approved it
    for e in reversed(earlier or []):
        with suppress(OSError, ValueError):
            for rs_, a_ in json.loads((e / "progress.json").read_text(encoding="utf-8")).items():
                if isinstance(a_, dict) and a_.get("approve") == "done":
                    before[rs_] = a_
    clock_p = work / "set-clock.json"
    clock = json.loads(clock_p.read_text(encoding="utf-8")) if clock_p.exists() else {}
    if new_attempt and clock.get("attempt_tag") != new_attempt:
        _new_attempt(work, clock, new_attempt)  # D-1129: once per tag; a reboot within the attempt keeps its clock
        clock = json.loads(clock_p.read_text(encoding="utf-8"))
    attempt = int(clock.get("attempt") or 1)
    if site_tz:  # the box's own zone (never a zone of this code's choosing), for the replay
        clock["tz"] = site_tz
    used0 = float(clock.get("used_s") or 0.0)
    t_start = time.monotonic()

    def used() -> float:
        return used0 + time.monotonic() - t_start

    tick_lock = threading.Lock()

    def tick() -> None:
        with tick_lock:  # one writer at a time when protocols run side by side
            # the attempts before (D-1129) are kept as they were: only this attempt's seconds and budget move
            _save(clock_p, {**clock, "used_s": round(used(), 1), "deadline_s": deadline_s, "attempt": attempt})

    def left() -> float:
        return deadline_s - used() if deadline_s > 0 else float("inf")

    def mid(rs: str, kind: str) -> str:
        return f"<acc-{run_id}-{name}-{rs}-{kind}@trialbox.invalid>".replace(" ", "")

    def send(rs: str, kind: str, subject: str, sender_: str, attach: dict[str, bytes]) -> dict[str, Any]:
        files = {k: base64.b64encode(v).decode() for k, v in attach.items()}
        r = box.call(
            "mail-gateway", "send", {"from": sender_, "subject": subject, "mid": mid(rs, kind), "attach": files}
        )
        return dict(r)

    def wait(job: str, until: tuple[str, ...]) -> dict[str, Any]:
        t = max(60.0, min(job_s, left()))
        j = dict(box.call("mail-gateway", "wait", {"job": job, "until": list(until), "timeout_s": t,
                                                   "poll_s": poll_s}))  # fmt: skip
        # D4: a wait the set's budget shortened (not the job's own limit) and that ran out is the budget's cut
        j["cut_by_budget"] = j.get("waited") == "timeout" and t < job_s and left() <= 60.0
        return j

    lock = threading.Lock()
    gave_up: list[dict[str, Any]] = []
    flight = {"now": 0, "max": 0}
    took: list[float] = []  # seconds of each protocol of this attempt that went through (D4's expected time)

    def _retry(fn: Any, what: str) -> None:  # another stream may change the progress while it is written: write again
        err = ""
        for _ in range(20):
            try:
                with lock:
                    fn()
                return
            except RuntimeError as exc:
                err = str(exc)
                time.sleep(0.05)
        # D6 (P1b): never silent: said on stderr (the step's log) and kept beside the work (and in the result)
        row = {"what": what, "tries": 20, "error": err[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        gave_up.append(row)
        print(f"acc-set {name}: gave up writing {what} after 20 tries: {err[:300]}", file=sys.stderr, flush=True)
        with suppress(OSError, ValueError, RuntimeError):
            _save(work / "save-give-ups.json", gave_up)

    def save() -> None:
        _retry(lambda: _save(prog_p, prog), "progress.json")

    def answers() -> None:
        _retry(lambda: _answers(work, prog), "answers.json")

    def need_s() -> float:  # D4: what a protocol is expected to take, at the least min_start_s
        return max(min_start_s, sum(took) / len(took)) if took else min_start_s

    def cut(a: dict[str, Any]) -> None:  # D4: the budget cut it: picked up again by an attempt with time left
        a.update(outcome="not_run_time_budget", finished=True)
        save()

    def one(proto: Path) -> None:
        with lock:
            flight["now"] += 1
            flight["max"] = max(flight["max"], flight["now"])
        try:
            t0 = used()
            one_(proto)
            if (prog.get(proto.stem) or {}).get("outcome") in ("screened", "compiled"):
                took.append(used() - t0)
        finally:
            with lock:
                flight["now"] -= 1

    def one_(proto: Path) -> None:
        rs = proto.stem
        a = prog.setdefault(rs, {"ruleset": rs})
        tick()
        if a.get("finished") and a.get("outcome") == "not_run_time_budget" and left() > need_s():
            a.pop("finished", None)  # D4: cut by an earlier budget, and there is time now: its jobs are waited for
            a.pop("outcome", None)
        if prog.get(rs, {}).get("finished"):
            answers()
            return
        # D-1129: the attempt that runs it (and so answers it, if it ends here); one finished before keeps its own
        a["attempt"] = attempt
        started = any(k in a for k in ("feas_job", "approve_job", "screen_job"))
        if not started and left() < need_s():  # D4: too little of the budget left to start a protocol
            cut(a)
            return
        answers()
        # --- FEAS with the protocol attached, from the coordinator
        if "feas_job" not in a:
            r = send(rs, "feas", f"FEAS {rs}", sender, {proto.name: proto.read_bytes()})
            a["feas_intake"] = {k: r.get(k) for k in ("action", "reason")}
            if r.get("action") != "job" or not r.get("job"):
                a.update(outcome="refused_at_intake", finished=True)
                save()
                return
            a["feas_job"] = r["job"]
            save()
        j = wait(a["feas_job"], FEAS_ENDS)
        a["feas"], a["feas_error"], a["version"] = j.get("state"), j.get("error"), j.get("ruleset_version")
        if j["cut_by_budget"]:
            cut(a)
            return
        if j.get("waited") == "timeout":
            a.update(outcome="timeout_feas", finished=True)
            save()
            return
        files = box.call("mail-gateway", "fetch", {"job": a["feas_job"], "suffixes": [".xlsx", "-draft.zip"],
                                                   "prefixes": ["review_", "ruleset_"]})["files"]  # fmt: skip
        z = next((v for k, v in files.items() if k.endswith("-draft.zip")), None)
        a["draft"] = (
            draft_criteria(base64.b64decode(z)) if z else (a.get("draft") or [] if a.get("approved_in") else [])
        )
        xlsx = next(((k, v) for k, v in files.items() if k.endswith(".xlsx")), None)
        b = before.get(rs) or {}
        if (
            not compile_only
            and a["feas"] in ("failed", "done")  # F38: on master FEAS with nothing to count is "done" (D-901)
            and not xlsx
            and "approve_job" not in a
            and b.get("approve") == "done"
            and b.get("approve_job")
            and b.get("version") == a.get("version")
        ):
            # F29: this version was approved on the box in the attempt before: SCREEN it under that approval
            a.update(
                draft=b.get("draft") or [], approve_job=b["approve_job"], approved_in="the attempt before the redo"
            )
            save()
        elif a["feas"] != "awaiting_approval" and not xlsx:
            a.update(outcome=classify(a.get("feas_error")) if a["feas"] == "failed" else f"feas_{a['feas']}",
                     finished=True)  # fmt: skip
            save()
            return
        if compile_only:
            a.update(outcome="compiled", finished=True)
            save()
            return
        # --- APPROVE by the box's named reviewer, the review workbook as it came
        if "approve_job" not in a:
            assert xlsx is not None
            subject = f"APPROVE {rs}" + (f" version={a['version']}" if a.get("version") else "")
            r = send(rs, "approve", subject, reviewer, {"review.xlsx": base64.b64decode(xlsx[1])})
            if r.get("action") != "job" or not r.get("job"):
                a.update(approve_intake=r.get("reason"), outcome="approve_refused_at_intake", finished=True)
                save()
                return
            a["approve_job"] = r["job"]
            save()
        j = wait(a["approve_job"], JOB_ENDS)
        a["approve"], a["approve_error"] = j.get("state"), j.get("error")
        if j["cut_by_budget"]:
            cut(a)
            return
        if a["approve"] != "done":
            a.update(outcome="approve_" + str(a["approve"]), finished=True)
            save()
            return
        # --- SCREEN scoped to the trial's investigator (the mail grammar's pract=)
        if "screen_job" not in a:
            pi = (ids.get("investigators") or {}).get(rs, "")
            r = send(rs, "screen", f"SCREEN {rs}" + (f" pract={pi}" if pi else ""), sender, {})
            if r.get("action") != "job" or not r.get("job"):
                a.update(screen_intake=r.get("reason"), outcome="screen_refused_at_intake", finished=True)
                save()
                return
            a["screen_job"] = r["job"]
            save()
        j = wait(a["screen_job"], JOB_ENDS)
        a["screen"], a["screen_error"] = j.get("state"), j.get("error")
        a["screen_metrics"] = j.get("metrics")
        if j["cut_by_budget"]:
            cut(a)
            return
        files = box.call("mail-gateway", "fetch", {"job": a["screen_job"], "suffixes": [".json"],
                                                   "prefixes": ["candidate_list_", "excluded_"]})["files"]  # fmt: skip
        pats: dict[str, Any] = {}
        for fname, b64 in sorted(files.items()):
            doc = json.loads(base64.b64decode(b64).decode("utf-8"))
            for row in list_rows(doc, "excluded" if fname.startswith("excluded_") else ""):
                pats[row.pop("pid")] = row
        a["patients"] = pats
        # the run's aggregate provenance (screen.py: screen_<stem>.json; the cascade's stage log, its metrics and
        # budgets, no patient ids): the S2b breakdown and the stage counts of the evidence page
        with suppress(Exception):
            sf = box.call("mail-gateway", "fetch", {"job": a["screen_job"], "suffixes": [".json"],
                                                    "prefixes": ["screen_"]})["files"]  # fmt: skip
            for b64 in sf.values():
                _save(work / "screen" / f"{rs}.json", json.loads(base64.b64decode(b64).decode("utf-8")))
        a["outcome"] = "screened" if a["screen"] == "done" else classify(a.get("screen_error"))
        a["finished"] = True
        save()

    # the owner's ruling (2026-11-16): several protocols in flight at once ("streams"), as many as the orchestrator
    # runs jobs side by side (TB_WORKERS 4, the first kept for the ingest: 3); each protocol's flow is unchanged
    for rs_ in (p_.stem for p_ in protos):
        prog.setdefault(rs_, {"ruleset": rs_})
    if streams <= 1:
        for proto in protos:
            one(proto)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=streams, thread_name_prefix="acc") as pool:
            for f in [pool.submit(one, proto) for proto in protos]:
                f.result()
    # --- the box's pseudonyms of the placed chart numbers, for the scorer's join outside the box
    pm_p = work / "pidmap.json"
    if not pm_p.exists():
        mrns = sorted((ids.get("patients") or {}).values())
        pm: dict[str, str] = {}
        for i in range(0, len(mrns), 500):
            pm.update(box.call("adapter", "pidmap", {"mrns": mrns[i : i + 500]}))
        _save(pm_p, pm)
    _answers(work, prog)
    tick()
    counts: dict[str, int] = {"protocols": len(protos)}
    for a in prog.values():
        o = str(a.get("outcome") or "unfinished")
        counts[o] = counts.get(o, 0) + 1
    counts.setdefault("refused_by_tripwire", 0)
    counts["patients_answered"] = sum(len(a.get("patients") or {}) for a in prog.values())
    want = "compiled" if compile_only else "screened"
    att = attempts_of(prog, json.loads(clock_p.read_text(encoding="utf-8")) if clock_p.exists() else {})
    # D1: a set of no protocol never passes (acc_set refuses one above; this is the result's own rule)
    return {"set": name, "counts": counts, "pass": bool(protos) and counts.get(want, 0) == len(protos),
            "seconds": round(used(), 1), "deadline_s": deadline_s or None,
            "streams": max(1, streams), "in_flight_max": flight["max"],
            "save_give_ups": len(gave_up),
            # D-1129: what a resume with a new budget would take up, and the attempts so far
            "budget_cut": counts.get("not_run_time_budget", 0) + counts.get("unfinished", 0),
            "attempts": att, "attempts_line": att["line"]}  # fmt: skip


def _new_attempt(work: Path, clock: dict[str, Any], tag: str) -> None:
    """D-1129: the set's clock starts a new attempt (the one before kept in ``attempts``), and the attempt before's
    services lines are kept ahead of the new ones (``services.earlier.log``); box-calls.log says where it began."""
    n = int(clock.get("attempt") or 1)
    past = list(clock.get("attempts") or [])
    past.append({"attempt": n, "tag": clock.get("attempt_tag") or "", "used_s": clock.get("used_s"),
                 "deadline_s": clock.get("deadline_s")})  # fmt: skip
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    new = {**clock, "attempts": past, "attempt": n + 1, "attempt_tag": tag, "attempt_started": now, "used_s": 0.0}
    new["earlier_s"] = round(sum(float(x.get("used_s") or 0) for x in past), 1)
    svc = work / "services.log"
    if svc.exists():
        with (work / "services.earlier.log").open("a", encoding="utf-8") as fh:
            fh.write(f"== attempt {n} of the set (its services' lines, as read at its end)\n")
            fh.write(svc.read_text(encoding="utf-8", errors="replace"))
        svc.unlink()
    with suppress(OSError), (work / "box-calls.log").open("a", encoding="utf-8") as fh:
        fh.write(f"== attempt {n + 1} of the set ({tag}) from {now}Z: only the protocols the budget cut\n")
    _save(work / "set-clock.json", new)


def attempts_of(prog: dict[str, Any], clock: dict[str, Any]) -> dict[str, Any]:
    """D-1129: the set's attempts as one record: how many, the protocols finished in each (a protocol stored
    before attempts were recorded is attempt 1's), and those still cut by a budget (or not started)."""
    rows = [a for a in prog.values() if isinstance(a, dict)]
    n = max([int(clock.get("attempt") or 1)] + [int(a.get("attempt") or 1) for a in rows if a.get("finished")])
    fin = {str(i): 0 for i in range(1, n + 1)}
    cut = 0
    for a in rows:
        if not a.get("finished") or a.get("outcome") == "not_run_time_budget":
            cut += 1
        else:
            k = str(int(a.get("attempt") or 1))
            fin[k] = fin.get(k, 0) + 1
    said = "; ".join(f"in attempt {k}: {v}" if i else f"protocols finished in attempt {k}: {v}"
                     for i, (k, v) in enumerate(sorted(fin.items(), key=lambda kv: int(kv[0]))))  # fmt: skip
    return {"attempts": n, "finished_in": fin, "still_cut": cut, "line": f"attempts: {n}; {said}; still cut: {cut}"}


def acc_attempt(work: Path) -> tuple[int, str]:
    """(the set's attempt, when it started in UTC with no offset): attempt 1 has no start of its own (the step's)."""
    try:
        c = json.loads((work / "set-clock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1, ""
    n = int(c.get("attempt") or 1)
    return n, (str(c.get("attempt_started") or "") if n > 1 else "")


def merge_attempt(kind: str, into: Path, new: Path, attempt: int) -> dict[str, Any]:
    """D-1129: one attempt's gateway audit (counts) or raw traces (rows) added to the set's file. Each attempt was read
    with its own ``since`` (the attempt's start, after the attempt before was read), so the totals are the sum and the
    rows the union (a row stored twice is kept once); each attempt's own read is kept under ``attempts``. A file
    written before attempts were recorded is attempt 1's."""
    cur: dict[str, Any] = {}
    with suppress(OSError, ValueError):
        cur = json.loads(into.read_text(encoding="utf-8"))
    one = json.loads(new.read_text(encoding="utf-8"))
    per = dict(cur.get("attempts") or ({"1": {k: v for k, v in cur.items() if k != "attempts"}} if cur else {}))
    per[str(attempt)] = one
    order = sorted(per, key=int)
    out: dict[str, Any] = {"since": per[order[0]].get("since"), "attempts": per}
    if kind == "audit":
        for k in ("calls_by_prompt", "refusals"):
            tot: dict[str, int] = {}
            for a in order:
                for x, v in (per[a].get(k) or {}).items():
                    tot[x] = tot.get(x, 0) + int(v or 0)
            out[k] = tot
        jobs: dict[str, dict[str, int]] = {}
        for a in order:
            for j, codes in (per[a].get("refusals_by_job") or {}).items():
                for c, v in (codes or {}).items():
                    jobs.setdefault(j, {})[c] = jobs.setdefault(j, {}).get(c, 0) + int(v or 0)
        out["refusals_by_job"] = jobs
        out["time_unreadable"] = sum(int(per[a].get("time_unreadable") or 0) for a in order)
    else:
        seen: set[str] = set()
        rows: list[Any] = []
        for a in order:
            for r in per[a].get("traces") or []:
                k = json.dumps(r, sort_keys=True, default=str)
                if k not in seen:
                    seen.add(k)
                    rows.append(r)
        ids = {r.get("call_id") for r in rows if isinstance(r, dict)}
        out["traces"] = rows
        out["calls"] = len(ids) if None not in ids else sum(int(per[a].get("calls") or 0) for a in order)
    _save(into, out)
    return {"kind": kind, "attempt": attempt, "attempts": len(per)}


def _answers(work: Path, prog: dict[str, Any]) -> None:
    """The set's answers so far (every finished protocol; the scorer reads only these), rewritten as it goes."""
    answers = {
        rs: {
            "ruleset": rs,
            "feas": a.get("feas"),
            "feas_error": a.get("feas_error"),
            "draft": a.get("draft") or [],
            "approve": a.get("approve"),
            "approve_error": a.get("approve_error"),  # D6 (P1b): why an approval failed, kept for the reader
            "approved_in": a.get("approved_in"),
            "screen": a.get("screen"),
            "screen_error": a.get("screen_error"),
            "patients": a.get("patients") or {},
            "outcome": a.get("outcome"),
            # D-1129: the attempt that answered it (a budget cut: the attempt that cut it); none stored: attempt 1
            "attempt": int(a.get("attempt") or 1),
        }
        for rs, a in prog.items()
        if a.get("finished")
    }
    _save(work / "answers.json", answers)


def acc_progress(work: Path, built: Path) -> dict[str, Any]:
    """A set's progress for the progress line: protocols finished of all, patients answered, its clock."""
    prog = {}
    p = work / "progress.json"
    if p.exists():
        with suppress(OSError, ValueError):
            prog = json.loads(p.read_text(encoding="utf-8"))
    clock = {}
    c = work / "set-clock.json"
    if c.exists():
        with suppress(OSError, ValueError):
            clock = json.loads(c.read_text(encoding="utf-8"))
    total = len(list((built / "site" / "protocols").glob("*.txt")))
    done = sum(1 for a in prog.values() if isinstance(a, dict) and a.get("finished"))
    rows = [a for a in prog.values() if isinstance(a, dict)]
    pats = sum(len(a.get("patients") or {}) for a in rows)
    # F22 (2026-11-15): what the step's verdict and the next sets' budgets are read from: protocols compiled (a
    # draft), protocols cut by the set's time budget, and each finished SCREEN job's own seconds and patients scoped
    compiled = sum(1 for a in rows if a.get("draft"))
    cut = sum(1 for a in rows if a.get("outcome") == "not_run_time_budget")
    jobs = [
        {"patients_scoped": int(m.get("patients_scoped") or 0), "seconds": float(m.get("wall_seconds") or 0.0),
         "llm_calls": int(m.get("llm_calls") or 0)}
        for a in rows
        if a.get("screen") == "done" and isinstance(m := a.get("screen_metrics"), dict)
    ]  # fmt: skip
    return {"protocols_done": done, "protocols": total, "patients_answered": pats, "used_s": clock.get("used_s"),
            "deadline_s": clock.get("deadline_s"), "compiled": compiled, "cut_by_time": cut,
            "screen_jobs": jobs, "attempt": int(clock.get("attempt") or 1),
            "attempts_line": attempts_of(prog, clock)["line"]}  # fmt: skip


def routes_verdict(gw: dict[str, Any], emb: dict[str, Any]) -> dict[str, Any]:
    """Would the box run the accuracy set at all: the screen's judge call routes to BOTH builds of the pair (the
    judge and the verifier), and the compile's calls (ir_extract's role, concept_map's) route. The reasons when not,
    as the gateway and the registry gave them."""
    rows = {(r.get("role"), r.get("class")): r for r in gw.get("routes") or []}
    why = []
    judge = next((r for (role, _), r in rows.items() if role == "judge"), None)
    if judge is None or not judge.get("routes"):
        why.append(f"the screen's judge call does not route: {(judge or {}).get('why') or (judge or {}).get('builds')}")
    else:
        ok = [b["alias"] for b in judge.get("builds") or [] if b.get("routes")]
        if len(ok) < 2:
            why.append(f"only {ok} of the pair route for the judge's role (the verifier's second opinion needs both)")
    for role in ("extract_criteria", "concept_select"):
        r = next((x for (rl, _), x in rows.items() if rl == role), None)
        if r is None or not r.get("routes"):
            why.append(f"the compile's {role} call does not route: {(r or {}).get('why') or (r or {}).get('builds')}")
    return {
        "environment": gw.get("environment"),
        "routes": gw.get("routes"),
        "served_prompts": gw.get("served_prompts"),
        "embedder": emb.get("embedder"),
        "routes_ok": not why,
        "blocked": why,
    }


def _notes(path: str | None, facts: dict[str, Any]) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for k, v in facts.items():
                fh.write(f"{k}\t{json.dumps(v)}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle-check")
    b.add_argument("bundle", type=Path)
    b.add_argument("--notes")
    b.add_argument("--release-out", type=Path)
    b.add_argument("--host-out", type=Path)
    b.add_argument("--production", action="store_true")
    b.add_argument("--commit", default="")
    b.add_argument("--beat", type=Path)
    w = sub.add_parser("wizard")
    w.add_argument("--issue", type=Path, required=True)
    w.add_argument("--answers", type=Path, required=True)
    w.add_argument("--connect", default="")
    w.add_argument("--cacert", default="")
    w.add_argument("--wait", type=float, default=0.0, help="seconds to wait for the code on the screen")
    w.add_argument("--notes")
    d = sub.add_parser("doctor-verdict")
    d.add_argument("doctor_json", type=Path)
    d.add_argument("--expected", default="")
    d.add_argument("--notes")
    s = sub.add_parser("sample")
    s.add_argument("--names", required=True)
    s.add_argument("--ids", type=Path, required=True, help="name<TAB>container id per line")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--stop", type=Path, required=True)
    s.add_argument("--interval", type=float, default=1.0)
    s.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    m = sub.add_parser("stage-memory")
    m.add_argument("samples", type=Path)
    c = sub.add_parser("compare-lists")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    ca = sub.add_parser("cmd-arg")
    ca.add_argument("cmd_json")
    ca.add_argument("--flag", required=True, help="written --flag=--chat-template (a value that starts with --)")
    i = sub.add_parser("identity")
    i.add_argument("--box", type=Path, required=True)
    i.add_argument("--lock", type=Path, required=True)
    i.add_argument("--template-sha", default="")
    i.add_argument("--images", type=Path, required=True)
    i.add_argument("--weights-exit", type=int)
    i.add_argument("--tokens", type=Path, help="G-1's token half (g1-tokens), folded into the record")
    i.add_argument("--notes")
    gt = sub.add_parser("g1-tokens")
    gt.add_argument("--server", type=Path, required=True)
    gt.add_argument("--hf", type=Path, required=True)
    gt.add_argument("--notes")
    mp = sub.add_parser("models-place")
    mp.add_argument("--root", type=Path, required=True)
    mp.add_argument("--link", action="append", default=[], help="name=relative/target under --root")
    mp.add_argument("--template", default="", help="dest=url=sha256")
    mp.add_argument("--embed-list", type=Path)
    mp.add_argument("--embed-url", default="")
    mp.add_argument("--notes")
    au = sub.add_parser("audit-stats")
    au.add_argument("--dir", type=Path, required=True)
    au.add_argument("--since", type=float, required=True)
    ap_ = sub.add_parser("acc-progress")
    ap_.add_argument("--work", type=Path, required=True)
    ap_.add_argument("--built", type=Path, required=True)
    qv = sub.add_parser("qualify-verdict")
    qv.add_argument("record", type=Path)
    t = sub.add_parser("top-costs")
    t.add_argument("parts", type=Path)
    sub.add_parser("redact")
    mf = sub.add_parser("acc-merge-feed")
    mf.add_argument("--into", type=Path, required=True)
    mf.add_argument("sites", type=Path, nargs="+")
    ac = sub.add_parser("acc-set")
    ac.add_argument("--set", required=True)
    ac.add_argument("--built", type=Path, required=True)
    ac.add_argument("--work", type=Path, required=True)
    ac.add_argument("--onbox", type=Path, required=True)
    ac.add_argument("--dc", required=True, help="the compose command, e.g. 'docker compose --project-directory D'")
    ac.add_argument("--sender", required=True)
    ac.add_argument("--reviewer", required=True)
    ac.add_argument("--run-id", required=True)
    ac.add_argument("--compile-only", action="store_true")
    ac.add_argument("--job-minutes", type=float, default=60.0)
    ac.add_argument("--poll", type=float, default=5.0)
    ac.add_argument("--deadline-s", type=float, default=0.0, help="the set's own time budget (0: none)")
    ac.add_argument("--protocols", default="", help="comma-separated rulesets: only these protocols of the set")
    ac.add_argument("--earlier", type=Path, action="append", help="a work folder of an earlier attempt (F29)")
    ac.add_argument(
        "--streams", type=int, default=1, help="protocols in flight at once (the orchestrator's job workers)"
    )
    ac.add_argument(
        "--min-start-s",
        type=float,
        default=600.0,
        help="D4: no protocol is started with less of the set's budget left (or its measured mean, if longer)",
    )
    ac.add_argument("--new-attempt", default="", help="D-1129: a resume's tag: the set's next attempt, once per tag")
    ac.add_argument("--site-tz", default="", help="the site's zone as the box reports it (onbox env), for the replay")
    ac.add_argument("--notes")
    ac.add_argument("--beat", type=Path)
    at_ = sub.add_parser("acc-attempt")
    at_.add_argument("--work", type=Path, required=True)
    ma = sub.add_parser("acc-merge-attempt")
    ma.add_argument("--kind", choices=("audit", "traces"), required=True)
    ma.add_argument("--into", type=Path, required=True)
    ma.add_argument("--new", type=Path, required=True)
    ma.add_argument("--attempt", type=int, required=True)
    cl = sub.add_parser("acc-call")
    cl.add_argument("--dc", required=True)
    cl.add_argument("--onbox", type=Path, required=True)
    cl.add_argument("--svc", required=True)
    cl.add_argument("--cmd", dest="onbox_cmd", required=True, help="the onbox.py command")
    cl.add_argument("--arg", default="{}", help="the command's JSON argument")
    cl.add_argument("--log", type=Path, required=True)
    cl.add_argument("--beat", type=Path)
    rv = sub.add_parser("acc-routes")
    rv.add_argument("gateway_json", type=Path)
    rv.add_argument("embedder_json", type=Path)
    rv.add_argument("--notes")
    a = ap.parse_args(argv)
    if a.cmd == "acc-call":
        try:
            print(json.dumps(Box(a.dc.split(), a.onbox, a.log, a.beat).call(a.svc, a.onbox_cmd, json.loads(a.arg))))
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"acc-call {a.svc} {a.onbox_cmd}: {exc}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "acc-routes":

        def jl(p: Path) -> dict[str, Any]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return d if isinstance(d, dict) else {}

        res = routes_verdict(jl(a.gateway_json), jl(a.embedder_json))
        _notes(a.notes, {"routes_ok": res["routes_ok"], "blocked": res["blocked"], "environment": res["environment"],
                         "embedder": res["embedder"]})  # fmt: skip
        print(json.dumps(res))
        return 0 if res["routes_ok"] else 1
    if a.cmd == "audit-stats":
        print(json.dumps(audit_stats(a.dir, a.since)))
        return 0
    if a.cmd == "acc-progress":
        print(json.dumps(acc_progress(a.work, a.built)))
        return 0
    if a.cmd == "acc-attempt":
        n, since = acc_attempt(a.work)
        print(f"{n}\t{since}")
        return 0
    if a.cmd == "acc-merge-attempt":
        try:
            print(json.dumps(merge_attempt(a.kind, a.into, a.new, a.attempt)))
        except (OSError, ValueError) as exc:
            print(f"acc-merge-attempt: {exc}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "models-place":
        res = models_place(a.root, a.link, a.template, a.embed_list, a.embed_url)
        _notes(a.notes, {"models": res})
        print(json.dumps(res))
        return 0 if res["ok"] else 1
    if a.cmd in ("g1-tokens", "qualify-verdict"):

        def jl2(p: Path) -> dict[str, Any]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return d if isinstance(d, dict) else {}

        if a.cmd == "qualify-verdict":
            print(json.dumps(qualify_verdict(jl2(a.record))))
            return 0
        res = g1_tokens(jl2(a.server), jl2(a.hf))
        _notes(a.notes, {"tokens_verdicts": res["verdicts"], "tokens_not_run": res["not_run"],
                         "tokens_pass": res["pass"]})  # fmt: skip
        print(json.dumps(res))
        return 0
    if a.cmd == "redact":
        sys.stdout.writelines(redact(sys.stdin))
        return 0
    if a.cmd == "acc-merge-feed":
        try:
            print(json.dumps(merge_feed(a.into, a.sites)))
        except ValueError as exc:
            print(f"acc-merge-feed: {exc}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "acc-set":
        a.work.mkdir(parents=True, exist_ok=True)
        box = Box(a.dc.split(), a.onbox, a.work / "box-calls.log", a.beat)
        try:
            res = acc_set(a.set, a.built, a.work, box, sender=a.sender, reviewer=a.reviewer, run_id=a.run_id,
                          compile_only=a.compile_only, job_s=a.job_minutes * 60, poll_s=a.poll,
                          deadline_s=a.deadline_s,
                          protocols=[x for x in a.protocols.split(",") if x] or None,
                          earlier=a.earlier, streams=a.streams, min_start_s=a.min_start_s,
                          new_attempt=a.new_attempt, site_tz=a.site_tz)  # fmt: skip
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"acc-set {a.set}: {exc}", file=sys.stderr)
            return 1
        _notes(a.notes, res)
        print(json.dumps(res))
        return 0
    if a.cmd == "bundle-check":
        res = bundle_check(
            a.bundle,
            production=a.production,
            commit=a.commit,
            release_out=a.release_out,
            host_out=a.host_out,
            beat=a.beat,
        )
        _notes(a.notes, res)
        for r in res["refused"]:
            print("TB-BUNDLE-REFUSED:", r, file=sys.stderr)
        print(json.dumps(res))
        return 1 if res["refused"] else 0
    if a.cmd == "wizard":
        end = time.time() + a.wait
        while True:
            try:
                read_screen(a.issue)
                break
            except (OSError, ValueError):
                if time.time() >= end:
                    raise
                time.sleep(1)
        answers = json.loads(a.answers.read_text(encoding="utf-8"))
        try:
            res = wizard(a.issue, answers, a.connect, a.cacert)
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"wizard: {exc}", file=sys.stderr)
            return 1
        _notes(a.notes, res)
        print(json.dumps(res))
        return 0
    if a.cmd == "doctor-verdict":
        try:
            checks = json.loads(a.doctor_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"doctor-verdict: no doctor JSON ({exc})", file=sys.stderr)
            return 1
        res = doctor_verdict(checks if isinstance(checks, list) else [], a.expected.split(","))
        _notes(a.notes, res)
        print(json.dumps(res))
        return 0 if res["pass"] else 1
    if a.cmd == "sample":
        ids = dict(line.split("\t", 1) for line in a.ids.read_text().splitlines() if "\t" in line)
        sample(
            [n for n in a.names.split(",") if n],
            {k: v.strip() for k, v in ids.items()},
            a.out,
            a.stop,
            a.interval,
            a.cgroup_root,
        )
        return 0
    if a.cmd == "stage-memory":
        print(json.dumps(stage_memory(a.samples.read_text(encoding="utf-8").splitlines())))
        return 0
    if a.cmd == "compare-lists":
        print(json.dumps(compare_lists(json.loads(a.a.read_text()), json.loads(a.b.read_text()))))
        return 0
    if a.cmd == "cmd-arg":
        try:
            cmd = json.loads(a.cmd_json)
        except ValueError:
            cmd = []
        print(cmd_arg(cmd if isinstance(cmd, list) else [], a.flag))
        return 0
    if a.cmd == "identity":

        def load(p: Path) -> dict[str, Any]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return d if isinstance(d, dict) else {}

        res = identity(load(a.box), load(a.lock), a.template_sha, load(a.images), a.weights_exit)
        if a.tokens is not None:  # the token half beside the identity half: each its own verdict
            res["token_identity"] = load(a.tokens)
        _notes(a.notes, {"identity": res, "pass": res["pass"]})
        print(json.dumps(res))
        return 0
    print(json.dumps(top_costs(a.parts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
