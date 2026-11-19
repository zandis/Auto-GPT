"""10G-41 (D-1343, review 21 OT-3): hadolint on every Dockerfile, and three configuration scans per image.

The Dockerfiles in the tree, the Makefile's ``DOCKERFILES`` (``make ci``) and the CI ``images`` job's hadolint loop
are one set. Every image of ``SC_OWN_IMAGES`` is scanned from the Dockerfile it is built from by ``make image-scan``,
which the image gates' job runs report-only after the release gates, keeping its folder with the gate record. Dockle
is pinned by sha256 like Syft and Trivy. D-1343 carries the dated line from which the scan gates at HIGH; this
test only checks that the line is there (it never fails because of the calendar). The parsing, the summary and the
``--fail-at HIGH`` logic are checked on small fixtures with a fake runner: no Docker, no scanner, no network."""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.supply_chain import __main__ as sc_main
from tools.supply_chain import image_scan, scanners

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
DECISION = ROOT / "docs/decisions/D-1343-every-dockerfile-linted-and-three-config-scanners-per-image.md"
SKIP_DIRS = {".git", ".venv", ".cache", "node_modules", "build", "dist", "__pycache__"}


def _makefile() -> str:
    return re.sub(r"\\\n\s*", " ", (ROOT / "Makefile").read_text(encoding="utf-8"))


def _make_var(name: str) -> list[str]:
    m = re.search(rf"^{name} \??:?= *(.*)$", _makefile(), re.M)
    assert m, f"{name} not in the Makefile"
    return m.group(1).split()


def _workflow(name: str) -> dict[str, Any]:
    if not WORKFLOWS.is_dir():
        pytest.skip("workflows not in this checkout")
    doc: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _dockerfiles_in_tree() -> set[str]:
    found = set()
    for p in ROOT.rglob("*Dockerfile"):
        rel = p.relative_to(ROOT)
        if p.is_file() and not SKIP_DIRS.intersection(rel.parts):
            found.add(rel.as_posix())
    return found


def _step(job: dict[str, Any], needle: str) -> tuple[int, dict[str, Any]]:
    for i, s in enumerate(job["steps"]):
        if needle in str(s.get("run", "")) or needle in str(s.get("name", "")):
            return i, s
    raise AssertionError(f"no step with {needle!r}")


def test_every_dockerfile_is_in_the_makefile_list_and_the_ci_loop() -> None:
    tree = _dockerfiles_in_tree()
    assert len(tree) >= 8, sorted(tree)
    assert set(_make_var("DOCKERFILES")) == tree
    assert re.search(r"hadolint --failure-threshold warning \$\(DOCKERFILES\)", _makefile())
    _, step = _step(_workflow("trialbox-ci.yml")["jobs"]["images"], "hadolint")
    loop = re.search(r"for f in (.*?); do", step["run"].replace("\\\n", " "), re.S)
    assert loop and set(loop.group(1).split()) == tree
    assert "--failure-threshold warning" in step["run"]


def test_the_hadolint_image_is_the_ci_jobs_by_digest() -> None:
    (image,) = _make_var("HADOLINT_IMAGE")
    assert re.fullmatch(r"hadolint/hadolint:v[0-9.]+@sha256:[0-9a-f]{64}", image)
    _, step = _step(_workflow("trialbox-ci.yml")["jobs"]["images"], "hadolint")
    assert image in step["run"]


def test_every_ignore_pragma_sits_on_an_instruction() -> None:
    """hadolint applies ``# hadolint ignore=`` to the line under it: a comment there makes it reach nothing."""
    for rel in sorted(_dockerfiles_in_tree()):
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# hadolint ignore="):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                assert nxt.strip() and not nxt.startswith("#"), f"{rel}:{i + 1}: the pragma is not above an instruction"


