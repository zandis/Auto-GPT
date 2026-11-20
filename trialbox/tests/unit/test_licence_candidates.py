"""Card 10E-24 (review 17-9, decision 93; D-1347): a licence register row for every candidate model, community and
health-developer licences never in the shipped box, unread terms never shippable, and the revision pins of a
verified build held by ``python -m tools.licence_register --check`` (not by ``qualify``, whose gate is unchanged).

Each test writes a changed copy of the register or the model registry and runs the check over the repository with
it, so the tests hold the check itself, whatever function inside it does the work."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import licence_register as lr

SHIPPED = {"model-gemma-4-26b-a4b-nvfp4", "model-qwen3.5-9b-awq-4bit"}
JUDGE = "gemma-4-26b-a4b-it-rtxpro6000"
FULL = "a" * 40


def _register_rows() -> list[dict[str, str]]:
    with lr.REGISTER.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_register(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=lr.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    out = tmp_path / "register.csv"
    out.write_text(buf.getvalue(), encoding="utf-8")
    return out


def _builds() -> list[dict[str, Any]]:
    return list(yaml.safe_load(lr.MODELS.read_text(encoding="utf-8"))["builds"])


def _write_models(tmp_path: Path, builds: list[dict[str, Any]]) -> Path:
    out = tmp_path / "registry.yaml"
    out.write_text(yaml.safe_dump({"builds": builds}, sort_keys=False), encoding="utf-8")
    return out


def _check(
    tmp_path: Path, rows: list[dict[str, str]] | None = None, builds: list[dict[str, Any]] | None = None
) -> list[str]:
    register = _write_register(tmp_path, rows) if rows is not None else None
    models = _write_models(tmp_path, builds) if builds is not None else None
    return lr.check(register=register, models=models)


def _set(rows: list[dict[str, str]], rid: str, **change: str) -> list[dict[str, str]]:
    return [{**r, **change} if r["id"] == rid else r for r in rows]


def _build(builds: list[dict[str, Any]], bid: str, **change: Any) -> list[dict[str, Any]]:
    return [{**b, **change} if b["build_id"] == bid else b for b in builds]


# ------------------------------------------------------------------------------------------------ the committed rows
def test_every_candidate_has_a_model_row_and_only_todays_pair_is_cleared() -> None:
    rows = {r.id: r for r in lr.load()}
    assert len(lr.CANDIDATES) == 15 and set(lr.CANDIDATES) <= rows.keys()
    for rid in lr.CANDIDATES:
        assert rows[rid].kind == "model", rid
    cleared = {rid for rid in lr.CANDIDATES if rows[rid].status in lr.MODEL_OK}
    assert cleared == SHIPPED
    unread = {rid for rid in lr.CANDIDATES if lr.TERMS_NOT_READ in rows[rid].raw["obligation"]}
    assert len(unread) == 12 and not unread & SHIPPED
    assert {rows[rid].status for rid in unread} <= {"terms-not-read", "excluded"}


def test_the_new_rows_cite_review_17_and_hold_no_text_hash() -> None:
    """No licence fact from memory: each new row cites the review that read it, and records no text it did not read."""
    rows = {r.id: r for r in lr.load()}
    for rid in set(lr.CANDIDATES) - SHIPPED:
        assert "review 17" in rows[rid].raw["evidence"] and not rows[rid].raw["text_sha256"], rid
        assert rows[rid].status in lr.SHIPS_NOTHING, rid


def test_community_and_health_developer_rows_are_excluded() -> None:
    rows = {r.id: r for r in lr.load()}
    assert rows["model-qwen3.8-flash-next"].status == "excluded"
    assert rows["model-medgemma"].status == "excluded"
    assert (
        "93" in rows["model-qwen3.8-flash-next"].raw["obligation"] and "93" in rows["model-medgemma"].raw["obligation"]
    )


# ------------------------------------------------------------------------------------------------ decision 93, planted
@pytest.mark.parametrize("rid", ["model-qwen3.8-flash-next", "model-medgemma"])
def test_an_excluded_licence_marked_shippable_fails_the_check(tmp_path: Path, rid: str) -> None:
    rows = _set(_register_rows(), rid, status="cleared", version=f"revision {FULL}")
    problems = _check(tmp_path, rows)
    assert any(rid in p and "not excluded (93)" in p for p in problems), problems


@pytest.mark.parametrize(
    ("licence", "spdx"),
    [
        ("Health Developer terms", "LicenseRef-x"),
        ("Fixture terms", "LicenseRef-Community-2"),
        ("x", "LicenseRef-HealthAI-Developer"),
    ],
)
def test_a_planted_candidate_under_such_a_licence_cannot_ship(
    tmp_path: Path, licence: str, spdx: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A synthetic candidate under a community or health-developer licence, its row cleared and a build verified
    against it: the CLI check exits 1, both on the row and on the build."""
    rows = _register_rows()
    rows.append({**rows[-1], "id": "model-planted", "kind": "model", "standard": "planted", "source": "fixture/planted",
                 "licence": licence, "spdx": spdx, "status": "cleared", "version": f"revision {FULL}",
                 "text_sha256": "", "athena": "", "paths": "", "evidence": "https://example.invalid"})  # fmt: skip
    build = {"build_id": "planted-champion", "status": "champion", "repository": "fixture/planted", "revision": FULL,
             "licence": {"name": licence, "spdx": spdx, "verified": True, "register": "model-planted"}}  # fmt: skip
    register, models = _write_register(tmp_path, rows), _write_models(tmp_path, [*_builds(), build])
    check = lr.check
    monkeypatch.setattr(lr, "check", lambda: check(register=register, models=models))
    assert lr.main(["--check"]) == 1
    err = capsys.readouterr().err.splitlines()
    assert any("model-planted" in p and "(93)" in p for p in err), err
    assert any("planted-champion" in p and "(93)" in p for p in err), err


