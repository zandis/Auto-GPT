"""Image configuration scans (D-1343, card 10G-41, review 21 OT-3): three tools per image, report-only.

    python -m tools.supply_chain image-scan --out build/image-scan --cache-dir .cache/trivy \\
        --hadolint-image hadolint/hadolint:v2.12.0@sha256:... \\
        --image trialbox-py:1.0.0=deploy/docker/python.Dockerfile ... --config-dir deploy/docker --config-dir demo

For each image built from one of our Dockerfiles:

* **hadolint** on the Dockerfile it was built from (the pinned image by digest, JSON, ``--no-fail``);
* **Trivy** ``--scanners secret,misconfig`` on the image's files and ``--image-config-scanners secret,misconfig`` on
  its configuration (the checks bundle embedded in the pinned binary: ``--skip-check-update``; no vulnerability DB);
* **Dockle** (CIS Docker image checks: user, setuid files, secrets in ENV, HEALTHCHECK), ``--exit-code 0``.

And ``trivy config`` over each ``--config-dir`` (the Dockerfiles as files). Every report is kept as JSON in ``--out``
with ``summary.md`` (a row per image, the three tools' counts) and ``index.json``.

Report-only until the date in D-1343 (``GATING_FROM``): the command exits 0 whatever the findings, and a tool that
fails is written into the summary, not raised. ``--fail-at HIGH`` (the switch D-1343 turns on at that date) fails on
a Trivy secret or misconfiguration finding of HIGH or CRITICAL, or a scan that did not run. Dockle and hadolint stay
report-only here: hadolint gates in the CI ``images`` job, Dockle FATAL at the release checklist (review 21 §5.2).
Nothing here accepts or suppresses a finding: there is no ignore file and Trivy runs with no ``TRIVY_*`` environment.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.supply_chain import vulns

GATING_FROM = dt.date(2026, 12, 17)  # D-1343: four weeks after the merge, then --fail-at HIGH in the images job
TRIVY_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
DOCKLE_LEVELS = ("FATAL", "WARN", "INFO")
HADOLINT_LEVELS = ("error", "warning", "info", "style")
GATE_LEVELS = frozenset({"CRITICAL", "HIGH"})

Runner = Callable[..., subprocess.CompletedProcess[Any]]


@dataclass(frozen=True)
class Target:
    image: str
    dockerfile: str

    @property
    def slug(self) -> str:
        return "".join(c if c.isalnum() or c in "-." else "_" for c in self.image)


@dataclass
class ToolResult:
    tool: str
    report: str  # file name in the output folder
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def parse_target(text: str) -> Target:
    image, sep, dockerfile = text.partition("=")
    if not sep or not image or not dockerfile:
        raise ValueError(f"--image wants IMAGE=DOCKERFILE, got {text!r}")
    return Target(image, dockerfile)


def trivy_counts(doc: dict[str, Any]) -> dict[str, int]:
    """Secret and misconfiguration findings of a Trivy JSON report by severity (a passed check is not a finding)."""
    seen: Counter[str] = Counter()
    for res in doc.get("Results") or []:
        for m in res.get("Misconfigurations") or []:
            if str(m.get("Status", "FAIL")).upper() == "FAIL":
                seen[str(m.get("Severity", "UNKNOWN")).upper()] += 1
        for s in res.get("Secrets") or []:
            seen[str(s.get("Severity", "UNKNOWN")).upper()] += 1
    return {k: seen.get(k, 0) for k in TRIVY_LEVELS} | {k: v for k, v in seen.items() if k not in TRIVY_LEVELS}


def dockle_counts(doc: dict[str, Any]) -> dict[str, int]:
    """Dockle JSON (``details[].level``) by level; PASS, SKIP and IGNORE are not findings."""
    seen: Counter[str] = Counter(str(d.get("level", "")).upper() for d in doc.get("details") or [])
    return {k: seen.get(k, 0) for k in DOCKLE_LEVELS}


def hadolint_counts(doc: list[dict[str, Any]]) -> dict[str, int]:
    seen: Counter[str] = Counter(str(d.get("level", "")).lower() for d in doc)
    return {k: seen.get(k, 0) for k in HADOLINT_LEVELS}


def trivy_image_command(image: str, cache_dir: Path, out: Path) -> list[str]:
    return [
        "trivy", "image", "--scanners", "secret,misconfig", "--image-config-scanners", "secret,misconfig",
        "--skip-check-update", "--skip-db-update", "--skip-version-check", "--cache-dir", str(cache_dir),
        "--format", "json", "--output", str(out), "--exit-code", "0", image,
    ]  # fmt: skip


def trivy_config_command(path: str, cache_dir: Path, out: Path) -> list[str]:
    return [
        "trivy", "config", "--skip-check-update", "--skip-version-check", "--cache-dir", str(cache_dir),
        "--format", "json", "--output", str(out), "--exit-code", "0", path,
    ]  # fmt: skip


def dockle_command(image: str, out: Path) -> list[str]:
    return ["dockle", "--format", "json", "--output", str(out), "--exit-code", "0", image]


def hadolint_command(hadolint_image: str) -> list[str]:
    """The Dockerfile goes on stdin, as the CI ``images`` job runs it."""
    return ["docker", "run", "--rm", "-i", hadolint_image, "hadolint", "--format", "json", "--no-fail", "-"]


def _run_to_file(
    tool: str, cmd: list[str], out: Path, parse: Callable[[Any], dict[str, int]], run: Runner, *,
    stdin_file: Path | None = None, stdout_is_report: bool = False,
) -> ToolResult:  # fmt: skip
    res = ToolResult(tool, out.name)
    out.unlink(missing_ok=True)
    env, _removed = vulns.scanner_env()
    try:
        if stdin_file is not None:
            with stdin_file.open("rb") as fh:
                proc = run(cmd, env=env, stdin=fh, capture_output=True, check=False)
            stdout, stderr = proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace")
        else:
            proc = run(cmd, env=env, capture_output=True, text=True, check=False)
            stdout, stderr = proc.stdout, proc.stderr
    except OSError as exc:
        res.error = f"{cmd[0]} did not start: {exc}"
        return res
    if stdout_is_report:
        out.write_text(stdout, encoding="utf-8")
    if proc.returncode != 0:
        res.error = f"exit {proc.returncode}: {stderr.strip()[-300:]}"
        return res
    try:
        res.counts = parse(json.loads(out.read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        res.error = f"no readable report: {exc}"
    return res


def scan(
    targets: Sequence[Target], out_dir: Path, *, cache_dir: Path, hadolint_image: str, config_dirs: Sequence[str] = (),
    root: Path = Path("."), run: Runner = subprocess.run,
) -> dict[str, Any]:  # fmt: skip
    out_dir.mkdir(parents=True, exist_ok=True)
    images: list[dict[str, Any]] = []
    for t in targets:
        hl = _run_to_file(
            "hadolint", hadolint_command(hadolint_image), out_dir / f"{t.slug}.hadolint.json", hadolint_counts, run,
            stdin_file=root / t.dockerfile, stdout_is_report=True,
        )  # fmt: skip
        tv = _run_to_file(
            "trivy", trivy_image_command(t.image, cache_dir, out_dir / f"{t.slug}.trivy-config.json"),
            out_dir / f"{t.slug}.trivy-config.json", trivy_counts, run,
        )  # fmt: skip
        dk = _run_to_file(
            "dockle", dockle_command(t.image, out_dir / f"{t.slug}.dockle.json"), out_dir / f"{t.slug}.dockle.json",
            dockle_counts, run,
        )  # fmt: skip
        images.append({"image": t.image, "dockerfile": t.dockerfile, "tools": [r.__dict__ for r in (hl, tv, dk)]})
    configs: list[dict[str, Any]] = []
    for d in config_dirs:
        name = "trivy-config-" + d.strip("/").replace("/", "_") + ".json"
        r = _run_to_file("trivy config", trivy_config_command(d, cache_dir, out_dir / name), out_dir / name,
                         trivy_counts, run)  # fmt: skip
        configs.append({"path": d} | r.__dict__)
    record = {"decision": "D-1343", "gating_from": GATING_FROM.isoformat(), "images": images, "config": configs}
    (out_dir / "index.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


def _fmt(r: dict[str, Any], levels: Sequence[str]) -> str:
    if r.get("error"):
        return "not run: " + str(r["error"]).replace("|", "/").replace("\n", " ")[:120]
    return " ".join(f"{k} {r['counts'].get(k, 0)}" for k in levels)


def summary(record: dict[str, Any]) -> str:
    lines = [
        "## Image configuration scans (D-1343, report-only)",
        "",
        f"Three tools per image. Report-only until {record['gating_from']}; from then Trivy secret and"
        " misconfiguration findings of HIGH or CRITICAL fail the images job.",
        "",
        "| Image | Dockerfile | hadolint | Trivy secret, misconfig | Dockle |",
        "| --- | --- | --- | --- | --- |",
    ]
    for img in record["images"]:
        hl, tv, dk = img["tools"]
        lines.append(
            f"| `{img['image']}` | `{img['dockerfile']}` | {_fmt(hl, HADOLINT_LEVELS)} | {_fmt(tv, TRIVY_LEVELS)} |"
            f" {_fmt(dk, DOCKLE_LEVELS)} |"
        )
    if record["config"]:
        lines += ["", "| trivy config | Findings |", "| --- | --- |"]
        lines += [f"| `{c['path']}` | {_fmt(c, TRIVY_LEVELS)} |" for c in record["config"]]
    return "\n".join(lines) + "\n"


def gate_failures(record: dict[str, Any]) -> list[str]:
    """What ``--fail-at HIGH`` fails on: a Trivy HIGH or CRITICAL finding, or a Trivy scan that did not run."""
    problems: list[str] = []
    rows = [(img["image"], img["tools"][1]) for img in record["images"]]
    rows += [(c["path"], c) for c in record["config"]]
    for name, r in rows:
        if r.get("error"):
            problems.append(f"{name}: trivy did not run ({r['error']})")
            continue
        n = sum(v for k, v in r["counts"].items() if k in GATE_LEVELS)
        if n:
            problems.append(f"{name}: {n} HIGH or CRITICAL secret or misconfiguration finding(s)")
    return problems