def test_every_own_image_is_scanned_from_its_dockerfile() -> None:
    pairs = [image_scan.parse_target(t) for t in _make_var("IMAGE_SCAN_IMAGES")]
    assert {t.image for t in pairs} == set(_make_var("SC_OWN_IMAGES"))
    mk = _makefile()
    built = set(re.findall(r"-f (\S+)\s+-t (\S+) \.", mk))  # `make images`: docker build ... -f DOCKERFILE -t IMAGE .
    db_script = (ROOT / "deploy/build_db_image.sh").read_text(encoding="utf-8")
    for t in pairs:
        assert t.dockerfile in _make_var("DOCKERFILES"), t
        if t.image == "trialbox-postgres:16-1":
            assert f"-f {t.dockerfile} -t {t.image}" in db_script
        elif t.image == "trialbox-demo:step5":
            run = _step(_workflow("trialbox-images.yml")["jobs"]["images"], "make images")[1]["run"]
            assert f"-f {t.dockerfile} -t {t.image}" in run
        else:
            assert (t.dockerfile, t.image) in built, (t, built)


def test_the_images_job_runs_the_scan_report_only_and_keeps_it() -> None:
    job = _workflow("trialbox-images.yml")["jobs"]["images"]
    i_gates, _ = _step(job, "make release-gates")
    i_scan, scan = _step(job, "make image-scan")
    assert i_scan > i_gates
    assert scan["run"].strip() == "make image-scan"  # no --fail-at: report-only until D-1343's date
    assert scan.get("continue-on-error") is True and "cancelled()" in str(scan.get("if"))
    _, keep = _step(job, "Keep the record")
    assert "trialbox/build/image-scan" in keep["with"]["path"].split()
    _, summ = _step(job, "Findings in the job summary")
    assert "build/image-scan/summary.md" in summ["run"]
    assert re.search(r"^image-scan: scanners$", _makefile(), re.M)
    assert "image-scan" in _makefile() and "IMAGE_SCAN_ARGS" in _makefile()


def test_dockle_is_pinned_for_both_platforms_and_fetched_with_the_others() -> None:
    assert "dockle" in scanners.TOOLS
    for arch in ("amd64", "arm64"):
        a = scanners.asset("dockle", arch)
        assert re.fullmatch(r"[0-9a-f]{64}", a.sha256) and a.version in a.url
        assert a.url.startswith("https://github.com/goodwithtech/dockle/releases/download/")
        assert "latest" not in a.url


def test_the_decision_holds_the_date_the_scan_gates_from() -> None:
    """Only that the dated line exists and agrees with the code and the workflow: the calendar never fails this."""
    m = re.search(r"^- \*\*Gating from:\*\* (\d{4}-\d{2}-\d{2})\s*$", DECISION.read_text(encoding="utf-8"), re.M)
    assert m, "D-1343 has no 'Gating from:' line"
    day = dt.date.fromisoformat(m.group(1))
    assert day == image_scan.GATING_FROM
    if WORKFLOWS.is_dir():
        assert day.isoformat() in (WORKFLOWS / "trialbox-images.yml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the reports, on fixtures

TRIVY = {
    "Results": [
        {"Target": "img (config)", "Misconfigurations": [
            {"ID": "DS002", "Severity": "HIGH", "Status": "FAIL"},
            {"ID": "DS026", "Severity": "LOW", "Status": "FAIL"},
            {"ID": "DS001", "Severity": "MEDIUM", "Status": "PASS"},
        ]},
        {"Target": "/app/x.pem", "Secrets": [{"RuleID": "private-key", "Severity": "CRITICAL"}]},
    ]
}  # fmt: skip
DOCKLE = {"details": [{"code": "CIS-DI-0006", "level": "WARN"}, {"code": "CIS-DI-0008", "level": "INFO"},
                      {"code": "DKL-DI-0006", "level": "PASS"}]}  # fmt: skip
HADOLINT = [{"code": "DL3008", "level": "warning", "line": 3}, {"code": "SC1091", "level": "info", "line": 3}]


def test_counts_by_severity() -> None:
    assert image_scan.trivy_counts(TRIVY) == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 1, "UNKNOWN": 0}
    assert image_scan.dockle_counts(DOCKLE) == {"FATAL": 0, "WARN": 1, "INFO": 1}
    assert image_scan.hadolint_counts(HADOLINT) == {"error": 0, "warning": 1, "info": 1, "style": 0}
    assert image_scan.trivy_counts({"Results": None}) == dict.fromkeys(image_scan.TRIVY_LEVELS, 0)


