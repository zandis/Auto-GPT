# ruff: noqa: F811 - the svc fixture is imported from test_site_setup and taken by name
"""ERASE-A4 (D-869): a patient's own upload to the site set-up goes whole at an opt-out.

A chart uploaded for one patient (``sitesetup.input`` with the patient's pseudonym) is the patient's: the opt-out
worker deletes its files on disk (the upload, its text, its lake text), its check items, its column fixes, its facts
and the row. Another patient's chart stays, and so does a sheet of many patients (it stays owed: its rows are not
keyed by patient). A worker that cannot reach the files never calls them cleared. Synthetic data only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_site_setup import WS, pid, svc  # noqa: F401 - the fixture is used by name

CHART = "診断: 関節リウマチ (synthetic)".encode()


def _env(db_url: str, root: Path | None) -> Any:
    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    return WorkerEnv(register=OptOutRegister(db_url), audit=None, now=datetime(2026, 11, 16, tzinfo=UTC),
                     extra={"setup_root": root})  # fmt: skip


def _files(root: Path, iid: int) -> list[str]:
    return sorted(p.name for p in (root / WS / "inputs").glob(f"{iid}.*"))


def test_a_patients_own_chart_goes_whole_and_another_stays(svc: Any, db_url: str) -> None:
    from datacore.optout_worker import clear_setup_uploads, verify_setup_uploads

    a = svc.add_chart(WS, "10000001", "a.txt", CHART, "crc")
    c = svc.add_chart(WS, "10000002", "c.txt", CHART, "crc")
    assert _files(svc.root, a["input"]) and _files(svc.root, c["input"])
    env = _env(db_url, svc.root)
    gone = frozenset({pid("10000001")})
    assert verify_setup_uploads(gone, env) == {"sitesetup.input": 1}
    assert clear_setup_uploads(gone, env) == {"sitesetup.input": 1}
    assert verify_setup_uploads(gone, env) == {"sitesetup.input": 0}
    assert _files(svc.root, a["input"]) == [] and _files(svc.root, c["input"])  # the other chart's files stay
    assert {i["id"] for i in svc.store.inputs(WS)} == {c["input"]}  # the marker of A is listed nowhere
    assert all(f["pid"] != pid("10000001") for f in svc.store.facts(WS))
    env.register.close()


def test_with_no_folder_the_uploads_are_never_called_cleared(svc: Any, db_url: str) -> None:
    from datacore.optout_worker import clear_setup_uploads

    svc.add_chart(WS, "10000001", "a.txt", CHART, "crc")
    env = _env(db_url, None)
    with pytest.raises(RuntimeError):
        clear_setup_uploads(frozenset({pid("10000001")}), env)
    assert len(svc.store.inputs(WS)) == 1  # nothing deleted
    env.register.close()


def test_an_upload_that_raced_the_clear_is_finished_and_nothing_else_is_swept(svc: Any, db_url: str) -> None:
    """The review of D-869: the erased upload's row stays as a marker, and each tick sweeps the marked ids only: a
    file or fact the racing upload wrote after the clear goes on the next tick; a file no row names is never swept
    (a database restored behind its files would otherwise lose every upload)."""
    from datacore.optout_worker import clear_setup_uploads, verify_setup_uploads

    a = svc.add_chart(WS, "10000001", "a.txt", CHART, "crc")
    env = _env(db_url, svc.root)
    gone = frozenset({pid("10000001")})
    clear_setup_uploads(gone, env)
    row = svc.store.db.fetchone("SELECT status, pid, name, sha256, ref_day FROM input WHERE id = ?", (a["input"],))
    assert row is not None and tuple(row) == ("erased", None, "", "", "")  # the marker: nothing of the patient
    inputs = svc.root / WS / "inputs"
    late, stray = inputs / f"{a['input']}.lake.txt", inputs / "999.txt"
    late.write_text("the racing upload's text")
    stray.write_text("a file no row names")
    svc.store.db.execute("INSERT INTO fact (ws, input_id, pid, domain, status, at) VALUES (?, ?, ?, 'dx', 'ok', 'n')",
                         (WS, a["input"], pid("10000001")))  # fmt: skip
    assert verify_setup_uploads(gone, env)["sitesetup.input"] == 2  # the late file and the late fact
    clear_setup_uploads(gone, env)
    assert verify_setup_uploads(gone, env)["sitesetup.input"] == 0
    assert not late.exists() and stray.exists()
    env.register.close()


def test_a_publish_skips_a_chart_deleted_under_it(svc: Any) -> None:
    c = svc.add_chart(WS, "10000002", "c.txt", CHART, "crc")
    (svc.root / WS / "inputs" / f"{c['input']}.lake.txt").unlink()
    assert svc.chart_texts(WS) == []
