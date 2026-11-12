"""The scale gate (T-687, D-471; TST-PERF; plan v6.1 §5 item 4: the nightly `scale` gate).

The night of a hospital at ``TB_SCALE_PATIENTS`` synthetic patients (the nightly job: 50,000), each part under the
memory cap of its compose service, with the slow model stand-in (``tools/scale_gate.py`` has the parts). One test per
check: a check of :data:`tools.scale_gate.EXPECTED` that applies at this size is a strict expected failure naming its
findings and card (it shows as XFAIL; a pass fails the job until the card removes its line); a check that a failed
part left without input is skipped with the part that blocked it. The report is ``$TB_SCALE_OUT/scale_gate.md``.

Marker ``perf``: not in the unit run (the gate's own logic is in ``tests/unit/test_scale_gate_logic.py``).

    TB_SCALE_PATIENTS=50000 TB_SCALE_ENFORCE=cgroup TB_SCALE_LATENCY_S=2 TB_SCALE_OUTAGE_AFTER=300 \\
      TB_SCALE_OUTAGE_S=40 TB_SCALE_RESTART_AFTER=900 pytest tests/perf/test_scale_gate.py -m perf
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from tb_testkit import scale

from tools import scale_gate as sg

pytestmark = pytest.mark.perf
PATIENTS = int(os.environ.get("TB_SCALE_PATIENTS") or 300)


def _params() -> list[Any]:
    out = []
    for cid in sg.CHECKS:
        exp = sg.EXPECTED.get(cid)
        marks = []
        if exp is not None and exp.applies(PATIENTS):
            marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{exp.label()}: {exp.why}")]
        out.append(pytest.param(cid, marks=marks, id=cid))
    return out


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> sg.Report:
    out = Path(os.environ.get("TB_SCALE_OUT") or tmp_path_factory.mktemp("scale-gate"))
    rep = sg.run(sg.params_from_env(out, PATIENTS))
    print(rep.markdown())
    return rep


@pytest.mark.parametrize("cid", _params())
def test_scale_gate(report: sg.Report, cid: str) -> None:
    row = next(r for r in report.rows() if r["check"] == cid)
    if row["state"] == scale.BLOCKED:
        pytest.skip(f"blocked by {row['blocked_by']}: {row['detail']}")
    check = next(c for c in report.checks if c.id == cid)
    assert check.passed, f"{sg.CHECKS[cid]}: {check.detail}"
