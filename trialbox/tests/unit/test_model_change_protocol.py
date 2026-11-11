"""The model change protocol against the code (T-649b, D-343): its change ids are the ones `qualify --change`
accepts, its threshold table names every qualify step with the numbers the code uses, every qualification record
cites it, and N-12 gates on the unadjusted figure."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tools import qualify as q

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs" / "validation" / "model-change-protocol.md"
NOTE = ROOT / "docs" / "validation" / "ai-governance.md"


def _table(text: str, heading: str) -> list[list[str]]:
    """The rows (cells stripped) of the first Markdown table under ``## <heading>``."""
    part = text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in part.splitlines() if ln.startswith("|")]
    return [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows[2:]]


@pytest.fixture(scope="module")
def protocol() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def test_every_foreseen_change_is_a_change_id_qualify_accepts(protocol: str) -> None:
    rows = _table(protocol, "2. Foreseen changes")
    assert tuple(r[0] for r in rows) == q.CHANGE_TYPES
    for r in rows:
        assert len(r) == 5 and all(r), f"{r[0]}: a change needs its change, example, test and threshold"
        assert "qualify" in r[3], f"{r[0]}: the test must include the qualify command"


def test_the_threshold_table_names_every_qualify_step_in_order(protocol: str) -> None:
    rows = _table(protocol, "3. Thresholds")
    assert tuple(r[0].strip("`") for r in rows) == q.STEPS
    assert all(r[1] and r[2] for r in rows)
    assert set(q.STEP_FUNCS) == set(q.STEPS)


def _threshold(protocol: str, step: str) -> str:
    return next(r[1] for r in _table(protocol, "3. Thresholds") if r[0].strip("`") == step)


def test_the_thresholds_are_the_numbers_in_the_code(protocol: str) -> None:
    from orchestrator import selftest

    from tools.judge_bakeoff import GateConfig

    canary = _threshold(protocol, "canary")
    assert f"at least {selftest.MIN_ANSWERED * 100:g} % answered" in canary
    assert f"at least {selftest.MIN_ACCURACY * 100:g} % correct" in canary
    assert f"at most {selftest.MAX_FLIPS} flip" in canary
    assert f"at most {selftest.MAX_PAIR_WRONG} cases decided wrong by the pair" in canary
    gate, cfg = _threshold(protocol, "pair_gate"), GateConfig()
    assert f"at most {cfg.max_wrong * 100:g} % of exclusions" in gate
    assert f"at least {cfg.min_exclusions} exclusions" in gate
    assert f"at least {cfg.min_answered} answered" in gate
    assert f"at most {cfg.max_no_answer * 100:g} % with no answer" in gate
    assert f"concurrency {q.REPEAT_WORKERS}" in _threshold(protocol, "determinism")
    assert "**unadjusted**" in _threshold(protocol, "n12") and '"basis": "unadjusted"' in _threshold(protocol, "n12")
    assert "100 %" in _threshold(protocol, "schema")


def test_a_record_cites_the_protocol_by_path_sha_and_change() -> None:
    opts = q.Options(profile="ci", stub=True, operator="test", sources=("synthetic",), change="MC-1")
    doc = q.qualify(opts, steps=("pin",))
    cite = doc["change_protocol"]
    assert cite == {
        "document": "docs/validation/model-change-protocol.md",
        "sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "change": "MC-1",
    }
    assert q.schema_problems(doc) == []
    bare = {k: v for k, v in doc.items() if k != "change_protocol"}
    assert any("change_protocol" in p for p in q.schema_problems(bare))


def test_an_unknown_change_id_is_refused() -> None:
    with pytest.raises(q.QualifyError, match="unknown change MC-99"):
        q.change_protocol("MC-99")


def test_the_command_takes_the_change_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    from tools.trialbox.__main__ import main

    monkeypatch.setattr(q, "STEPS", ("pin",))
    rc = main(["eval", "qualify", "--profile", "ci", "--stub", "--change", "MC-6", "--out", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    doc = json.loads(Path(out["record"]).read_text(encoding="utf-8"))
    assert rc == 0 and doc["change_protocol"]["change"] == "MC-6"
    with pytest.raises(SystemExit):
        main(["eval", "qualify", "--profile", "ci", "--stub", "--change", "MC-99"])


def test_n12_evidence_must_be_unadjusted(tmp_path: Path) -> None:
    import io
    from typing import cast

    head, _ = q.git_head()
    real = q.Options(profile="rtxpro6000", stub=False, operator="test", sources=("synthetic",))

    def run(**doc: Any) -> q.StepResult:
        p = tmp_path / "n12.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        ctx = q.Ctx(replace(real, evidence={"n12": p}), cast(q.Target, None), {}, cast(q.QClient, None),
                    cast(q.QClient, None), tmp_path, io.StringIO())  # fmt: skip
        return q.step_evidence("n12")(ctx)

    good = run(passed=True, head=head, basis="unadjusted")
    assert good.status == "passed" and good.detail["basis"] == "unadjusted"
    for basis in ("audit_adjusted", None):
        r = run(passed=True, head=head, basis=basis)
        assert r.status == "failed" and "basis unadjusted" in r.reason


def test_validation_reports_n12_unadjusted_and_cites_the_protocol() -> None:
    text = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
    section = text.split("## 3. The model gate", 1)[1].split("\n## ", 1)[0]
    row = next(ln for ln in section.splitlines() if ln.startswith("| N-12"))
    assert "unadjusted" in row and "audit-adjusted" not in row
    assert re.search(r"\*\*fail\*\*|pass", row)
    assert "docs/validation/model-change-protocol.md" in section
    assert "docs/validation/ai-governance.md" in section


def test_the_governance_note_covers_the_three_texts_and_cites_the_protocol() -> None:
    note = NOTE.read_text(encoding="utf-8")
    for heading in ("## 2. GMLP", "## 3. Taiwan AI Basic Act", "## 4. Japan: AI Guidelines for Business"):
        assert heading in note
    assert len(_table(note, "2. GMLP")) == 10  # the ten guiding principles
    assert len(_table(note, "3. Taiwan AI Basic Act")) == 7  # the Act's seven principles
    assert len(_table(note, "4. Japan: AI Guidelines for Business")) == 10  # the ten common principles
    assert "docs/validation/model-change-protocol.md" in note
