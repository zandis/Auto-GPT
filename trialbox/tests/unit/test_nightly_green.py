"""ENG-002 (D-560): the nightly workflow's three stops of 2026-11-10 and 2026-11-11. The test stack's embed service
runs as TEST (the stub embedder is refused in PRODUCTION, D-429); the public corpus is fetched by a named step before
the public-data walk, and a missing corpus is one line that names the command; the random-order run uses the unit
shards of the pull-request gate (D-475), so it ends inside its limit and names what failed."""

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
def test_the_nightly_fetches_the_public_corpus_before_the_public_walk() -> None:
    assert "tools.medtxt_eval" in _target_body("public-data")
    runs = _runs(_yaml(NIGHTLY)["jobs"]["nightly"])
    fetch = next(i for i, r in enumerate(runs) if "make public-data" in r)
    walk = next(i for i, r in enumerate(runs) if "tools.public_e2e" in r)
    assert fetch < walk
    steps = _yaml(NIGHTLY)["jobs"]["nightly"]["steps"]
    assert steps[fetch].get("if") == steps[walk].get("if") == "matrix.run == 'public-e2e'"


def test_the_compose_job_fetches_the_public_corpus_before_its_browser_walk() -> None:
    """The nightly of 2026-11-13: the compose job's walk of the public console stopped at "the MedTxt corpus is not
    in .cache/medtxt: fetch it once with `make public-data`". Only the public-e2e run fetched it (D-639)."""
    steps = _yaml(NIGHTLY)["jobs"]["compose"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    fetch = next(i for i, r in enumerate(runs) if "make public-data" in r)
    walk = next(i for i, r in enumerate(runs) if r.startswith("make walk"))
    assert (
        fetch < walk and "if" not in steps[fetch]
    )  # always, and before the stack is up: a fetch that fails stops early
    cache = next(s for s in steps if "trialbox/.cache/medtxt" in str((s.get("with") or {}).get("path", "")))
    public = next(
        s for s in _yaml(NIGHTLY)["jobs"]["nightly"]["steps"]
        if "trialbox/.cache/medtxt" in str((s.get("with") or {}).get("path", ""))
    )  # fmt: skip
    assert cache["uses"] == public["uses"] and cache["with"]["key"] == public["with"]["key"]  # one cache, both jobs
    assert steps.index(cache) < fetch < next(i for i, r in enumerate(runs) if "make up-test" in r)


def test_a_missing_corpus_is_one_line_that_names_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import medtxt_eval, public_site

    monkeypatch.setattr(medtxt_eval, "CACHE", tmp_path / "medtxt")
    with pytest.raises(SystemExit) as stop:
        public_site.medtxt_docs()
    assert "make public-data" in str(stop.value) and "MedTxt" in str(stop.value)


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
