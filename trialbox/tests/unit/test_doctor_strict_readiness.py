"""TRIAGE-1 G2: `trialbox doctor --strict` is the "doctor all true" row of the acceptance. On the R1 box every
readiness item that later broke a night, a backup or the pair canary was a WARN (backup key, KEK, ops timer, memory
caps, served models against their pins), and the poc host profile eased the FAILs it had to WARN. Under --strict each
readiness item must PASS; anything else, or a readiness item the run did not check, is a FAIL and the exit is 1. The
plain doctor is unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import __main__ as cli
from tools.trialbox import doctor as d

pytestmark = pytest.mark.nodb

E2E_LINES = [  # the R1 box's lines (E2E evidence/doctor-envfile.txt), as the doctor gave them
    d.Check("topology", "PASS", "A"),
    d.Check("backup", "WARN", "no backup key"),
    d.Check("key_custody", "WARN", "site_hmac.key, pid_map.key plain on disk in VALIDATION [host profile poc]"),
    d.Check("key_escrow", "WARN", "no KEK: the site keys are not under a KEK"),
    d.Check("ops_runner", "WARN", "the runner has never written status.json [host profile poc]"),
    d.Check("memory_caps", "WARN", "no CURRENT snapshot and no TB_SITE_PATIENTS"),
    d.Check("registry_pins", "WARN", "pinned: none is champion"),
    d.Check("judge_route", "FAIL", "build_unpinned"),
    d.Check("audit_heads", "WARN", "no anchor folder"),
]


def test_every_readiness_warn_is_a_fail_and_the_rest_as_they_were() -> None:
    got = {c.name: c for c in d.strict(E2E_LINES)}
    for name in d.READINESS:
        assert got[name].status == "FAIL", name
    assert "--strict" in got["backup"].detail and "no backup key" in got["backup"].detail
    assert got["audit_heads"].status == "WARN" and got["topology"].status == "PASS"
    assert not d.ok(d.strict(E2E_LINES))


def test_a_ready_box_passes_and_an_unchecked_item_fails() -> None:
    ready = [d.Check(n, "PASS", "ok") for n in d.READINESS] + [d.Check("audit_heads", "WARN", "no anchor folder")]
    assert d.ok(d.strict(ready))
    missing = [c for c in ready if c.name != "ops_runner"]
    got = {c.name: c for c in d.strict(missing)}
    assert got["ops_runner"].status == "FAIL" and "not checked" in got["ops_runner"].detail


def test_the_command_line_takes_strict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def run(*_a: Any, **_k: Any) -> list[d.Check]:
        return list(E2E_LINES)

    monkeypatch.setattr(d, "run", run)
    monkeypatch.setattr(d, "needs_image", lambda: False)
    assert cli.main(["doctor"]) == 1  # judge_route already FAILs: the plain run is as before
    plain = capsys.readouterr().out
    assert "WARN  backup" in plain
    assert cli.main(["doctor", "--strict"]) == 1
    assert "FAIL  backup" in capsys.readouterr().out


def test_the_readiness_items_are_checks_the_doctor_has() -> None:
    names = {fn.__name__.removeprefix("check_") for fn in d.CHECKS}
    module = Path(d.__file__).with_name("doctor_m5.py").read_text(encoding="utf-8")
    for n in d.READINESS:
        assert n in names or f'"{n}"' in module, n
