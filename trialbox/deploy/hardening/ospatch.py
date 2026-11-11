"""Offline OS patch bundles (T-634, D-408; OPS-024). Standard library only: it runs on the host's python3.

An OS patch bundle is an ordinary signed update bundle (``tools/sign_bundle.py``) whose payloads are all of kind
``other`` under ``ospatch/``: ``ospatch/ospatch.json`` and a flat apt repository ``ospatch/repo/`` (the ``.deb``
files and their ``Packages`` index). The signature covers the index and every package, so apt reads the repository
as ``[trusted=yes]``: the trust is the vendor key's, checked by ``tools/verify_update.py`` before anything is staged.

    # vendor side: a dated snapshot of the security updates for one release and architecture
    python3 deploy/hardening/ospatch.py make --debs DIR --out PAYLOAD --snapshot 2026-11-01 \\
        --distro ubuntu --version 24.04 --arch amd64
    python3 tools/sign_bundle.py build --key ... --id ospatch-2026-11-01 --release-seq N --out ospatch.tar \\
        other:PAYLOAD/ospatch.json=ospatch/ospatch.json other:PAYLOAD/repo/Packages=ospatch/repo/Packages ...
    # the box (hospital IT, in the patch window of RUNBOOK §24)
    tools/apply_update.sh ospatch ospatch.tar [--dry-run] [--conf deploy/site/hardening.conf]
    tools/apply_update.sh ospatch-check          # after the reboot: doctor and the canary

``apply`` (after the verifier staged the bundle): the snapshot must be for this host's system and architecture
(``/etc/os-release``, ``dpkg --print-architecture``) and newer than the last one applied (no going back); held
packages (the NVIDIA driver, D-373) are left as they are; only packages already installed are upgraded. Then
``apt-get install --only-upgrade`` from the staged repository alone (no other source is read), a record in
``deploy/updates/ospatch/``, and the reboot plan: when a reboot is needed (``/var/run/reboot-required`` or a kernel
package), ``REBOOT_PENDING.json`` is written and the canary waits for ``ospatch-check`` after the reboot; otherwise
the canary runs at once. A failing canary is exit 1: roll the patch back with hospital IT and open a P1 (RUNBOOK §24).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "tb-ospatch/1"
DEFAULT_CANARY = (
    "python3 -m tools.trialbox doctor --env-file deploy/.env && "
    "docker compose --project-directory deploy exec -T orchestrator python -m orchestrator.selftest"
)
_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_SNAPSHOT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KERNEL = ("linux-image-", "linux-modules-", "linux-generic", "linux-headers-")


class Refused(Exception):
    pass


def host_root() -> Path:
    return Path(os.environ.get("TB_HOST_ROOT") or "/")


def _sh(cmd: list[str], check: bool = True) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and r.returncode != 0:
        raise Refused(f"{' '.join(cmd[:3])} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def os_release(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    p = root / "etc/os-release"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def conf_value(conf: Path | None, name: str) -> str | None:
    """One variable of the site's shell-syntax file, without running it."""
    if not conf or not conf.is_file():
        return None
    val = None
    for line in conf.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(f"{name}="):
            parts = shlex.split(s[len(name) + 1 :], comments=True)
            val = parts[0] if parts else ""
    return val


