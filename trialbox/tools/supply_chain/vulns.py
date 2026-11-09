"""Vulnerability gates (D-186): pip-audit on the hashed lock, Trivy (offline DB) on the images.

Policy:

* **pip-audit**: every advisory on a locked package fails the gate unless the allow-list accepts it.
* **Trivy**: a CRITICAL or HIGH finding with a fixed version fails unless allow-listed. Findings with no fix yet
  and lower severities are listed in the report but do not fail (``--fail-unfixed`` / ``--severity`` change this).
* A pip-audit dependency it could not audit ("skip_reason") fails the gate: unaudited is not clean.
* Allow-list entries that matched nothing are reported, so stale entries get removed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.supply_chain.allowlist import Allowlist, norm

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
DEFAULT_FAIL_SEVERITIES = frozenset({"CRITICAL", "HIGH"})


class ReportError(ValueError):
    """A scanner report that cannot be read; the gate fails rather than passing on nothing."""


@dataclass(frozen=True)
class Finding:
    source: str  # "pip-audit" or "trivy"
    target: str  # the lock or the image/target Trivy names
    package: str
    version: str
    id: str
    aliases: tuple[str, ...]
    severity: str
    fixed: str

    def ids(self) -> set[str]:
        return {self.id, *self.aliases}


@dataclass
class GateResult:
    failing: list[Finding] = field(default_factory=list)
    accepted: list[tuple[Finding, str]] = field(default_factory=list)
    reported: list[Finding] = field(default_factory=list)  # below the bar: shown, not failing
    errors: list[str] = field(default_factory=list)  # unreadable report, unaudited packages
    unused_entries: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failing and not self.errors

    def render(self, title: str) -> str:
        lines = [f"{title}: {'PASS' if self.ok else 'FAIL'}"]
        lines += [f"  ERROR {e}" for e in self.errors]
        lines += [f"  FAIL  {_fmt(f)}" for f in self.failing]
        lines += [f"  OK    {_fmt(f)} (allow-listed: {why})" for f, why in self.accepted]
        lines += [f"  info  {_fmt(f)}" for f in self.reported]
        lines += [f"  note  allow-list entry matched nothing: {e}" for e in self.unused_entries]
        return "\n".join(lines)


def _fmt(f: Finding) -> str:
    fix = f"fixed in {f.fixed}" if f.fixed else "no fix yet"
    sev = "" if f.source == "pip-audit" else f" {f.severity}"  # pip-audit has no severity
    return f"{f.id}{sev} {f.package} {f.version} ({fix}) [{f.target}]"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"{path}: cannot read scanner JSON: {exc}") from exc


def parse_pip_audit(data: Any, target: str = "deploy/requirements.lock") -> tuple[list[Finding], list[str]]:
    """pip-audit ``-f json``: ``{"dependencies": [...], "fixes": [...]}`` (or the bare list of older versions)."""
    deps = data.get("dependencies") if isinstance(data, dict) else data
    if not isinstance(deps, list):
        raise ReportError("pip-audit JSON has no 'dependencies' list")
    if not deps:
        raise ReportError("pip-audit JSON lists no dependencies: nothing was audited")
    findings: list[Finding] = []
    errors: list[str] = []
    for dep in deps:
        if not isinstance(dep, dict) or "name" not in dep:
            raise ReportError(f"pip-audit dependency entry is malformed: {dep!r:.80}")
        name, version = norm(str(dep["name"])), str(dep.get("version", "?"))
        if dep.get("skip_reason"):
            errors.append(f"{name} {version} was not audited: {dep['skip_reason']}")
            continue
        for v in dep.get("vulns", []) or []:
            fixes = [str(x) for x in v.get("fix_versions", []) or []]
            findings.append(
                Finding(
                    source="pip-audit",
                    target=target,
                    package=name,
                    version=version,
                    id=str(v["id"]),
                    aliases=tuple(str(a) for a in v.get("aliases", []) or []),
                    severity="UNKNOWN",  # pip-audit carries no severity; every advisory counts
                    fixed=", ".join(fixes),
                )
            )
    return findings, errors


def parse_trivy(data: Any) -> list[Finding]:
    """Trivy ``--format json`` (schema 2): ``Results[].Vulnerabilities[]``."""
    if not isinstance(data, dict) or "ArtifactName" not in data:
        raise ReportError("not a Trivy JSON report (no ArtifactName)")
    results = data.get("Results") or []
    if not isinstance(results, list):
        raise ReportError("Trivy JSON 'Results' is not a list")
    artifact = str(data["ArtifactName"])
    findings: list[Finding] = []
    for res in results:
        target = f"{artifact}:{res.get('Target', '?')}" if res.get("Target") != artifact else artifact
        for v in res.get("Vulnerabilities") or []:
            sev = str(v.get("Severity", "UNKNOWN")).upper()
            findings.append(
                Finding(
                    source="trivy",
                    target=target,
                    package=norm(str(v.get("PkgName", "?"))),
                    version=str(v.get("InstalledVersion", "?")),
                    id=str(v["VulnerabilityID"]),
                    aliases=tuple(str(a) for a in v.get("VendorIDs", []) or []),
                    severity=sev if sev in SEVERITIES else "UNKNOWN",
                    fixed=str(v.get("FixedVersion", "") or ""),
                )
            )
    return findings


def gate(
    findings: list[Finding],
    allow: Allowlist,
    *,
    fails: Callable[[Finding], bool] | None = None,
    errors: list[str] | None = None,
) -> GateResult:
    """Sort findings into failing, accepted (with the entry's reason) and reported.

    ``fails(finding) -> bool`` says whether a finding is above the bar; by default every finding is.
    """
    result = GateResult(errors=list(errors or []))
    used: set[int] = set()
    for f in findings:
        entry = allow.vuln(f.ids(), f.package)
        if entry is not None:
            used.add(id(entry))
            result.accepted.append((f, entry.reason))
        elif fails is None or fails(f):
            result.failing.append(f)
        else:
            result.reported.append(f)
    result.unused_entries = [e.id for e in allow.vulnerabilities if id(e) not in used]
    return result


def pip_audit_gate(path: Path, allow: Allowlist) -> GateResult:
    try:
        findings, errors = parse_pip_audit(_load_json(path))
    except ReportError as exc:
        return GateResult(errors=[str(exc)])
    return gate(findings, allow, errors=errors)


def trivy_gate(
    paths: list[Path],
    allow: Allowlist,
    *,
    severities: frozenset[str] = DEFAULT_FAIL_SEVERITIES,
    fail_unfixed: bool = False,
) -> GateResult:
    findings: list[Finding] = []
    errors: list[str] = []
    if not paths:
        errors.append("no Trivy reports given")
    for p in paths:
        try:
            findings += parse_trivy(_load_json(p))
        except ReportError as exc:
            errors.append(str(exc))

    def fails(f: Finding) -> bool:
        return f.severity in severities and (bool(f.fixed) or fail_unfixed)

    return gate(findings, allow, fails=fails, errors=errors)


def trivy_offline_command(image: str, cache_dir: Path, out: Path) -> list[str]:
    """The Trivy call for the box's media: the DB pulled beforehand (``oras pull``) into ``cache_dir``, no network."""
    return [
        "trivy",
        "image",
        "--cache-dir",
        str(cache_dir),
        "--skip-db-update",
        "--skip-java-db-update",
        "--skip-check-update",
        "--offline-scan",
        "--scanners",
        "vuln",
        "--format",
        "json",
        "--output",
        str(out),
        image,
    ]
