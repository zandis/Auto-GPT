"""The nightly mutation runner and the coverage ratchet (T-651, ENG-029; TB-DR-04 §3.2, §3.3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools import coverage_ratchet as cr
from tools import mutation as mt

ROOT = Path(__file__).resolve().parents[2]

SAMPLE = '''"""A docstring is never mutated."""


def decide(value: int | None, strict: bool = False) -> str:
    """Neither is this one."""
    if value is None:
        return "unknown"
    if value >= 10 and not strict:
        return "pass"
    total = value + 1  # pragma: no mutate
    return "fail" if total else "x"
'''


def test_the_operators_cover_the_boundary_and_absent_field_cases() -> None:
    ops = {(m.line, m.operator) for m in mt.enumerate_mutants(SAMPLE, "mod.py")}
    assert (6, "cmp:Is->IsNot") in ops  # an absent value treated as present
    assert (8, "cmp:GtE->Gt") in ops  # a boundary moved by one
    assert (8, "bool:and->or") in ops and (8, "not:drop") in ops
    assert (8, "const:+1") in ops
    assert (4, "const:False->True") in ops  # a default
    assert (7, "return:None") in ops
    lines = {line for line, _ in ops}
    assert 1 not in lines and 5 not in lines  # docstrings
    assert 10 not in lines  # the pragma
    assert not any(op == "binop:Add->Sub" for _, op in ops)  # it was on the pragma line
    # the annotation's `int | None` is never touched
    assert all(not op.startswith("binop:BitOr") for _, op in ops)


def test_a_mutant_changes_one_node_and_ids_are_stable() -> None:
    mutants = mt.enumerate_mutants(SAMPLE, "mod.py")
    assert [m.id for m in mutants] == [m.id for m in mt.enumerate_mutants(SAMPLE, "mod.py")]
    flip = next(m for m in mutants if m.operator == "cmp:GtE->Gt")
    assert flip.id == f"mod.py:8:7:{flip.operator}"
    out = mt.apply_mutant(SAMPLE, flip)
    assert "value > 10 and (not strict)" in out or "value > 10 and not strict" in out
    assert "value is None" in out  # nothing else moved
    ns: dict[str, object] = {}
    exec(compile(out, "mod.py", "exec"), ns)
    assert ns["decide"](10) == "fail"  # type: ignore[operator]


def test_the_score_counts_timeouts_as_killed_and_leaves_accepted_out() -> None:
    results = [
        mt.Result("a", "killed"),
        mt.Result("b", "timeout"),
        mt.Result("c", "survived"),
        mt.Result("d", "accepted"),
        mt.Result("e", "no-coverage"),
        mt.Result("g", "not-run"),  # out of time: listed, not scored
    ]
    score, counts = mt.score(results)
    assert score == pytest.approx(50.0) and counts["accepted"] == 1
    text = mt.table([mt.Result("f.py:1:0:x", "survived"), mt.Result("f.py:2:0:y", "killed")], 90.0, 40.0)
    assert "not met yet" in text and "Floor 40.0 %" in text and "held" in text
    assert "`f.py:1:0:x` (survived)" in text


def test_the_runner_kills_what_the_tests_see_and_reports_what_they_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end on a tiny tree: a real pytest per mutant, in a private copy, the original left untouched."""
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "mod.py").write_text(
        "def gate(x):\n    if x >= 10:\n        return 'pass'\n    return 'fail'\n\n\n"
        "def unused(y):\n    return y == 3\n",
        encoding="utf-8",
    )
    (tree / "test_mod.py").write_text(
        "from mod import gate\n\n\ndef test_gate():\n    assert gate(11) == 'pass' and gate(1) == 'fail'\n",
        encoding="utf-8",
    )
    config = mt.Config(
        threshold=90.0,
        floor=50.0,
        targets=[mt.Target("mod.py", ["test_mod.py"])],
        accepted={"mod.py:8:11:cmp:Eq->NotEq": "an example", "mod.py:99:0:gone": "stale"},
    )
    results, meta = mt.run(config, root=tree, workers=2, python=sys.executable, log=False)
    status = {r.mutant: r.status for r in results}
    assert status["mod.py:2:7:cmp:GtE->Gt"] == "survived"  # no test at the boundary 10
    assert status["mod.py:3:8:return:None"] == "killed"
    assert status["mod.py:2:12:const:+1"] == "survived"
    assert status["mod.py:8:4:return:None"] == "no-coverage"
    assert status["mod.py:8:11:cmp:Eq->NotEq"] == "accepted"
    assert meta["stale_accepted"] == ["mod.py:99:0:gone"]
    assert "if x >= 10:" in (tree / "mod.py").read_text(encoding="utf-8")
    assert not list((tmp_path / "scratch").glob("tb-mutation-*"))  # the worker trees are gone