# ------------------------------------------------------------------------------------------------ make (vendor)
def make(debs: Path, out: Path, snapshot: str, distro: str, version: str, arch: str) -> dict[str, Any]:
    if not _SNAPSHOT.match(snapshot):
        raise Refused(f"--snapshot {snapshot!r} is not YYYY-MM-DD")
    repo = out / "repo"
    repo.mkdir(parents=True, exist_ok=False)
    stanzas, packages = [], []
    for deb in sorted(debs.glob("*.deb")):
        fields = _sh(["dpkg-deb", "-f", str(deb)]).rstrip("\n")
        ctl = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", fields, flags=re.M))
        name, ver = ctl.get("Package", ""), ctl.get("Version", "")
        if not _NAME.match(name) or not ver:
            raise Refused(f"{deb.name}: no package name or version")
        data = deb.read_bytes()
        shutil.copyfile(deb, repo / deb.name)
        stanzas.append(
            f"{fields}\nFilename: ./{deb.name}\nSize: {len(data)}\nSHA256: {hashlib.sha256(data).hexdigest()}\n"
        )
        packages.append({"name": name, "version": ver, "file": deb.name})
    if not packages:
        raise Refused(f"no .deb in {debs}")
    (repo / "Packages").write_text("\n".join(stanzas), encoding="utf-8")
    meta = {"format": FORMAT, "snapshot": snapshot, "distro": distro, "version": version, "arch": arch,
            "packages": packages}  # fmt: skip
    (out / "ospatch.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


# ------------------------------------------------------------------------------------------------ apply (the box)
def read_meta(stage: Path) -> dict[str, Any]:
    p = stage / "other" / "ospatch" / "ospatch.json"
    if not p.is_file():
        raise Refused("not an OS patch bundle (no ospatch/ospatch.json among its payloads)")
    meta = json.loads(p.read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT:
        raise Refused(f"ospatch.json format {meta.get('format')!r}, expected {FORMAT}")
    if not _SNAPSHOT.match(str(meta.get("snapshot", ""))):
        raise Refused("ospatch.json has no snapshot date")
    for pkg in meta.get("packages") or []:
        if not _NAME.match(str(pkg.get("name", ""))):
            raise Refused(f"ospatch.json: bad package name {pkg.get('name')!r}")
        if not (stage / "other" / "ospatch" / "repo" / Path(str(pkg.get("file", ""))).name).is_file():
            raise Refused(f"ospatch.json names {pkg.get('file')} but the bundle does not carry it")
    if not meta.get("packages"):
        raise Refused("ospatch.json lists no package")
    if not (stage / "other" / "ospatch" / "repo" / "Packages").is_file():
        raise Refused("the bundle has no repo/Packages index")
    return meta


def last_snapshot(state: Path) -> str | None:
    done = sorted(p.stem for p in state.glob("*.json") if _SNAPSHOT.match(p.stem))
    return done[-1] if done else None


def plan(meta: dict[str, Any], root: Path, state: Path) -> dict[str, Any]:
    rel = os_release(root)
    if (rel.get("ID"), rel.get("VERSION_ID")) != (meta.get("distro"), meta.get("version")):
        raise Refused(f"the snapshot is for {meta.get('distro')} {meta.get('version')}; this host runs "
                      f"{rel.get('ID', '?')} {rel.get('VERSION_ID', '?')}")  # fmt: skip
    arch = _sh(["dpkg", "--print-architecture"]).strip()
    if arch != meta.get("arch"):
        raise Refused(f"the snapshot is for {meta.get('arch')}; this host is {arch}")
    last = last_snapshot(state)
    if last and meta["snapshot"] <= last:
        raise Refused(f"snapshot {meta['snapshot']} is not newer than {last}, the last one applied (no going back)")
    held = set(_sh(["apt-mark", "showhold"], check=False).split())
    names = sorted({p["name"] for p in meta["packages"]})
    installed = []
    for n in names:
        status = _sh(["dpkg-query", "-W", "-f=${Status}", n], check=False)
        if status.strip().endswith("installed") and "not-installed" not in status:
            installed.append(n)
    upgrade = [n for n in installed if n not in held]
    return {"snapshot": meta["snapshot"], "upgrade": upgrade, "held": sorted(set(installed) & held),
            "not_installed": [n for n in names if n not in installed],
            "kernel": any(n.startswith(KERNEL) for n in upgrade)}  # fmt: skip


def apt_upgrade(stage: Path, names: list[str]) -> None:
    repo = stage / "other" / "ospatch" / "repo"
    with tempfile.TemporaryDirectory(prefix="tb-ospatch-") as tmp:
        t = Path(tmp)
        (t / "lists" / "partial").mkdir(parents=True)
        (t / "sources.list").write_text(f"deb [trusted=yes] file:{repo} ./\n", encoding="utf-8")
        opts = [f"-o=Dir::Etc::SourceList={t / 'sources.list'}", "-o=Dir::Etc::SourceParts=/dev/null",
                f"-o=Dir::State::Lists={t / 'lists'}", "-o=APT::Get::List-Cleanup=0",
                "-o=Dpkg::Options::=--force-confold"]  # fmt: skip
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        upgrade = ["apt-get", *opts, "-y", "--no-install-recommends", "install", "--only-upgrade", *names]
        for cmd in (["apt-get", *opts, "update"], upgrade):
            r = subprocess.run(cmd, env=env, check=False)
            if r.returncode != 0:
                raise Refused(f"apt-get {cmd[len(opts) + 1]} failed (exit {r.returncode}, above)")


def canary(root_dir: Path, conf: Path | None) -> bool:
    cmd = conf_value(conf, "CANARY_CMD") or DEFAULT_CANARY
    print(f"    canary: {cmd}", flush=True)
    return subprocess.run(["sh", "-c", cmd], cwd=root_dir, check=False).returncode == 0


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_apply(a: argparse.Namespace) -> int:
    root = host_root()
    state = Path(a.deploy) / "updates" / "ospatch"
    stage = Path(a.stage)
    conf = Path(a.conf) if a.conf else None
    meta = read_meta(stage)
    if (state / "REBOOT_PENDING.json").exists():
        raise Refused("an OS patch waits for its reboot and canary: reboot, then tools/apply_update.sh ospatch-check")
    p = plan(meta, root, state)
    print(f"OS patch snapshot {p['snapshot']}: {len(p['upgrade'])} package(s) to upgrade")
    for n in p["upgrade"]:
        print(f"  would upgrade {n}" if a.dry_run else f"  upgrade {n}")
    for n in p["held"]:
        print(f"  held, left as it is: {n}")
    if p["not_installed"]:
        print(f"  not installed here (only as dependencies): {', '.join(p['not_installed'])}")
    if a.dry_run:
        print(f"dry run: nothing changed; a reboot would {'be' if p['kernel'] else 'maybe not be'} needed")
        return 0
    rec = {"snapshot": p["snapshot"], "started": _now(), "upgraded": p["upgrade"], "held": p["held"]}
    _write(state / "IN_PROGRESS.json", rec)
    if p["upgrade"]:
        apt_upgrade(stage, p["upgrade"])
    rec["applied"] = _now()
    reboot = p["kernel"] or (root / "var/run/reboot-required").exists() or (root / "run/reboot-required").exists()
    _write(state / f"{p['snapshot']}.json", {**rec, "reboot": reboot, "canary": "pending"})
    (state / "IN_PROGRESS.json").unlink()
    if reboot:
        _write(state / "REBOOT_PENDING.json", rec)
        print("reboot needed. In the window: systemctl stop trialbox; reboot. After it: "
              "tools/apply_update.sh ospatch-check (doctor and the canary)")  # fmt: skip
        return 0
    return after(Path(a.deploy), conf, p["snapshot"])


def after(deploy: Path, conf: Path | None, snapshot: str | None = None) -> int:
    state = deploy / "updates" / "ospatch"
    pending = state / "REBOOT_PENDING.json"
    if snapshot is None:
        if not pending.exists():
            snapshot = last_snapshot(state)
            if snapshot is None:
                print("no OS patch has been applied on this box")
                return 0
        else:
            snapshot = json.loads(pending.read_text(encoding="utf-8"))["snapshot"]
    ok = canary(deploy.parent, conf)
    rec_path = state / f"{snapshot}.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {"snapshot": snapshot}
    rec.update({"canary": "passed" if ok else "failed", "checked": _now()})
    _write(rec_path, rec)
    if ok:
        pending.unlink(missing_ok=True)
        print(f"OS patch {snapshot}: the canary passed")
        return 0
    print(f"OS patch {snapshot}: the canary FAILED. Roll the patch back with hospital IT and open a P1 "
          "(docs/runbook/24-patch-policy.md)", file=sys.stderr)  # fmt: skip
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ospatch.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="vendor: the payload folder of a snapshot")
    m.add_argument("--debs", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--snapshot", required=True)
    m.add_argument("--distro", default="ubuntu")
    m.add_argument("--version", default="24.04")
    m.add_argument("--arch", default="amd64")
    p = sub.add_parser("apply", help="the box: apply a staged, verified OS patch bundle")
    p.add_argument("--stage", required=True)
    p.add_argument("--deploy", required=True)
    p.add_argument("--conf")
    p.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check", help="the box: after the reboot, the canary")
    c.add_argument("--deploy", required=True)
    c.add_argument("--conf")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "make":
            meta = make(Path(a.debs), Path(a.out), a.snapshot, a.distro, a.version, a.arch)
            print(f"ospatch {meta['snapshot']}: {len(meta['packages'])} package(s) in {a.out}")
            return 0
        if a.cmd == "apply":
            return cmd_apply(a)
        return after(Path(a.deploy), Path(a.conf) if a.conf else None)
    except Refused as exc:
        print(f"ospatch REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
