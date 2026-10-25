"""The Test Bench never ships in a product image or a production compose file (docs/HANDOFF.md §5).

This is how the bench stays out of the FR-UX-12 surface inventory: not by an allow-list, but by proving that nothing
that can run in production contains it. Product images are checked through their build context (every ``COPY`` source
of every Dockerfile under ``deploy/``, filtered by ``.dockerignore``); compose files are checked as text.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest
import yaml

from tools.testbench import BANNER

ROOT = Path(__file__).resolve().parents[2]
BENCH_COMPOSE = ROOT / "deploy" / "docker-compose.testbench.yml"
MARKERS = (BANNER, "tools/testbench", "tools.testbench", "testbench")


def _compose_files() -> list[Path]:
    out = [p for p in (ROOT / "deploy").rglob("*.yml") if "compose" in p.name]
    out += [p for p in (ROOT / "deploy").rglob("*.yaml") if "compose" in p.name]
    return sorted(p for p in out if p.resolve() != BENCH_COMPOSE.resolve())


def _dockerignore(root: Path = ROOT) -> list[tuple[bool, str]]:
    rules: list[tuple[bool, str]] = []
    path = root / ".dockerignore"
    if not path.exists():
        return rules
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        rules.append((neg, line.lstrip("!").strip("/")))
    return rules


def ignored(rel: str, rules: list[tuple[bool, str]]) -> bool:
    """Docker's rule: the last matching pattern wins; a pattern also excludes everything below a matched directory."""
    parts = rel.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    result = False
    for neg, pat in rules:
        pats = {pat, pat.removeprefix("**/")}
        hit = any(fnmatch.fnmatchcase(p, q) for p in prefixes for q in pats)
        if pat.startswith("**/"):
            hit = hit or any(fnmatch.fnmatchcase(part, pat[3:]) for part in parts)
        if hit:
            result = not neg
    return result


def _copy_sources(dockerfile: Path) -> list[str]:
    srcs: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*COPY\s+(.*)$", line, flags=re.I)
        if not m or "--from=" in m.group(1):
            continue
        args = [a for a in m.group(1).replace("\\", " ").split() if not a.startswith("--")]
        srcs += args[:-1]  # the last argument is the destination
    return srcs


def image_files(dockerfile: Path, rules: list[tuple[bool, str]]) -> list[str]:
    """Repository-relative files a product image built from ``dockerfile`` would contain."""
    out: list[str] = []
    for src in _copy_sources(dockerfile):
        base = ROOT / src
        paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []
        for p in paths:
            rel = p.relative_to(ROOT).as_posix()
            if not ignored(rel, rules):
                out.append(rel)
    return out


def test_dockerignore_matcher() -> None:
    rules = [(False, "**/__pycache__"), (False, "tools/testbench"), (False, "data"), (True, "data/keep.txt")]
    assert ignored("tools/testbench/app.py", rules) and ignored("tools/testbench/static/htmx.min.js", rules)
    assert ignored("services/x/__pycache__/a.pyc", rules)
    assert not ignored("tools/acceptance.py", rules) and not ignored("data/keep.txt", rules)


@pytest.mark.req("FR-UX-12")
def test_no_production_compose_file_contains_the_test_bench() -> None:
    files = _compose_files()
    assert files, "no compose files found under deploy/"
    for p in files:
        text = p.read_text(encoding="utf-8")
        found = [m for m in MARKERS if m.lower() in text.lower()]
        assert not found, f"{p.relative_to(ROOT)} mentions the Test Bench: {found}"


@pytest.mark.req("FR-UX-12")
def test_no_product_image_contains_the_test_bench() -> None:
    rules = _dockerignore()
    dockerfiles = sorted((ROOT / "deploy").rglob("*Dockerfile*"))
    assert dockerfiles, "no Dockerfiles found under deploy/"
    for df in dockerfiles:
        files = image_files(df, rules)
        bench = [f for f in files if f.startswith("tools/testbench/") or f.startswith("tests/")]
        assert not bench, (
            f"{df.relative_to(ROOT)} would copy the Test Bench into a product image ({bench[:3]} …): "
            "add `tools/testbench/` to .dockerignore"
        )
        for f in files:
            if f.endswith((".py", ".html", ".js", ".yml", ".yaml", ".txt", ".md", ".json", ".css")):
                text = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
                assert BANNER not in text, f"{f} (in {df.name}) carries the Test Bench banner"


def test_bench_compose_is_dev_only_and_local() -> None:
    doc = yaml.safe_load(BENCH_COMPOSE.read_text(encoding="utf-8"))
    services = doc["services"]
    assert set(services) == {"testbench"}
    svc = services["testbench"]
    assert svc["profiles"] == ["dev"]
    assert svc["environment"]["TB_ENV"] in ("DEV", "TEST")
    assert all(str(p).startswith("127.0.0.1:") for p in svc["ports"])
    assert not any(k in svc["environment"] for k in ("TB_LAKE_DIR", "TB_ORCH_DIR", "TB_MAIL_DIR", "FHIR_BASE_URL"))