def test_shard_reports_merge_into_one_score_and_the_floor_decides(tmp_path: Path) -> None:
    for i, status in enumerate(("killed", "survived")):
        data = {
            "results": [{"mutant": f"f{i}.py:1:0:x", "status": status, "seconds": 1.0}],
            "meta": {"targets": {f"f{i}.py": {}}, "stale_accepted": []},
        }
        (tmp_path / f"m{i}.json").write_text(json.dumps(data), encoding="utf-8")
    shards = [str(tmp_path / "m0.json"), str(tmp_path / "m1.json")]
    out = tmp_path / "all.json"
    for floor, rc in ((60.0, 1), (50.0, 0)):
        cfg = tmp_path / "mutation.toml"
        cfg.write_text(f"threshold = 90.0\nfloor = {floor}\n", encoding="utf-8")
        assert mt.main(["--config", str(cfg), "--merge", *shards, "--report", str(out)]) == rc
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["score"] == 50.0 and report["floor"] == 50.0 and report["threshold"] == 90.0


def test_the_config_names_the_safety_core_and_every_target_exists() -> None:
    config = mt.load_config()
    assert config.threshold >= 90.0 and config.floor <= config.threshold
    assert "services/matching/proposed.py" in config.safety_core and len(config.safety_core) == 18
    for f in config.safety_core:
        assert (ROOT / f).is_file(), f
    for t in config.targets:
        assert t.file in config.safety_core and (ROOT / t.file).is_file()
        assert t.tests and all((ROOT / p).is_file() for p in t.tests), t.file
    assert cr.safety_core() == config.safety_core


# --- the coverage ratchet ------------------------------------------------------------------------------------------


def _report(files: dict[str, tuple[int, int, int, int]], branch: bool = True) -> dict[str, object]:
    return {
        "meta": {"branch_coverage": branch},
        "files": {
            name: {"summary": {"num_statements": s, "covered_lines": c, "num_branches": b, "covered_branches": cb}}
            for name, (s, c, b, cb) in files.items()
        },
    }


def test_files_are_grouped_by_package() -> None:
    packages, files = cr.measure(
        _report(
            {
                "services/matching/proposed.py": (100, 90, 10, 9),
                "services/matching/cascade/engine.py": (100, 80, 10, 5),
                str(ROOT / "libs/tb_common/pair.py"): (50, 50, 4, 4),
                "tools/doclint.py": (10, 5, 0, 0),
            }
        )
    )
    assert set(packages) == {"services/matching", "libs/tb_common", "tools"}
    assert packages["services/matching"].line == pytest.approx(85.0)
    assert packages["services/matching"].branch == pytest.approx(70.0)
    assert "libs/tb_common/pair.py" in files  # absolute paths made relative to the tree


def test_a_drop_of_more_than_half_a_point_fails_and_a_smaller_one_does_not() -> None:
    base = {"packages": {"services/a": {"line": 90.0, "branch": 80.0}, "services/b": {"line": 90.0}}}
    packages, files = cr.measure(
        _report(
            {
                "services/a/x.py": (1000, 896, 100, 80),
                "services/b/y.py": (1000, 894, 0, 0),
                "services/c/z.py": (1, 0, 0, 0),
            }
        )
    )
    prows, _, failures = cr.check(packages, files, base, [])
    by = {r.name: r.status for r in prows}
    assert by == {"services/a": "ok", "services/b": "DROP", "services/c": "new"}
    assert len(failures) == 1 and failures[0].startswith("services/b: line")
    # a branch drop counts only when both sides have branches
    packages, files = cr.measure(_report({"services/a/x.py": (1000, 900, 100, 70)}))
    assert cr.check(packages, files, base, [])[2]
    packages, files = cr.measure(_report({"services/a/x.py": (1000, 900, 0, 0)}, branch=False))
    assert not cr.check(packages, files, base, [])[2]