def test_unread_terms_are_never_cleared(tmp_path: Path) -> None:
    rows = _set(_register_rows(), "model-qwen3.8-27b", status="cleared", version=f"revision {FULL}")
    assert any("model-qwen3.8-27b" in p and "terms not read" in p for p in _check(tmp_path, rows))
    rows = _set(_register_rows(), "model-gpt-oss-safeguard-20b", status="terms-not-read")
    (tmp_path / "b").mkdir()
    assert any("model-gpt-oss-safeguard-20b" in p and "must say" in p for p in _check(tmp_path / "b", rows))


# ------------------------------------------------------------------------------------------------ the six Medium findings
def test_medium_3_a_missing_candidate_row_fails_the_check_itself(tmp_path: Path) -> None:
    """The candidate list lives in the tool: the register without one candidate's row fails --check."""
    rows = [r for r in _register_rows() if r["id"] != "model-gemma-4-31b-it"]
    problems = _check(tmp_path, rows)
    assert len(problems) == 1 and "candidate model-gemma-4-31b-it" in problems[0], problems


def test_medium_4_the_installed_revision_is_checked_against_the_expected_one(tmp_path: Path) -> None:
    builds = _builds()
    judge = next(b for b in builds if b["build_id"] == JUDGE)
    assert judge["expected"]["revision"] and not judge["revision"]
    problems = _check(tmp_path, builds=_build(builds, JUDGE, revision="1" * 40))
    assert any(JUDGE in p and "installed revision" in p for p in problems), problems
    assert any(JUDGE in p and "is not row model-gemma-4-26b-a4b-nvfp4's" in p for p in problems), problems


def test_medium_5_a_promoted_build_needs_an_immutable_commit(tmp_path: Path) -> None:
    rows = _set(_register_rows(), "model-gemma-4-26b-a4b-nvfp4", version="revision main")
    builds = _build(_builds(), JUDGE, status="champion", revision="main", expected={"revision": "main"})
    problems = _check(tmp_path, rows, builds)
    assert any("model-gemma-4-26b-a4b-nvfp4" in p and "one full commit id" in p for p in problems), problems
    assert any(JUDGE in p and "'main' is not a full commit id" in p for p in problems), problems
    rows = _set(_register_rows(), "model-gemma-4-26b-a4b-nvfp4", version="")
    builds = _build(_builds(), JUDGE, status="champion", revision=None, expected={"manifest_sha256": "b" * 64})
    (tmp_path / "empty").mkdir()
    problems = _check(tmp_path / "empty", rows, builds)
    assert any(JUDGE in p and "no pinned revision" in p for p in problems), problems


def test_medium_6_an_unmeasured_candidate_can_have_its_terms_verified_before_its_pins(tmp_path: Path) -> None:
    """The registry's unmeasured verifier candidate, verified against a matching cleared row: a source revision in
    its provenance does not make it measured, and no pin is asked of a candidate."""
    bid = "ministral-3-14b-verifier-candidate"
    builds = _builds()
    cand = next(b for b in builds if b["build_id"] == bid)
    assert cand["bakeoff"]["state"] == "unmeasured" and cand["provenance"]["revision"]
    assert not cand["revision"] and not cand["expected"]["revision"]
    rows = _register_rows()
    rows.append({**rows[-1], "id": "model-planted-verifier", "kind": "model", "standard": "planted",
                 "source": cand["repository"], "licence": "Apache-2.0 (fixture)", "spdx": "Apache-2.0",
                 "status": "cleared", "version": f"revision {FULL}", "text_sha256": "", "athena": "", "paths": "",
                 "evidence": "https://example.invalid"})  # fmt: skip
    lic = {**cand["licence"], "verified": True, "register": "model-planted-verifier"}
    assert _check(tmp_path, rows, _build(builds, bid, licence=lic)) == []
