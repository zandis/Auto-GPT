"""H-32 (D-1110): the planted-faults drill on the in-process box, the seven faults of plan 8's V17 one at a time.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_planted_faults_drill.py
    make planted-faults                                  # the same; the record goes to TB_PLANTED_FAULTS_OUT if set

It fails when a fault could not be planted, when the box was not green before a fault, when a fault does not clear
by itself, and when what a person met differs from the table of the findings page
(``docs/plan/measurements/planted-faults-2026-11-18.md``): a fix that makes a fault show changes this table and the
page together. Run as root, the backup target and the watched disk are real mounts; otherwise the disk is planted by
a stand-in (the record says which).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tools import planted_faults as pf

pytestmark = [pytest.mark.integration, pytest.mark.slow]

NS, NL = "not shown", "not in the language"
#: fault -> (first page en, zh-TW, ja; mail; /metrics; the runbook page the line or mail names)
EXPECTED: dict[str, tuple[str, str, str, str, str, bool]] = {
    "backup_target": (NS, NS, NS, NL, "shown", True),
    "disk_full": (NS, NS, NS, NL, "shown", False),
    "morning_mail": (NS, NS, NS, NS, NS, False),
    "certificate": (NS, NS, NS, NL, "shown", False),
    "clock_off": (NS, NS, NS, NS, NS, False),
    "model_down": (NS, NS, NS, NS, NS, False),
    "feed_empty": (NS, NS, NS, NS, NS, False),
}


def test_each_planted_fault_as_a_person_meets_it(db_url: str, tmp_path: Path) -> None:
    out = Path(os.environ.get("TB_PLANTED_FAULTS_OUT") or tmp_path / "planted-faults.json")
    rec = pf.run(out, db_url=db_url, root=tmp_path)
    by = {r["fault"]: r for r in rec["faults"]}
    assert set(by) == set(EXPECTED)
    for key, want in EXPECTED.items():
        r: dict[str, Any] = by[key]
        assert "error" not in r, (key, r.get("error"))
        assert r["green_before"] is True, (key, r["green_before"])
        got = (*(r["page"][lang]["verdict"] for lang in pf.LANGS), r["mail"]["verdict"], r["metrics"]["verdict"],
               r["runbook"]["leads_there"])  # fmt: skip
        assert got == want, (key, got)
        assert r["cleared"]["metrics"] and all(r["cleared"]["page"].values()), (key, r["cleared"])
        assert r["cleared"]["mail_next_morning"], (key, r["cleared"])
        assert r.get("second_round_same_day", 0) == 0, key  # a mail goes once a day, never twice
    # the backup night failed on the unwritable target, and the alert route named RUNBOOK §5
    assert by["backup_target"]["night"]["ok"] is False and by["backup_target"]["clear_night"]["ok"] is True
    assert any(m["route"] == "backup-alert" for m in by["backup_target"]["mail"]["mails"])
    if rec["mounts"]["nas"]:  # the share unmounted: the night wrote to the box's own disk and every surface stayed ok
        gone = by["backup_target"]["gone"]
        assert gone["night"]["ok"] is True and gone["written_on_box_disk"]
        assert gone["after_night"]["metrics"]["level"] == "ok"
    # the model down with no passing canary: the Health tab's line in three languages and /metrics canary warn
    nc = by["model_down"]["no_passing_canary"]
    assert [nc["page"][lang]["verdict"] for lang in pf.LANGS] == ["shown"] * 3
    assert nc["metrics"]["moved"] == {"canary": "warn"}
    # the clock: the product's own check sees the offset; the feed: the adapter holds the empty night
    assert by["clock_off"]["product_check"]["status"] == "FAIL"
    assert by["feed_empty"]["empty_night"]["held"] is True and by["feed_empty"]["clear_night"]["held"] is False
