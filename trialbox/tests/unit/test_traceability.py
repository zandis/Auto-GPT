"""NEW-STD-3 (STD-003): the traceability table is made from the tests and the run's results, not from a plan. A test
declares what it proves (``@pytest.mark.req``); the ids reach the run's JUnit file; TB-DS-01 Appendix D maps them to
requirements; a requirement with no passing test is listed as such, and the report is never a gate (D-311)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import traceability as tr

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

SRS = """# TB-DS-01

| Spec-v4 IDs (markers) | Spec-v4 subject | TB-DS-01 |
| --- | --- | --- |
| CAS-1 (10), CAS-14 (1) | Cascade stages | FR-SCR-01 |
| CAS-2 (1) | Structured criteria never sent to a model | CON-04, FR-SCR-05 |
| CAS-4 (1) | Per-run model budgets | Design (TB-DS-02) |
| DP-01 (1) | Data-platform stages | Retired (not in the baseline) |

After the table.
"""

TRACE = "\n".join([
    '{"test": "tests/unit/test_a.py::test_one", "result": "passed", "req": "CAS-1 CAS-2"}',
    '{"test": "tests/unit/test_a.py::test_two", "result": "failed", "req": "CAS-2"}',
    '{"test": "tests/unit/test_b.py::test_three", "result": "skipped", "req": "ZZ-9"}',
]) + "\n"  # fmt: skip


def test_appendix_d_maps_each_spec_id_and_marks_design_and_retired(tmp_path: Path) -> None:
    (tmp_path / "srs.md").write_text(SRS, encoding="utf-8")
    m = tr.appendix(tmp_path / "srs.md")
    assert m == {"CAS-1": ["FR-SCR-01"], "CAS-14": ["FR-SCR-01"], "CAS-2": ["CON-04", "FR-SCR-05"],
                 "CAS-4": ["Design"], "DP-01": ["Retired"]}  # fmt: skip


def test_the_table_has_each_requirement_its_tests_and_the_verdict_never_a_gate(tmp_path: Path) -> None:
    (tmp_path / "srs.md").write_text(SRS, encoding="utf-8")
    (tmp_path / "trace.jsonl").write_text(TRACE, encoding="utf-8")
    rc = tr.main(["--srs", str(tmp_path / "srs.md"), "--out", str(tmp_path / "out"), str(tmp_path / "trace.jsonl")])
    assert rc == 0  # a failing requirement is reported, not a failed command (D-311)
    md = (tmp_path / "out" / "traceability.md").read_text(encoding="utf-8")
    assert "| FR-SCR-01 | CAS-1 | 1 | 1 | 0 | 0 | passing |" in md
    assert "| FR-SCR-05 | CAS-2 | 2 | 1 | 1 | 0 | FAILING |" in md and "| CON-04 | CAS-2 |" in md
    assert "| Unmapped | ZZ-9 | 1 | 0 | 0 | 1 | skipped only |" in md
    unmapped = md.split("does not map")[1].split("##")[0]
    untested = md.split("no test in this run cites")[1]
    assert "- ZZ-9" in unmapped and "- CAS-4" in untested and "- DP-01" in untested
    rows = (tmp_path / "out" / "traceability.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "requirement,spec_v4_id,test,result"
    assert "FR-SCR-05,CAS-2,tests/unit/test_a.py::test_two,failed" in rows
    assert "requirements: 4" in (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")


def test_unreadable_input_is_exit_2(tmp_path: Path) -> None:
    (tmp_path / "srs.md").write_text("no table here\n", encoding="utf-8")
    (tmp_path / "trace.jsonl").write_text(TRACE, encoding="utf-8")
    assert (
        tr.main(["--srs", str(tmp_path / "srs.md"), "--out", str(tmp_path / "o"), str(tmp_path / "trace.jsonl")]) == 2
    )


def test_the_shipped_srs_has_its_appendix() -> None:
    m = tr.appendix(ROOT / "docs" / "plan" / "design" / "01-SRS.md")
    assert len(m) > 100 and all(v for v in m.values())


def test_a_run_with_tb_trace_out_records_what_each_test_proves(tmp_path: Path) -> None:
    """tests/conftest.py writes the trace of a real run: a test with a req marker and its result; one without none."""
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "test_probe.py").write_text(
        "import pytest\n\n\n@pytest.mark.nodb\n@pytest.mark.req('CAS-2', 'CAS-1')\ndef test_x():\n    assert True\n\n\n"
        "@pytest.mark.nodb\n@pytest.mark.req('CAS-4')\ndef test_y():\n    assert False\n\n\n@pytest.mark.nodb\ndef test_z():\n    pass\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))
    env["TB_TRACE_OUT"] = str(tmp_path / "trace.jsonl")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "-n", "0",
                        "-p", "tests.conftest", "--rootdir", str(probe), "-c", os.devnull, str(probe)], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=300, check=False)  # fmt: skip
    assert r.returncode == 1, r.stdout[-1500:] + r.stderr[-1500:]  # test_y fails on purpose
    got = {c.test.rsplit("::", 1)[1]: (c.reqs, c.result) for c in tr.cases([tmp_path / "trace.jsonl"])}
    assert got == {"test_x": (("CAS-1", "CAS-2"), "passed"), "test_y": (("CAS-4",), "failed")}


def test_ci_writes_the_shards_junit_and_renders_the_table_without_gating() -> None:
    import yaml

    wf = yaml.safe_load((ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml").read_text(encoding="utf-8"))
    shard_run = "\n".join(str(s.get("run", "")) for s in wf["jobs"]["unit-shard"]["steps"])
    assert 'TRACE="$RUNNER_TEMP/shard/trace.jsonl"' in shard_run
    (step,) = [s for s in wf["jobs"]["unit"]["steps"] if "tools.traceability" in str(s.get("run", ""))]
    assert step["continue-on-error"] is True  # never a gate (D-311)
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert '$(if $(TRACE),TB_TRACE_OUT="$(TRACE)",)' in make