def test_safety_core_files_hold_the_target_or_their_own_floor() -> None:
    core = ["services/m/at.py", "services/m/under.py", "services/m/fell.py", "services/m/missing.py"]
    base = {
        "files": {
            "services/m/at.py": {"line": 96.0, "branch": 91.0},
            "services/m/under.py": {"line": 80.0, "branch": 70.0},
            "services/m/fell.py": {"line": 80.0},
        }
    }
    packages, files = cr.measure(
        _report(
            {
                "services/m/at.py": (100, 94, 10, 9),  # under 95 % line: fails although within 0.5 of nothing
                "services/m/under.py": (100, 80, 10, 7),  # under target, at its baseline: listed, passes
                "services/m/fell.py": (100, 79, 0, 0),  # fell more than 0.5 under its own baseline
            }
        )
    )
    _, crows, failures = cr.check(packages, files, base, core)
    by = {r.name: r.status for r in crows}
    assert by == {
        "services/m/at.py": "DROP",
        "services/m/under.py": "under target",
        "services/m/fell.py": "DROP",
        "services/m/missing.py": "not measured",
    }
    assert len(failures) == 2


def test_the_command_line_writes_and_checks_a_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "coverage.json"
    baseline = tmp_path / "baseline.json"
    report.write_text(json.dumps(_report({"services/a/x.py": (100, 90, 0, 0)}, branch=False)), encoding="utf-8")
    baseline.write_text(json.dumps({"packages": {"services/a": {"line": 80.0, "branch": 77.0}}}), encoding="utf-8")
    assert cr.main([str(report), "--baseline", str(baseline)]) == 0
    assert "services/a" in capsys.readouterr().out
    assert cr.main([str(report), "--baseline", str(baseline), "--write-baseline"]) == 0
    written = json.loads(baseline.read_text(encoding="utf-8"))
    assert written["packages"]["services/a"] == {"statements": 100, "line": 90.0, "branch": 77.0}  # branch kept
    report.write_text(json.dumps(_report({"services/a/x.py": (100, 89, 0, 0)}, branch=False)), encoding="utf-8")
    assert cr.main([str(report), "--baseline", str(baseline)]) == 1


def test_a_target_split_in_parts_runs_every_mutant_once_across_the_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENG-006: engine.py's shard ran out of its 200 minutes with 114 mutants not run (nightly of 2026-11-15), so the
    floor could not be raised on a complete score. ``--part K/N`` runs every N-th mutant of the targets (stable
    order); the parts' reports merge into exactly the whole run, no mutant twice, no accepted one called stale."""
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "mod.py").write_text(
        "def gate(x):\n    if x >= 10:\n        return 'pass'\n    return 'fail'\n\n\n"
        "def unused(y):\n    return y == 3\n",
        encoding="utf-8",
    )
    (tree / "test_mod.py").write_text(
        "from mod import gate\n\n\ndef test_gate():\n    assert gate(11) == 'pass' and gate(1) == 'fail'\n",
        encoding="utf-8",
    )
    config = mt.Config(threshold=90.0, floor=50.0, targets=[mt.Target("mod.py", ["test_mod.py"])],
                       accepted={"mod.py:8:11:cmp:Eq->NotEq": "an example", "mod.py:99:0:gone": "stale"})  # fmt: skip
    whole, _ = mt.run(config, root=tree, workers=2, python=sys.executable, log=False)
    parts = []
    for k in (1, 2):
        results, meta = mt.run(config, root=tree, workers=2, python=sys.executable, log=False, part=(k, 2))
        assert results and len(results) < len(whole)
        (tmp_path / f"p{k}.json").write_text(json.dumps({"results": [r.__dict__ for r in results], "meta": meta}),
                                             encoding="utf-8")  # fmt: skip
        parts.append(tmp_path / f"p{k}.json")
    merged, meta = mt._merge(parts)
    assert sorted(r.mutant for r in merged) == sorted(r.mutant for r in whole)  # each once
    assert {r.mutant: r.status for r in merged} == {r.mutant: r.status for r in whole}
    assert meta["stale_accepted"] == ["mod.py:99:0:gone"]  # once, and only the really stale one
    with pytest.raises(SystemExit):
        mt.main(["--part", "3/2", "--list"])
    assert mt.parse_part("2/3") == (2, 3)
