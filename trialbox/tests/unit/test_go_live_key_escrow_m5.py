"""INT-M5 line 4 (R22-33): go-live is refused while a TPM-sealed box has no key escrow.

A TPM box's KEK (back end ``file``) is bound to its board: a dead board opens nothing, and a restore on new hardware
needs the escrow set (TB-SOP-03 §5, D-894). The box passed the health check and go-live without one: the doctor's
``key_ceremony`` line only warned (and passed a ceremony record that lists no escrow), and the acceptance had no
escrow criterion. Now the acceptance has one (``key_escrow``), which fails closed: no KEK, a TPM KEK with no set, a set
of an older KEK, or a newest ceremony record that does not list the set is a FAIL, and its report says NOT YET while
the criterion has not passed or was not run. The doctor's row ``key_escrow`` (through F0's hook, ``doctor_m5``) names
the open gate on a strict box; it is a WARN, never a FAIL, so an installed box before its ceremony stays green.

Synthetic KEK ids, set ids and custodian names only; no key, no share is made here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import acceptance as acc
from tools import key_escrow as ke

KEK_ID = "kek-synthetic-1"
SET = {"set_id": "esc-synthetic-1", "threshold": 2, "count": 3, "kek_id": KEK_ID, "made_at": "2026-11-20T10:00:00+00:00",
       "shares": [{"share": i, "of": 3, "custodian": f"Custodian {i}", "fingerprint": f"fp{i}"} for i in (1, 2, 3)]}  # fmt: skip


def _secrets(tmp_path: Path, backend: str = "file", escrow: dict[str, Any] | None = None) -> Path:
    from tb_common import kek

    sec = tmp_path / "secrets"
    sec.mkdir(mode=0o700, exist_ok=True)
    meta: dict[str, Any] = {"format": kek.META_FORMAT, "backend": backend, "kek_id": KEK_ID}
    if escrow is not None:
        meta["escrow"] = escrow
    (sec / kek.META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    return sec


def _record(deploy: Path, kek_id: str = KEK_ID, escrow: dict[str, Any] | None = None) -> None:
    from tools import key_ceremony as kc

    site = deploy / "site"
    site.mkdir(parents=True, exist_ok=True)
    rec: dict[str, Any] = {"format": kc.FORMAT, "at": "2026-11-20T11:00:00+00:00", "kek": {"kek_id": kek_id},
                           "custodians": ["Custodian 1", "Custodian 2", "Custodian 3"]}  # fmt: skip
    if escrow is not None:
        rec["escrow"] = ke.summary(escrow)
    (site / f"{kc.PREFIX}20261120T110000Z.json").write_text(json.dumps(rec), encoding="utf-8")


def _state(tmp_path: Path) -> tuple[bool, str]:
    return ke.go_live(tmp_path / "secrets", tmp_path / "deploy")


def test_a_tpm_box_with_no_escrow_set_is_refused_at_go_live(tmp_path: Path) -> None:
    _secrets(tmp_path)
    _record(tmp_path / "deploy")
    ok, why = _state(tmp_path)
    assert not ok and "no escrow set" in why and "escrow-shares" in why, why
    body = acc.check_key_escrow(tmp_path / "secrets", tmp_path / "deploy")
    assert body["passed"] is False and "no escrow set" in body["summary"]


def test_a_tpm_box_whose_set_is_on_the_newest_record_passes(tmp_path: Path) -> None:
    _secrets(tmp_path, escrow=SET)
    _record(tmp_path / "deploy", escrow=SET)
    ok, why = _state(tmp_path)
    assert ok and str(SET["set_id"]) in why and "2 of 3" in why, why


@pytest.mark.parametrize(
    ("escrow", "record_kek", "record_escrow", "said"),
    [
        ({**SET, "kek_id": "kek-older"}, KEK_ID, {**SET, "kek_id": "kek-older"}, "older KEK"),
        (SET, KEK_ID, None, "not on the newest ceremony record"),
        (SET, "kek-older", SET, "ceremony record is of KEK kek-older"),
        (SET, None, None, "no key ceremony record"),
    ],
)
def test_every_gap_in_the_escrow_fails_closed(tmp_path: Path, escrow: dict[str, Any], record_kek: str | None,
                                              record_escrow: dict[str, Any] | None, said: str) -> None:  # fmt: skip
    _secrets(tmp_path, escrow=escrow)
    if record_kek is not None:
        _record(tmp_path / "deploy", kek_id=record_kek, escrow=record_escrow)
    ok, why = _state(tmp_path)
    assert not ok and said in why, why


def test_no_kek_and_an_unreadable_secrets_folder_fail_closed(tmp_path: Path) -> None:
    ok, why = _state(tmp_path)
    assert not ok and "not here" in why, why
    (tmp_path / "secrets").mkdir()
    ok, why = _state(tmp_path)
    assert not ok and "no KEK" in why, why


def test_a_kek_not_bound_to_the_board_needs_no_escrow_set(tmp_path: Path) -> None:
    _secrets(tmp_path, backend="shamir")
    ok, why = _state(tmp_path)
    assert ok and "shamir" in why, why


def test_the_report_is_not_yet_until_the_escrow_criterion_passed(tmp_path: Path) -> None:
    out = tmp_path / "acc"
    for name in acc.TARGETS:
        if name != "key_escrow":
            acc._save(out, name, {"passed": True, "summary": "synthetic"})
    md = acc.report(out)
    assert "| key_escrow |" in md and "not run" in md and "Overall: NOT YET" in md, md
    _secrets(tmp_path)
    _record(tmp_path / "deploy")
    rc = acc.main(["--out", str(out), "key-escrow", "--secrets", str(tmp_path / "secrets"), "--deploy",
                   str(tmp_path / "deploy")])  # fmt: skip
    assert rc == 1 and json.loads((out / "key_escrow.json").read_text())["passed"] is False
    assert "Overall: NOT YET" in acc.report(out)
    _secrets(tmp_path, escrow=SET)
    _record(tmp_path / "deploy", escrow=SET)
    rc = acc.main(["--out", str(out), "key-escrow", "--secrets", str(tmp_path / "secrets"), "--deploy",
                   str(tmp_path / "deploy")])  # fmt: skip
    assert rc == 0 and "Overall: PASS" in acc.report(out)


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "WARN"), ("VALIDATION", "WARN"), ("TEST", "PASS")])
def test_the_doctor_row_names_the_open_gate_through_the_hook_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str, status: str
) -> None:
    from tools.trialbox import doctor

    monkeypatch.delenv("TB_SECRETS_DIR", raising=False)
    sec = _secrets(tmp_path)
    _record(tmp_path / "deploy")
    inp = doctor.DoctorInputs(env={"TB_ENV": env, "TB_SECRETS_DIR": str(sec)}, deploy=tmp_path / "deploy")
    rows = [c for c in doctor.module_rows(inp, []) if c.name == "key_escrow"]
    assert [c.status for c in rows] == [status], rows
    if status == "WARN":
        assert "[go-live gate key-escrow: open]" in rows[0].detail and "escrow-shares" in rows[0].detail, rows
    _secrets(tmp_path, escrow=SET)
    _record(tmp_path / "deploy", escrow=SET)
    rows = [c for c in doctor.module_rows(inp, []) if c.name == "key_escrow"]
    assert [c.status for c in rows] == ["PASS"], rows
