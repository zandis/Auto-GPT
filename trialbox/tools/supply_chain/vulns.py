"""Vulnerability gates (D-186): pip-audit on the hashed lock, Trivy (offline DB) on the images.

Policy:

* **pip-audit**: every advisory on a locked package fails unless the allow-list accepts it. The audited set must equal
  the lock's entries for the target (CPython 3.12 on Linux): a package left out, an extra one or another version
  fails, and so does a package pip-audit could not audit.
* **Trivy**: a CRITICAL or HIGH finding with a fixed version fails unless allow-listed. Trivy's own UNKNOWN (a CVE
  not scored yet) counts as HIGH. A finding whose severity is missing or anything else (a trailing space, lower case)
  fails always. Findings with no fix yet and MEDIUM/LOW are listed but do not fail (``--fail-unfixed`` /
  ``--severity`` tighten this).
* A Trivy report must show what it scanned: non-empty ``Results`` with OS packages, and the language package types
  expected for the image (Python packages in the TrialBox images, jars in the JVM image). An empty report fails.
* The Trivy database must be at most ``MAX_DB_AGE_DAYS`` old (its ``UpdatedAt``), Java database included.
* Trivy runs with no ignore file, no config file and no ``TRIVY_*`` environment, so only the allow-list can accept
  a finding.
* Allow-list entries that matched nothing are reported, so stale entries get removed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.markers import InvalidMarker, Marker

from tools.supply_chain.allowlist import Allowlist, norm
from tools.supply_chain.lock import parse_requirements

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
DEFAULT_FAIL_SEVERITIES = frozenset({"CRITICAL", "HIGH"})
INVALID = "INVALID"  # a severity that is neither one of SEVERITIES nor UNSCORED (missing, odd spelling): always fails
UNSCORED = "UNKNOWN"  # Trivy's own value for a CVE not scored yet: treated as HIGH (fails when a fix exists)
MAX_DB_AGE_DAYS = 7  # Trivy publishes its DB every 6 hours; a release is scanned with a DB at most a week old
# the box's interpreter: the environment markers of the lock are judged for it
TARGET_ENV = {
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "python_version": "3.12",
    "python_full_version": "3.12.0",
    "implementation_version": "3.12.0",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_release": "",
    "platform_version": "",
    "extra": "",
}


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
    errors: list[str] = field(default_factory=list)  # unreadable report, unaudited packages, old DB
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


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"{path}: cannot read scanner JSON: {exc}") from exc


# ---------------------------------------------------------------- pip-audit


def lock_targets(requirements_text: str, env: Mapping[str, str] = TARGET_ENV) -> dict[str, str]:
    """name -> version of every lock entry that installs on ``env`` (markers evaluated)."""
    out: dict[str, str] = {}
    for req in parse_requirements(requirements_text):
        if not req.name or not req.version:
            continue
        if req.marker:
            try:
                if not Marker(req.marker).evaluate(dict(env)):
                    continue
            except InvalidMarker as exc:
                raise ReportError(f"lock entry {req.name}: bad marker {req.marker!r}: {exc}") from exc
        out[req.name] = req.version
    return out


def parse_pip_audit(
    data: Any, expected: Mapping[str, str] | None = None, target: str = "deploy/requirements.lock"
) -> tuple[list[Finding], list[str]]:
    """pip-audit ``-f json``: ``{"dependencies": [...], "fixes": [...]}`` (or the bare list of older versions).

    With ``expected`` (name -> version from the lock), the audited set must be exactly that set.
    """
    deps = data.get("dependencies") if isinstance(data, dict) else data
    if not isinstance(deps, list):
        raise ReportError("pip-audit JSON has no 'dependencies' list")
    if not deps:
        raise ReportError("pip-audit JSON lists no dependencies: nothing was audited")
    findings: list[Finding] = []
    errors: list[str] = []
    audited: dict[str, str] = {}
    for dep in deps:
        if not isinstance(dep, dict) or "name" not in dep:
            raise ReportError(f"pip-audit dependency entry is malformed: {dep!r:.80}")
        name, version = norm(str(dep["name"])), str(dep.get("version", "?"))
        if dep.get("skip_reason"):
            errors.append(f"{name} {version} was not audited: {dep['skip_reason']}")
            continue
        audited[name] = version
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
    if expected is not None:
        want = {norm(k): v for k, v in expected.items()}
        for name, version in sorted(want.items()):
            if name not in audited and not any(e.startswith(f"{name} ") for e in errors):
                errors.append(f"{name}=={version} is in the lock but was not audited")
            elif name in audited and audited[name] != version:
                errors.append(f"{name}: audited {audited[name]}, locked {version}")
        for name in sorted(set(audited) - set(want)):
            errors.append(f"{name}=={audited[name]} was audited but is not in the lock")
    return findings, errors


# ---------------------------------------------------------------- Trivy


@dataclass(frozen=True)
class TrivyReport:
    artifact: str
    image_id: str
    repo_digests: tuple[str, ...]
    diff_ids: tuple[str, ...]
    platform: str
    findings: tuple[Finding, ...]


def expected_lang_types(ref: str) -> frozenset[str]:
    """Language package types a report of this image must contain (the image's own content)."""
    name = ref.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    if name == "trialbox-jvm":
        return frozenset({"python-pkg", "jar"})
    if name in ("trialbox-py", "trialbox-demo"):
        return frozenset({"python-pkg"})
    return frozenset()


def parse_trivy(data: Any, expect_lang: frozenset[str] | None = None) -> TrivyReport:
    """Trivy ``--format json --list-all-pkgs`` (schema 2). Refuses a report that does not show what it scanned.

    ``expect_lang`` defaults to what the scanned image must contain (``expected_lang_types`` of its name)."""
    if not isinstance(data, dict) or not data.get("ArtifactName"):
        raise ReportError("not a Trivy JSON report (no ArtifactName)")
    artifact = str(data["ArtifactName"])
    if expect_lang is None:
        expect_lang = expected_lang_types(artifact)
    results = data.get("Results")
    if not isinstance(results, list) or not results:
        raise ReportError(f"{artifact}: Trivy found nothing to scan (no Results)")
    classes = {(r.get("Class"), r.get("Type")) for r in results if isinstance(r, dict) and r.get("Packages")}
    if not any(c == "os-pkgs" for c, _ in classes):
        raise ReportError(f"{artifact}: no OS packages in the report (run with --list-all-pkgs)")
    missing = sorted(t for t in expect_lang if ("lang-pkgs", t) not in classes)
    if missing:
        raise ReportError(f"{artifact}: no {', '.join(missing)} packages in the report; expected for this image")
    findings: list[Finding] = []
    for res in results:
        target = f"{artifact}:{res.get('Target', '?')}" if res.get("Target") != artifact else artifact
        for v in res.get("Vulnerabilities") or []:
            sev = v.get("Severity")
            findings.append(
                Finding(
                    source="trivy",
                    target=target,
                    package=norm(str(v.get("PkgName", "?"))),
                    version=str(v.get("InstalledVersion", "?")),
                    id=str(v.get("VulnerabilityID", "?")),
                    aliases=tuple(str(a) for a in v.get("VendorIDs", []) or []),
                    severity=sev if sev in SEVERITIES or sev == UNSCORED else f"{INVALID}({sev!r})",
                    fixed=str(v.get("FixedVersion", "") or ""),
                )
            )
    meta = data.get("Metadata") or {}
    cfg = meta.get("ImageConfig") or {}
    platform = f"{cfg.get('os', '?')}/{cfg.get('architecture', '?')}" + (
        f"/{cfg['variant']}" if cfg.get("variant") else ""
    )
    return TrivyReport(
        artifact=artifact,
        image_id=str(meta.get("ImageID", "")),
        repo_digests=tuple(str(d) for d in meta.get("RepoDigests") or []),
        diff_ids=tuple(str(d) for d in meta.get("DiffIDs") or []),
        platform=platform,
        findings=tuple(findings),
    )


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


def pip_audit_gate(path: Path, allow: Allowlist, expected: Mapping[str, str] | None = None) -> GateResult:
    try:
        findings, errors = parse_pip_audit(load_json(path), expected)
    except ReportError as exc:
        return GateResult(errors=[str(exc)])
    return gate(findings, allow, errors=errors)


def trivy_fails(severities: frozenset[str], fail_unfixed: bool) -> Callable[[Finding], bool]:
    def fails(f: Finding) -> bool:
        if f.severity.startswith(INVALID):
            return True
        if f.severity == UNSCORED:  # not scored yet: treated as HIGH, so a fixed one fails
            return "HIGH" in severities and (bool(f.fixed) or fail_unfixed)
        return f.severity in severities and (bool(f.fixed) or fail_unfixed)

    return fails


def trivy_gate(
    reports: list[Path],
    allow: Allowlist,
    *,
    severities: frozenset[str] = DEFAULT_FAIL_SEVERITIES,
    fail_unfixed: bool = False,
    db_errors: list[str] | None = None,
) -> GateResult:
    """Gate Trivy reports; each must show the package types its image should contain."""
    findings: list[Finding] = []
    errors: list[str] = list(db_errors or [])
    if not reports:
        errors.append("no Trivy reports given")
    for path in reports:
        try:
            findings += parse_trivy(load_json(path)).findings
        except ReportError as exc:
            errors.append(f"{path.name}: {exc}")
    return gate(findings, allow, fails=trivy_fails(severities, fail_unfixed), errors=errors)


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    if "." in text:  # Trivy writes nanoseconds; Python reads at most microseconds
        head, _, rest = text.partition(".")
        digits = "".join(ch for ch in rest if ch.isdigit())
        tz = rest[len(digits) :]
        text = f"{head}.{digits[:6]}{tz}"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def db_problems(
    cache_dir: Path, now: dt.datetime, *, max_days: int = MAX_DB_AGE_DAYS
) -> tuple[list[str], dict[str, str]]:
    """Problems with the Trivy databases in ``cache_dir`` (missing, unreadable, too old) and their UpdatedAt."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for sub in ("db", "java-db"):
        meta = cache_dir / sub / "metadata.json"
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"Trivy {sub}: cannot read {meta}: {exc}")
            continue
        when = parse_time(data.get("UpdatedAt") if isinstance(data, dict) else None)
        if when is None:
            problems.append(f"Trivy {sub}: no UpdatedAt in {meta}")
            continue
        seen[sub] = when.isoformat()
        age = now - when
        if age > dt.timedelta(days=max_days):
            problems.append(f"Trivy {sub} is {age.days} days old (UpdatedAt {when:%Y-%m-%d}); the limit is {max_days}")
        elif age < -dt.timedelta(days=1):
            problems.append(f"Trivy {sub} UpdatedAt {when:%Y-%m-%d} is in the future; check the clock")
    return problems, seen


def scanner_env(environ: Mapping[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """The environment for Trivy: every ``TRIVY_*`` setting removed (it could skip findings). Returns the names."""
    env = dict(os.environ if environ is None else environ)
    removed = sorted(k for k in env if k.upper().startswith("TRIVY_"))
    for k in removed:
        del env[k]
    return env, removed


def trivy_command(
    image: str,
    cache_dir: Path,
    out: Path,
    *,
    platform: str | None = None,
    remote: bool = False,
    insecure: bool = False,
) -> list[str]:
    """The Trivy call: the DB already in ``cache_dir`` (pulled beforehand, as on the media), no network for the DB,
    no ignore file, no config file, every package listed so the report shows what was scanned."""
    cmd = [
        "trivy",
        "image",
        "--cache-dir",
        str(cache_dir),
        "--skip-db-update",
        "--skip-java-db-update",
        "--offline-scan",
        "--skip-version-check",
        "--disable-telemetry",
        "--ignorefile",
        "",
        "--config",
        "",
        "--scanners",
        "vuln",
        "--list-all-pkgs",
        "--image-src",
        "remote" if remote else "docker",
        "--format",
        "json",
        "--output",
        str(out),
    ]
    if platform:
        cmd += ["--platform", platform]
    if insecure:
        cmd += ["--insecure"]
    return [*cmd, image]
