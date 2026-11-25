"""The review of #1484 (H-116, the bench mark), 1484-1: an install with --bench that is refused with "nothing was
changed" leaves no bench mark behind (before, the record was written in the BENCH block, before the KEK passphrase,
the install lock, the host check and the bundle's signature, each of which still said nothing was changed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_bench_box_h116 import _loaded, _prod
from tests.unit.test_test_box_h106 import TEST_ARGS, Engine, H106Box
from tools.trialbox import benchbox, testbox

pytestmark = [pytest.mark.nodb]


@pytest.mark.parametrize(
    ("args", "env"),
    [((), {"TB_KEK_PASSPHRASE": "x"}), (("--kek-passphrase-file", "pass.txt"), {})],
    ids=["kek-in-the-environment", "kek-file-not-a-full-path"],
)
def test_1484_1_a_refused_bench_install_leaves_no_bench_mark(tmp_path: Path, args: tuple[str, ...],
                                                             env: dict[str, str]) -> None:  # fmt: skip
    p = _prod(tmp_path)
    r = p.run("--environment", "PRODUCTION", "--bench", *args, *TEST_ARGS, env=env)
    assert r.rc != 0 and "nothing was changed" in r.err.splitlines()[-1], r.text[-2000:]
    assert not _loaded(p)
    assert not (p.deploy / benchbox.RECORD).exists(), "a refused install that changed nothing left the bench mark"
    assert "TB_BENCH" not in benchbox.read_env(p.deploy / ".env"), "a refused install wrote TB_BENCH"
    assert [(s.project, s.kind) for s in testbox.boxes(Engine({"trialbox": str(p.deploy.parent)}))] == [
        ("trialbox", "production")
    ]
    t = H106Box(tmp_path / "t")
    r = t.run("--test-box", "t", "--port-offset", "1", *TEST_ARGS, engine=f"volume trialbox\ndir trialbox {p.deploy}\n")
    assert r.rc == 1 and "this host holds a PRODUCTION box (project trialbox)" in r.err, r.text[-2000:]
