"""CLI for the supply-chain gates; see ``tools/supply_chain/__init__.py``. Exit 0 pass, 1 fail, 2 usage/tool error."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from tools.supply_chain import allowlist, licences, lock, sbom, vulns


def _today(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def _allow(args: argparse.Namespace) -> tuple[allowlist.Allowlist, list[str]]:
    return allowlist.load(Path(args.allowlist), today=_today(args.today))


def cmd_lock_export(args: argparse.Namespace) -> int:
    text = lock.export_requirements()
    lock.REQUIREMENTS_LOCK.write_text(text, encoding="utf-8")
    problems = lock.check_requirements_hashes(text)
    for p in problems:
        print(f"lock-export: {p}", file=sys.stderr)
    print(f"lock-export: wrote {lock.REQUIREMENTS_LOCK.relative_to(lock.ROOT)}")
    return 1 if problems else 0


def cmd_lock_check(args: argparse.Namespace) -> int:
    problems = lock.lock_check(offline=args.offline, skip_resolve=args.skip_resolve)
    for p in problems:
        print(f"lock-check: {p}", file=sys.stderr)
    print(f"lock-check: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


def cmd_allowlist_check(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    for e in errors:
        print(f"allowlist-check: {e}", file=sys.stderr)
    n = len(allow.vulnerabilities) + len(allow.licences)
    print(f"allowlist-check: {'FAIL' if errors else 'PASS'} ({n} valid entries)")
    return 1 if errors else 0


def _finish(result: vulns.GateResult, title: str, allow_errors: list[str]) -> int:
    result.errors[:0] = [f"allow-list: {e}" for e in allow_errors]
    print(result.render(title))
    return 0 if result.ok else 1


def cmd_pip_audit_gate(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    return _finish(vulns.pip_audit_gate(Path(args.report), allow), "pip-audit gate", errors)


def cmd_trivy_gate(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    sev = frozenset(s.strip().upper() for s in args.severity.split(",") if s.strip())
    unknown = sev - set(vulns.SEVERITIES)
    if unknown:
        print(f"trivy-gate: unknown severity {sorted(unknown)}", file=sys.stderr)
        return 2
    result = vulns.trivy_gate([Path(p) for p in args.reports], allow, severities=sev, fail_unfixed=args.fail_unfixed)
    return _finish(result, "Trivy gate", errors)


def cmd_trivy_scan(args: argparse.Namespace) -> int:
    """Run Trivy offline for each image (DB already in --cache-dir), then the gate on what it wrote."""
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for image in args.image:
        out = out_dir / sbom.file_name(image).replace(".cdx.json", ".trivy.json")
        cmd = vulns.trivy_offline_command(image, Path(args.cache_dir), out)
        try:
            proc = subprocess.run(cmd, check=False)
        except FileNotFoundError:
            print("trivy-scan: trivy is not on PATH (https://trivy.dev); nothing was scanned", file=sys.stderr)
            return 2
        if proc.returncode != 0:
            print(f"trivy-scan: trivy failed on {image} (exit {proc.returncode})", file=sys.stderr)
            return 2
        reports.append(str(out))
    args.reports = reports
    return cmd_trivy_gate(args)


def cmd_sbom(args: argparse.Namespace) -> int:
    try:
        problems = sbom.run(Path(args.out), lock=Path(args.lock) if args.lock else None, images=args.image)
    except sbom.SbomError as exc:
        print(f"sbom: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"sbom: {p}", file=sys.stderr)
    print(f"sbom: {'FAIL' if problems else 'PASS'} -> {args.out}")
    return 1 if problems else 0


def cmd_licences(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    docs = {}
    for p in args.sboms:
        try:
            doc = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"licences: cannot read {p}: {exc}", file=sys.stderr)
            return 2
        bad = sbom.validate(doc)
        if bad:
            print(f"licences: {p}: {'; '.join(bad)}", file=sys.stderr)
            return 2
        docs[Path(p).name] = doc
    rows = licences.report(docs, allow, gate_os_packages=args.gate_os_packages)
    text = licences.render(rows)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    for e in errors:
        print(f"licences: allow-list: {e}", file=sys.stderr)
    return 1 if errors or any(r.failing for r in rows) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.supply_chain", description=__doc__)
    ap.add_argument("--allowlist", default=str(allowlist.ALLOWLIST), help="allow-list YAML")
    ap.add_argument("--today", help="ISO date to judge review_by against (default: today)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("lock-export", help="write deploy/requirements.lock from uv.lock").set_defaults(fn=cmd_lock_export)
    p = sub.add_parser("lock-check", help="fail when a lock is stale or lacks hashes")
    p.add_argument("--offline", action="store_true", help="uv lock --check without the network")
    p.add_argument("--skip-resolve", action="store_true", help="skip `uv lock --check` (hash and export checks only)")
    p.set_defaults(fn=cmd_lock_check)
    sub.add_parser("allowlist-check", help="validate the allow-list").set_defaults(fn=cmd_allowlist_check)
    p = sub.add_parser("pip-audit-gate", help="gate a pip-audit JSON report")
    p.add_argument("report")
    p.set_defaults(fn=cmd_pip_audit_gate)
    for name, fn in (("trivy-gate", cmd_trivy_gate), ("trivy-scan", cmd_trivy_scan)):
        p = sub.add_parser(name, help="gate Trivy JSON reports" if name == "trivy-gate" else "Trivy offline + gate")
        if name == "trivy-gate":
            p.add_argument("reports", nargs="+")
        else:
            p.add_argument("--image", action="append", required=True)
            p.add_argument("--cache-dir", required=True, help="Trivy cache with db/ and java-db/ (from the media)")
            p.add_argument("--out", default="build/supply-chain")
        p.add_argument("--severity", default="CRITICAL,HIGH", help="severities that fail (default CRITICAL,HIGH)")
        p.add_argument("--fail-unfixed", action="store_true", help="also fail on findings with no fixed version")
        p.set_defaults(fn=fn)
    p = sub.add_parser("sbom", help="Syft CycloneDX SBOM for the lock and each image")
    p.add_argument("--out", default="dist/sbom")
    p.add_argument("--lock", default=str(lock.REQUIREMENTS_LOCK))
    p.add_argument("--image", action="append", default=[])
    p.set_defaults(fn=cmd_sbom)
    p = sub.add_parser("licences", help="licence report from CycloneDX SBOMs")
    p.add_argument("sboms", nargs="+")
    p.add_argument("--out", help="write the Markdown report here too")
    p.add_argument("--gate-os-packages", action="store_true", help="fail on distro (deb/apk/rpm) packages too")
    p.set_defaults(fn=cmd_licences)

    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except lock.LockError as exc:
        print(f"{args.cmd}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
