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
      work/answers.json in the shape tools.public_accuracy.score reads, and work/pidmap.json

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
import time
import urllib.parse
from collections.abc import Iterable
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
            verdicts.append(
                {
                    "id": c.get("id"),
                    "verdict": c.get("verdict"),
                    "basis": c.get("basis"),
                    "quote": ev.get("quote") or ev.get("text") if isinstance(ev, dict) else None,
                }
            )
        out.append(
            {"pid": r["pid"], "tier": r.get("tier") or tier, "actions": list(r.get("actions") or []),
             "verdicts": verdicts}
        )  # fmt: skip
    return out


class Box:
    """The installed box as the accuracy set reaches it: onbox.py piped into a service's container."""

    def __init__(self, dc: list[str], onbox: Path, log: Path, beat: Path | None) -> None:
        self.dc, self.onbox, self.log, self.beat = dc, onbox, log, beat

    def call(self, svc: str, cmd: str, arg: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        import subprocess

        b64 = base64.b64encode(json.dumps(arg or {}, ensure_ascii=False).encode()).decode()
        argv = [*self.dc, "exec", "-T", svc, "python", "-", cmd, b64]
        with self.log.open("a", encoding="utf-8") as lf:
            lf.write(f"+ {svc} onbox {cmd} {time.strftime('%H:%M:%S')}\n")
            lf.flush()
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=lf, text=True)
            stdout, _ = p.communicate(self.onbox.read_text(encoding="utf-8"), timeout=timeout)
            lf.write(stdout[-4000:])
        if self.beat is not None:
            self.beat.touch()
        if p.returncode != 0:
            raise RuntimeError(f"{svc} onbox {cmd}: exit {p.returncode}")
        last = [x for x in stdout.splitlines() if x.startswith(("{", "["))]
        if not last:
            raise RuntimeError(f"{svc} onbox {cmd}: no answer")
        return json.loads(last[-1])


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
) -> dict[str, Any]:
    """One accuracy set on the installed box (see the module docstring). Resumable from ``work/progress.json``."""
    ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
    protos = sorted((built / "site" / "protocols").glob("*.txt"))
    prog_p = work / "progress.json"
    prog: dict[str, Any] = json.loads(prog_p.read_text(encoding="utf-8")) if prog_p.exists() else {}

    def mid(rs: str, kind: str) -> str:
        return f"<acc-{run_id}-{name}-{rs}-{kind}@trialbox.invalid>".replace(" ", "")

    def send(rs: str, kind: str, subject: str, sender_: str, attach: dict[str, bytes]) -> dict[str, Any]:
        files = {k: base64.b64encode(v).decode() for k, v in attach.items()}
        r = box.call(
            "mail-gateway", "send", {"from": sender_, "subject": subject, "mid": mid(rs, kind), "attach": files}
        )
        return dict(r)

    def wait(job: str, until: tuple[str, ...]) -> dict[str, Any]:
        return dict(box.call("mail-gateway", "wait", {"job": job, "until": list(until), "timeout_s": job_s,
                                                      "poll_s": poll_s}))  # fmt: skip

    for proto in protos:
        rs = proto.stem
        a = prog.setdefault(rs, {"ruleset": rs})
        if a.get("finished"):
            continue
        # --- FEAS with the protocol attached, from the coordinator
        if "feas_job" not in a:
            r = send(rs, "feas", f"FEAS {rs}", sender, {proto.name: proto.read_bytes()})
            a["feas_intake"] = {k: r.get(k) for k in ("action", "reason")}
            if r.get("action") != "job" or not r.get("job"):
                a.update(outcome="refused_at_intake", finished=True)
                _save(prog_p, prog)
                continue
            a["feas_job"] = r["job"]
            _save(prog_p, prog)
        j = wait(a["feas_job"], FEAS_ENDS)
        a["feas"], a["feas_error"], a["version"] = j.get("state"), j.get("error"), j.get("ruleset_version")
        if j.get("waited") == "timeout":
            a.update(outcome="timeout_feas", finished=True)
            _save(prog_p, prog)
            continue
        files = box.call("mail-gateway", "fetch", {"job": a["feas_job"], "suffixes": [".xlsx", "-draft.zip"],
                                                   "prefixes": ["review_", "ruleset_"]})["files"]  # fmt: skip
        z = next((v for k, v in files.items() if k.endswith("-draft.zip")), None)
        a["draft"] = draft_criteria(base64.b64decode(z)) if z else []
        xlsx = next(((k, v) for k, v in files.items() if k.endswith(".xlsx")), None)
        if a["feas"] != "awaiting_approval" and not xlsx:
            a.update(outcome=classify(a.get("feas_error")) if a["feas"] == "failed" else f"feas_{a['feas']}",
                     finished=True)  # fmt: skip
            _save(prog_p, prog)
            continue
        if compile_only:
            a.update(outcome="compiled", finished=True)
            _save(prog_p, prog)
            continue
        # --- APPROVE by the box's named reviewer, the review workbook as it came
        if "approve_job" not in a:
            assert xlsx is not None
            subject = f"APPROVE {rs}" + (f" version={a['version']}" if a.get("version") else "")
            r = send(rs, "approve", subject, reviewer, {"review.xlsx": base64.b64decode(xlsx[1])})
            if r.get("action") != "job" or not r.get("job"):
                a.update(approve_intake=r.get("reason"), outcome="approve_refused_at_intake", finished=True)
                _save(prog_p, prog)
                continue
            a["approve_job"] = r["job"]
            _save(prog_p, prog)
        j = wait(a["approve_job"], JOB_ENDS)
        a["approve"], a["approve_error"] = j.get("state"), j.get("error")
        if a["approve"] != "done":
            a.update(outcome="approve_" + str(a["approve"]), finished=True)
            _save(prog_p, prog)
            continue
        # --- SCREEN scoped to the trial's investigator (the mail grammar's pract=)
        if "screen_job" not in a:
            pi = (ids.get("investigators") or {}).get(rs, "")
            r = send(rs, "screen", f"SCREEN {rs}" + (f" pract={pi}" if pi else ""), sender, {})
            if r.get("action") != "job" or not r.get("job"):
                a.update(screen_intake=r.get("reason"), outcome="screen_refused_at_intake", finished=True)
                _save(prog_p, prog)
                continue
            a["screen_job"] = r["job"]
            _save(prog_p, prog)
        j = wait(a["screen_job"], JOB_ENDS)
        a["screen"], a["screen_error"] = j.get("state"), j.get("error")
        a["screen_metrics"] = j.get("metrics")
        files = box.call("mail-gateway", "fetch", {"job": a["screen_job"], "suffixes": [".json"],
                                                   "prefixes": ["candidate_list_", "excluded_"]})["files"]  # fmt: skip
        pats: dict[str, Any] = {}
        for fname, b64 in sorted(files.items()):
            doc = json.loads(base64.b64decode(b64).decode("utf-8"))
            for row in list_rows(doc, "excluded" if fname.startswith("excluded_") else ""):
                pats[row.pop("pid")] = row
        a["patients"] = pats
        a["outcome"] = "screened" if a["screen"] == "done" else classify(a.get("screen_error"))
        a["finished"] = True
        _save(prog_p, prog)
    # --- the box's pseudonyms of the placed chart numbers, for the scorer's join outside the box
    pm_p = work / "pidmap.json"
    if not pm_p.exists():
        mrns = sorted((ids.get("patients") or {}).values())
        pm: dict[str, str] = {}
        for i in range(0, len(mrns), 500):
            pm.update(box.call("adapter", "pidmap", {"mrns": mrns[i : i + 500]}))
        _save(pm_p, pm)
    answers = {
        rs: {
            "ruleset": rs,
            "feas": a.get("feas"),
            "feas_error": a.get("feas_error"),
            "draft": a.get("draft") or [],
            "approve": a.get("approve"),
            "screen": a.get("screen"),
            "screen_error": a.get("screen_error"),
            "patients": a.get("patients") or {},
            "outcome": a.get("outcome"),
        }
        for rs, a in prog.items()
    }
    _save(work / "answers.json", answers)
    counts: dict[str, int] = {"protocols": len(protos)}
    for a in prog.values():
        o = str(a.get("outcome") or "unfinished")
        counts[o] = counts.get(o, 0) + 1
    counts.setdefault("refused_by_tripwire", 0)
    counts["patients_answered"] = sum(len(a.get("patients") or {}) for a in prog.values())
    want = "compiled" if compile_only else "screened"
    return {"set": name, "counts": counts, "pass": counts.get(want, 0) == len(protos)}


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
    i.add_argument("--notes")
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
    ac.add_argument("--notes")
    ac.add_argument("--beat", type=Path)
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
                          compile_only=a.compile_only, job_s=a.job_minutes * 60, poll_s=a.poll)  # fmt: skip
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
        _notes(a.notes, {"identity": res, "pass": res["pass"]})
        print(json.dumps(res))
        return 0
    print(json.dumps(top_costs(a.parts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
