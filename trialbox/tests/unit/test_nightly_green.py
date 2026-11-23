"""ENG-002 (D-560): the nightly workflow's three stops of 2026-11-10 and 2026-11-11. The test stack's embed service
runs as TEST (the stub embedder is refused in PRODUCTION, D-429); the public-data walk reads the committed, pinned
JMED-LLM datasets (nothing is fetched; rewritten 2026-11-23); the random-order run uses the unit shards of the pull-request gate (D-475), so it ends inside its limit and names what failed."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
NIGHTLY = WORKFLOWS / "trialbox-e2e.yml"
GATE = WORKFLOWS / "trialbox-ci.yml"
DEFAULT = re.compile(r"^\$\{TB_ENV:-(\w+)\}$")

pytestmark = pytest.mark.nodb


def _yaml(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    return {str(k): str(v) for k, v in env.items()}


def _runs(job: dict[str, Any]) -> list[str]:
    return [str(s.get("run", "")) for s in job["steps"]]


def _target_body(name: str) -> str:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return text[text.index(f"\n{name}:") :].split("\n\n", 1)[0]


# ------------------------------------------------------------------------------------------------ the compose stack
def test_the_test_stack_runs_the_embed_service_as_test() -> None:
    """The nightly's `make up-test` stopped on EmbedderRefused: the overlay left the embed service on PRODUCTION."""
    from embed_service import embedder

    overlay = _yaml(ROOT / "deploy" / "docker-compose.test.yml")["services"]
    m = DEFAULT.match(_env(overlay["embed-service"]).get("TB_ENV", ""))
    assert m and m.group(1) == "TEST", "docker-compose.test.yml: embed-service has no TB_ENV default of TEST"
    assert isinstance(embedder.service_embedder({"TB_ENV": m.group(1)}), embedder.HashEmbedder)


def test_the_box_stack_still_refuses_the_stub_embedder() -> None:
    """The fix is in the test overlay only: the base file gives the embed service no TB_ENV, and unset is PRODUCTION."""
    from embed_service import embedder

    base = _yaml(ROOT / "deploy" / "docker-compose.yml")["services"]
    assert "TB_ENV" not in _env(base["embed-service"])
    with pytest.raises(embedder.EmbedderRefused, match="refused in PRODUCTION"):
        embedder.service_embedder({"TB_EMBED_MODE": "hash"})


# -------------------------------------------------------------------------------------------------- the public data
# Rewritten on 2026-11-23 (the integrator's ruling, #639 7116467086): the corpus host is not reachable from the runner,
# so the public walk reads 147 case reports and 50 radiology reports of JMED-LLM's three CC BY 4.0 datasets, committed
# unchanged under eval/medtxt/jmed-llm and pinned by SHA-256. Nothing is fetched, so the tests that required the fetch
# step before the walk (and its cache, and the one line for a missing corpus) now say what replaced it.
def test_the_nightly_fetches_nothing_before_the_public_walk() -> None:
    steps = _yaml(NIGHTLY)["jobs"]["nightly"]["steps"]
    runs = _runs(_yaml(NIGHTLY)["jobs"]["nightly"])
    assert not any("make public-data" in r for r in runs)  # no fetch step
    assert not any("trialbox/.cache/medtxt" in str((s.get("with") or {}).get("path", "")) for s in steps)  # no cache
    walk = next(s for s in steps if "tools.public_e2e" in str(s.get("run", "")))
    assert walk.get("if") == "matrix.run == 'public-e2e'"
    assert (
        "public-e2e" in _yaml(NIGHTLY)["jobs"]["nightly"]["strategy"]["matrix"]["run"]
    )  # and it stays on the schedule


def test_the_compose_job_fetches_nothing_before_its_browser_walk() -> None:
    """The nightly of 2026-11-13: the compose job's walk of the public console stopped at a missing corpus (D-639). The
    walk reads the committed datasets now, as public-e2e does."""
    steps = _yaml(NIGHTLY)["jobs"]["compose"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    assert not any("make public-data" in r for r in runs)
    assert not any("trialbox/.cache/medtxt" in str((s.get("with") or {}).get("path", "")) for s in steps)
    assert any(r.startswith("make walk") for r in runs)  # the walk is still there


def test_the_public_walk_reads_the_pinned_committed_datasets() -> None:
    import hashlib

    from tools import public_site

    for name, sha in public_site.JMED_PINS.items():
        assert hashlib.sha256((public_site.JMED_DIR / name).read_bytes()).hexdigest() == sha
        assert (public_site.JMED_DIR.parent / "jmed-llm" / "SHA256SUMS").read_text().count(f"{sha}  {name}") == 1
    docs = public_site.medtxt_docs()
    assert [(k, sum(1 for d in docs if d.source == k)) for k in ("MedTxt-CR", "MedTxt-RR")] == [
        ("MedTxt-CR", 147),
        ("MedTxt-RR", 50),
    ]
    assert len({d.doc for d in docs}) == len(docs) and all(d.text and d.lang == "ja" for d in docs)


def test_a_dataset_that_is_not_the_pinned_one_is_refused_by_name(tmp_path: Path) -> None:
    from tools import public_site

    for name in public_site.JMED_PINS:
        (tmp_path / name).write_bytes((public_site.JMED_DIR / name).read_bytes() + b"x")
    with pytest.raises(SystemExit) as stop:
        public_site.jmed_reports(tmp_path)
    assert "mrner_disease.csv" in str(stop.value) and "not the pinned" in str(stop.value)


# ------------------------------------------------------------------------------------------------ the random order
def test_the_random_order_run_takes_a_shard() -> None:
    assert "$(SHARD_ARGS)" in _target_body("test-random-locked")


def test_the_nightly_runs_the_random_order_in_the_gates_shards() -> None:
    """One job per shard, the same shards and the same limit as `unit-shard` of the pull-request gate (D-475)."""
    gate = _yaml(GATE)["jobs"]["unit-shard"]
    job = _yaml(NIGHTLY)["jobs"]["random-order"]
    assert job["strategy"]["matrix"]["shard"] == gate["strategy"]["matrix"]["shard"]
    assert job["strategy"]["fail-fast"] is False
    assert job["timeout-minutes"] == gate["timeout-minutes"]
    run = next(r for r in _runs(job) if "make test-random" in r)
    assert "SHARD=${{ matrix.shard }}/${{ strategy.job-total }}" in run
    assert "random-order" not in _yaml(NIGHTLY)["jobs"]["nightly"]["strategy"]["matrix"]["run"]
