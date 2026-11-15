"""CLI for the supply-chain gates; see ``tools/supply_chain/__init__.py``. Exit 0 pass, 1 fail, 2 usage/tool error.

Dates are the machine's date (``allowlist.today()``); there is no date override.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from tools.supply_chain import allowlist, licences, lock, release, sbom, scanners, vulns


def _allow(args: argparse.Namespace) -> tuple[allowlist.Allowlist, list[str]]:
    return allowlist.load(Path(args.allowlist), today=allowlist.today())


def cmd_lock_export(args: argparse.Namespace) -> int:
    text = lock.export_requirements()
    lock.REQUIREMENTS_LOCK.write_text(text, encoding="utf-8")
    lock.EMBED_LOCK.write_text(lock.export_requirements(extra=lock.EMBED_EXTRA), encoding="utf-8")  # ENG-003 (D-563)
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
    n = len(allow.vulnerabilities) + len(allow.licences) + len(allow.budgets) + len(allow.os_packages_unreadable)
    print(f"allowlist-check: {'FAIL' if errors else 'PASS'} ({n} valid entries)")
    return 1 if errors else 0


def _finish(result: vulns.GateResult, title: str, allow_errors: list[str]) -> int:
    result.errors[:0] = [f"allow-list: {e}" for e in allow_errors]
    print(result.render(title))
    return 0 if result.ok else 1


def cmd_pip_audit_gate(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    expected = vulns.lock_targets(Path(args.lock).read_text(encoding="utf-8"))
    return _finish(vulns.pip_audit_gate(Path(args.report), allow, expected), "pip-audit gate", errors)


def _severities(text: str) -> frozenset[str] | None:
    sev = frozenset(s.strip().upper() for s in text.split(",") if s.strip())
    return sev if sev and sev <= set(vulns.SEVERITIES) else None


def cmd_trivy_gate(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    sev = _severities(args.severity)
    if sev is None:
        print(f"trivy-gate: severities must be among {', '.join(vulns.SEVERITIES)}", file=sys.stderr)
        return 2
    db_errors, _ = vulns.db_problems(Path(args.cache_dir), dt.datetime.now(dt.UTC))
    result = vulns.trivy_gate(
        [Path(p) for p in args.reports], allow, severities=sev, fail_unfixed=args.fail_unfixed, db_errors=db_errors
    )
    return _finish(result, "Trivy gate", errors)


def cmd_release_gates(args: argparse.Namespace) -> int:
    allow, errors = _allow(args)
    sev = _severities(args.severity)
    if sev is None:
        print(f"release-gates: severities must be among {', '.join(vulns.SEVERITIES)}", file=sys.stderr)
        return 2
    targets = [release.parse_target(t) for t in args.image]
    missing = release.missing_local(targets)
    if missing:
        for m in missing:
            print(f"release-gates: {m}", file=sys.stderr)
        return 1
    record = release.run_gates(
        targets,
        cache_dir=Path(args.cache_dir),
        out_dir=Path(args.out),
        sbom_dir=Path(args.sbom_dir),
        allow=allow,
        allow_errors=errors,
        lock_sbom=Path(args.lock_sbom) if args.lock_sbom else None,
        insecure=args.insecure,
        severities=sev,
        fail_unfixed=args.fail_unfixed,
        vuln_mode=args.vuln_mode,
    )
    print(release.render(record))
    return 0 if record["ok"] else 1


def cmd_bundle_check(args: argparse.Namespace) -> int:
    try:
        record = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"bundle-check: cannot read {args.gates}: {exc}", file=sys.stderr)
        return 1
    images: dict[str, tuple[str, ...]] = {}
    platforms: dict[str, str] = {}
    for ref in args.image:
        try:
            local = release.inspect_local(ref)
        except vulns.ReportError as exc:
            print(f"bundle-check: {exc}", file=sys.stderr)
            return 1
        # D-830: the Id and every repo digest (on the containerd store the Id is the index digest), with the platform
        images[ref] = (local["image_id"], *(str(d).rsplit("@", 1)[-1] for d in local["repo_digests"]))
        platforms[ref] = local["platform"]
    problems = release.bundle_problems(record, images, platforms=platforms)
    for p in problems:
        print(f"bundle-check: {p}", file=sys.stderr)
    print(f"bundle-check: {'FAIL' if problems else 'PASS'} ({len(images)} images)")
    return 1 if problems else 0


def cmd_lock_sbom(args: argparse.Namespace) -> int:
    env, _ = vulns.scanner_env()
    problems = sbom.lock_sbom(Path(args.env), Path(args.lock), Path(args.out), sbom.syft_env(env))
    for p in problems:
        print(f"lock-sbom: {p}", file=sys.stderr)
    print(f"lock-sbom: {'FAIL' if problems else 'PASS'} -> {args.out}")
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
    result = licences.evaluate(docs, allow, gate_os_packages=args.gate_os_packages)
    text = licences.render(result)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    for e in errors:
        print(f"licences: allow-list: {e}", file=sys.stderr)
    return 1 if errors or not result.ok else 0


def cmd_scanners(args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    try:
        for tool in ("syft", "trivy"):
            path = scanners.fetch(tool, dest)
            print(f"scanners: {tool} -> {path}")
    except (scanners.ScannerError, OSError) as exc:
        print(f"scanners: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.supply_chain", description=__doc__)
    ap.add_argument("--allowlist", default=str(allowlist.ALLOWLIST), help="allow-list YAML")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("lock-export", help="write deploy/requirements.lock from uv.lock").set_defaults(fn=cmd_lock_export)
    p = sub.add_parser("lock-check", help="fail when a lock is stale or lacks hashes")
    p.add_argument("--offline", action="store_true", help="uv lock --check without the network")
    p.add_argument("--skip-resolve", action="store_true", help="skip `uv lock --check` (hash and export checks only)")
    p.set_defaults(fn=cmd_lock_check)
    sub.add_parser("allowlist-check", help="validate the allow-list").set_defaults(fn=cmd_allowlist_check)
    p = sub.add_parser("pip-audit-gate", help="gate a pip-audit JSON report of the lock")
    p.add_argument("report")
    p.add_argument("--lock", default=str(lock.REQUIREMENTS_LOCK), help="the lock that was audited")
    p.set_defaults(fn=cmd_pip_audit_gate)

    def severity_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--severity", default="CRITICAL,HIGH", help="severities that fail (default CRITICAL,HIGH)")
        p.add_argument("--fail-unfixed", action="store_true", help="also fail on findings with no fixed version")

    p = sub.add_parser("trivy-gate", help="gate Trivy JSON reports (and the DB age in --cache-dir)")
    p.add_argument("reports", nargs="+")
    p.add_argument("--cache-dir", required=True, help="the Trivy cache the reports were made with")
    severity_args(p)
    p.set_defaults(fn=cmd_trivy_gate)
    p = sub.add_parser("release-gates", help="Trivy + Syft per image (pinned by id/digest), licences, record")
    p.add_argument("--image", action="append", required=True, help="REF (local) or registry:REF=os/arch")
    p.add_argument("--cache-dir", required=True, help="Trivy cache with db/ and java-db/ (from the media)")
    p.add_argument("--out", default="build/supply-chain")
    p.add_argument("--sbom-dir", default="dist/sbom")
    p.add_argument("--lock-sbom", help="the lock's SBOM from make lock-sbom")
    p.add_argument("--insecure", action="store_true", help="plain-HTTP registry (a CI-local registry only)")
    p.add_argument(
        "--vuln-mode",
        choices=release.VULN_MODES,
        default="block",
        help="fixable CRITICAL/HIGH in release.VULN_REPORT_ONLY images are shown, not failing, in both modes (D-827)",
    )
    severity_args(p)
    p.set_defaults(fn=cmd_release_gates)
    p = sub.add_parser("bundle-check", help="are these local images in a passing gate record?")
    p.add_argument("--gates", required=True)
    p.add_argument("image", nargs="+")
    p.set_defaults(fn=cmd_bundle_check)
    p = sub.add_parser("lock-sbom", help="Syft SBOM of the environment installed from the lock")
    p.add_argument("--env", default=".cache/lock-env")
    p.add_argument("--lock", default=str(lock.REQUIREMENTS_LOCK))
    p.add_argument("--out", default="dist/sbom/requirements.lock.cdx.json")
    p.set_defaults(fn=cmd_lock_sbom)
    p = sub.add_parser("licences", help="licence report from CycloneDX SBOMs")
    p.add_argument("sboms", nargs="+")
    p.add_argument("--out", help="write the Markdown report here too")
    p.add_argument("--gate-os-packages", action="store_true", help="fail on distro (deb/apk/rpm) packages too")
    p.set_defaults(fn=cmd_licences)
    p = sub.add_parser("scanners", help="fetch Syft and Trivy with pinned sha256")
    p.add_argument("--dest", default=".cache/scanners")
    p.set_defaults(fn=cmd_scanners)

    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except (lock.LockError, vulns.ReportError, subprocess.SubprocessError) as exc:
        print(f"{args.cmd}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