def _fake_run(*, trivy: dict[str, Any] = TRIVY, dockle_rc: int = 0) -> Any:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
        calls.append(cmd)
        assert not any(k.upper().startswith("TRIVY_") for k in kw["env"])
        if cmd[0] == "docker":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(HADOLINT).encode(), b"")
        out = Path(cmd[cmd.index("--output") + 1])
        if cmd[0] == "trivy":
            out.write_text(json.dumps(trivy), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if dockle_rc:
            return subprocess.CompletedProcess(cmd, dockle_rc, "", "cannot connect to the Docker daemon")
        out.write_text(json.dumps(DOCKLE), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_scan_writes_three_tools_per_image_and_a_failing_tool_is_recorded(tmp_path: Path) -> None:
    run = _fake_run(dockle_rc=1)
    targets = [image_scan.Target("trialbox-py:1.0.0", "deploy/docker/python.Dockerfile")]
    rec = image_scan.scan(targets, tmp_path / "out", cache_dir=tmp_path / "c", hadolint_image="h@sha256:x",
                          config_dirs=["deploy/docker"], root=ROOT, run=run)  # fmt: skip
    tools = rec["images"][0]["tools"]
    assert [t["tool"] for t in tools] == ["hadolint", "trivy", "dockle"]
    assert tools[2]["error"] and "Docker daemon" in tools[2]["error"]
    trivy_cmd = next(c for c in run.calls if c[:2] == ["trivy", "image"])
    assert (
        "secret,misconfig" in trivy_cmd and "--skip-check-update" in trivy_cmd and trivy_cmd[-1] == "trialbox-py:1.0.0"
    )
    assert "--image-config-scanners" in trivy_cmd and "--exit-code" in trivy_cmd
    assert any(c[:2] == ["trivy", "config"] and c[-1] == "deploy/docker" for c in run.calls)
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "| `trialbox-py:1.0.0` | `deploy/docker/python.Dockerfile` | error 0 warning 1" in summary
    assert "not run: exit 1" in summary and image_scan.GATING_FROM.isoformat() in summary
    assert json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))["decision"] == "D-1343"
    assert len(image_scan.gate_failures(rec)) == 2  # the image's HIGH+CRITICAL and the config folder's


def test_report_only_exits_0_and_fail_at_high_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = image_scan.scan
    monkeypatch.setattr(image_scan, "scan", lambda *a, **k: real(*a, **k, root=ROOT, run=_fake_run()))
    base = ["image-scan", "--out", str(tmp_path / "o"), "--cache-dir", str(tmp_path / "c"), "--hadolint-image", "h",
            "--image", "trialbox-py:1.0.0=deploy/docker/python.Dockerfile"]  # fmt: skip
    assert sc_main.main(base) == 0
    assert sc_main.main([*base, "--fail-at", "HIGH"]) == 1
    clean = {"Results": [{"Misconfigurations": [{"Severity": "MEDIUM", "Status": "FAIL"}]}]}
    monkeypatch.setattr(image_scan, "scan", lambda *a, **k: real(*a, **k, root=ROOT, run=_fake_run(trivy=clean)))
    assert sc_main.main([*base, "--fail-at", "HIGH"]) == 0
    assert sc_main.main(["image-scan", "--hadolint-image", "h", "--image", "no-dockerfile"]) == 2
