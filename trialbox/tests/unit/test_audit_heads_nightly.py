"""NEW-STD-2 (STD-002, LIFE-010, D-562): the signed audit heads of D-355 are made every night on a box. The nightly
command checks the chain against every earlier signed head before it signs again, publishes the new head write-once
to every anchor folder, and records the event through the audit journal: the host never writes the audit volume
(D-394). ``doctor`` fails in PRODUCTION when no anchor folder is set, the key is missing or the newest head is old.
Synthetic events only."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit
from tb_common.audit import GENESIS, AuditLog, canonical, line_hash, read_signed_heads, write_head
from tb_common.crypto import ed25519_generate

from tools import audit_verify
from tools.trialbox import audit_heads, doctor
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)
NIGHT = datetime(2026, 11, 7, 0, 25, tzinfo=UTC)

pytestmark = pytest.mark.nodb


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV):
        monkeypatch.delenv(var, raising=False)
    paths = {name: tmp_path / name for name in ("audit", "share", "share2", "secrets", "run", "deploy")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert audit_verify.init_key(paths["secrets"]) == 0
    return paths


def _events(log: AuditLog, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        log.append("test.event", ts=T0 + timedelta(minutes=i), actor="tester", detail={"n": i})


def _state(folder: Path) -> dict[str, tuple[bytes, int, int]]:
    """Every file of the audit folder with its bytes, owner and mode: what the host must leave as it is."""
    return {p.name: (p.read_bytes(), p.stat().st_uid, p.stat().st_mode) for p in sorted(folder.iterdir())}


def _remove_line_and_rehash(audit_dir: Path, drop: int) -> None:
    """What a process that can write the audit volume does: remove event ``drop`` (1-based), recompute every hash
    after it and rewrite HEAD.json to match (STD-002's attack). The unkeyed chain and its anchor then agree."""
    prev, n, last_file = GENESIS, 0, None
    for f in sorted(audit_dir.glob("*.jsonl")):
        out = []
        for raw in f.read_text(encoding="utf-8").splitlines():
            n += 1
            if n == drop:
                continue
            body = {k: v for k, v in json.loads(raw).items() if k not in ("prev_hash", "hash")}
            body["prev_hash"] = prev
            body["hash"] = prev = line_hash(prev, body)
            out.append(canonical(body))
        f.write_text("\n".join(out) + "\n", encoding="utf-8")
        last_file = f.name
    write_head(audit_dir, n - 1, prev, last_file)


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.fail = fail

    def __call__(self, event: str, actor: str, detail: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("the journal did not take it")
        self.events.append((event, actor, detail))


def _night(box: dict[str, Path], rec: Recorder, now: datetime = NIGHT, targets: list[Path] | None = None) -> Any:
    return audit_heads.sign_night(
        box["audit"], box["secrets"], [box["share"]] if targets is None else targets, record=rec, now=now
    )


# ------------------------------------------------------------------------------------------------ the nightly run
def test_a_night_signs_publishes_and_records_and_leaves_the_audit_folder_alone(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 5)
    before = _state(box["audit"])
    rec = Recorder()
    res = _night(box, rec, targets=[box["share"], box["share2"]])
    assert res.ok, res.problems
    assert _state(box["audit"]) == before  # D-394: the host writes nothing there, not even the event
    anchor = audit.read_head(box["audit"])
    assert anchor is not None
    for share in (box["share"], box["share2"]):
        heads = read_signed_heads(share)
        assert [h["lines"] for h in heads] == [5] and heads[0]["hash"] == anchor["hash"]
    assert len(rec.events) == 1
    event, actor, detail = rec.events[0]
    assert event == audit.SIGNED_EVENT and actor == "trialbox:audit-sign"
    assert detail["lines"] == 5 and detail["anchors"] == 2 and "failed" not in detail


def test_the_host_does_not_make_the_writers_lock_file(box: dict[str, Path]) -> None:
    """A lock file made by the host's root could not be opened for writing by the audit writer."""
    _events(AuditLog(box["audit"]), 2)
    (box["audit"] / ".lock").unlink()
    assert _night(box, Recorder()).ok
    assert not (box["audit"] / ".lock").exists()


def test_a_rewritten_chain_is_never_signed_again(box: dict[str, Path]) -> None:
    log = AuditLog(box["audit"])
    _events(log, 6)
    assert _night(box, Recorder()).ok
    _events(log, 3, start=6)
    _remove_line_and_rehash(box["audit"], 4)
    assert audit.verify(box["audit"]).ok  # the unkeyed chain and its own anchor agree: the review's PASS
    rec = Recorder()
    res = _night(box, rec, now=NIGHT + timedelta(days=1))
    assert not res.ok and "signed head" in " ".join(res.problems)
    assert len(read_signed_heads(box["share"])) == 1 and not rec.events  # nothing new signed, nothing recorded


def test_a_second_night_adds_a_head_and_both_hold(box: dict[str, Path]) -> None:
    log = AuditLog(box["audit"])
    _events(log, 4)
    assert _night(box, Recorder()).ok
    _events(log, 4, start=4)
    assert _night(box, Recorder(), now=NIGHT + timedelta(days=1)).ok
    assert [h["lines"] for h in read_signed_heads(box["share"])] == [4, 8]


def test_a_head_signed_by_a_key_the_box_does_not_hold_stops_the_night(box: dict[str, Path]) -> None:
    """The trusted keys are the box's own (the secrets folder), not whatever the anchor folder's keys/ offers."""
    _events(AuditLog(box["audit"]), 3)
    priv, pub = ed25519_generate()
    head = audit.read_head(box["audit"])
    assert head is not None
    audit.publish_head(box["share"], audit.make_signed_head(3, head["hash"], head["file"], priv, pub, ts=T0), pub)
    res = _night(box, Recorder())
    assert not res.ok and len(read_signed_heads(box["share"])) == 1


def test_no_folder_a_folder_inside_the_audit_volume_and_a_missing_key_are_refused(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 2)
    assert not _night(box, Recorder(), targets=[]).ok
    inside = box["audit"] / "anchors"
    inside.mkdir()
    res = _night(box, Recorder(), targets=[inside])
    assert not res.ok and "inside the audit folder" in " ".join(res.problems) and not list(inside.iterdir())
    inside.rmdir()
    (box["secrets"] / audit.SIGN_KEY_FILE).unlink()
    res = _night(box, Recorder())
    assert not res.ok and not read_signed_heads(box["share"])


def test_a_folder_that_is_not_there_fails_the_night_but_the_others_take_the_head(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 2)
    rec = Recorder()
    res = _night(box, rec, targets=[box["share"], box["share"].parent / "unmounted"])
    assert not res.ok and len(read_signed_heads(box["share"])) == 1
    assert rec.events and rec.events[0][2]["anchors"] == 1 and rec.events[0][2]["failed"]


def test_a_head_that_was_published_but_not_recorded_fails_the_night(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 2)
    res = _night(box, Recorder(fail=True))
    assert not res.ok and "not recorded" in " ".join(res.problems)
    assert len(read_signed_heads(box["share"])) == 1  # the head is good; the next night signs again


def test_a_chain_with_no_event_yet_is_not_a_failure(box: dict[str, Path]) -> None:
    res = _night(box, Recorder())
    assert res.ok and res.signed is None and not read_signed_heads(box["share"])


# ------------------------------------------------------------------------------------------------ the command
def test_the_command_runs_on_an_in_process_box_and_writes_the_event_itself(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _events(AuditLog(box["audit"]), 3)
    (box["deploy"] / ".env").write_text(
        f"TB_TZ=Asia/Taipei\nTB_ENV=DEV\nTB_AUDIT_HOST_DIR={box['audit']}\nTB_SECRETS_HOST_DIR={box['secrets']}\n"
        f"TB_AUDIT_ANCHOR_TARGETS={box['share']}\n",
        encoding="utf-8",
    )
    assert cli(["audit-sign", "--deploy", str(box["deploy"]), "--local"]) == 0
    assert "signed head: event 3" in capsys.readouterr().out
    res = audit.verify(box["audit"], signed_heads=read_signed_heads(box["share"]),
                       trusted_keys=audit.read_public_keys([box["secrets"]]))  # fmt: skip
    assert res.ok and res.lines == 4  # the three events and audit.head_signed


def test_on_a_site_box_the_signer_sees_the_audit_volume_read_only_and_the_event_goes_to_the_journal(
    box: dict[str, Path],
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **kw: Any) -> str:
        calls.append(argv)
        if "run" in argv[:3]:
            return json.dumps({"ok": True, "problems": [], "signed": {"lines": 7, "hash": "ab" * 32, "key_id": "k"},
                               "detail": {"lines": 7, "head": "ab" * 32, "key_id": "k", "anchors": 1}})  # fmt: skip
        return ""

    env = {"TB_AUDIT_HOST_DIR": str(box["audit"]), "TB_SECRETS_HOST_DIR": str(box["secrets"]),
           "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), "TB_ENV": "PRODUCTION", "TB_KEK_PASSPHRASE": "never-passed"}  # fmt: skip
    res = audit_heads.sign_on_box(box["deploy"], env, run=run)
    assert res.ok
    signer, record = calls
    joined = " ".join(signer)
    assert f"{box['audit']}:{box['audit']}:ro" in joined and "--network none" in joined
    assert f"{box['share']}:{box['share']}" in joined and f"{box['secrets']}:{box['secrets']}:ro" in joined
    assert "never-passed" not in joined and "TB_KEK_PASSPHRASE" in signer  # by name only, never on the command line
    assert record[record.index("exec") :][:3] == ["exec", "-T", "orchestrator"]
    assert audit.SIGNED_EVENT in " ".join(record) and '"lines": 7' in record[-1]


# ------------------------------------------------------------------------------------------------ doctor
def _doctor(box: dict[str, Path], env: str, now: datetime, **more: str) -> doctor.Check:
    e = {"TB_ENV": env, "TB_SECRETS_HOST_DIR": str(box["secrets"]), "TB_AUDIT_HOST_DIR": str(box["audit"]), **more}
    return doctor.check_audit_heads(doctor.DoctorInputs(env=e, deploy=box["deploy"]), now=now)


def test_doctor_passes_a_box_with_a_fresh_head(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 2)
    assert _night(box, Recorder()).ok
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=10), TB_AUDIT_ANCHOR_TARGETS=str(box["share"]))
    assert (c.name, c.status) == ("audit_heads", "PASS"), c.detail


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("DEV", "WARN")])
def test_doctor_fails_a_box_with_no_anchor_folder(box: dict[str, Path], env: str, status: str) -> None:
    c = _doctor(box, env, NIGHT)
    assert c.status == status and "TB_AUDIT_ANCHOR_TARGETS" in c.detail


def test_doctor_fails_an_old_head_a_folder_with_none_and_a_missing_key(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 2)
    targets = {"TB_AUDIT_ANCHOR_TARGETS": str(box["share"])}
    c = _doctor(box, "PRODUCTION", NIGHT, **targets)
    assert c.status == "FAIL" and "no signed head" in c.detail
    assert _night(box, Recorder()).ok
    assert _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=35), **targets).status == "PASS"
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=37), **targets)
    assert c.status == "FAIL" and "37 h" in c.detail
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=37), TB_AUDIT_HEAD_MAX_AGE_H="48", **targets)
    assert c.status == "PASS"
    both = {"TB_AUDIT_ANCHOR_TARGETS": os.pathsep.join([str(box["share"]), str(box["share2"])])}
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=1), **both)
    assert c.status == "FAIL" and str(box["share2"]) in c.detail  # every folder, not the best one
    (box["secrets"] / audit.SIGN_KEY_FILE).unlink()
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=1), **targets)
    assert c.status == "FAIL" and "audit signing key" in c.detail


def test_doctor_fails_an_anchor_folder_on_the_audit_volume(box: dict[str, Path]) -> None:
    inside = box["audit"] / "anchors"
    inside.mkdir()
    c = _doctor(box, "PRODUCTION", NIGHT, TB_AUDIT_ANCHOR_TARGETS=str(inside))
    assert c.status == "FAIL" and "audit volume" in c.detail


def test_the_check_is_one_of_doctors_and_the_age_is_a_declared_setting() -> None:
    from tb_common.config import DECLARED

    assert doctor.check_audit_heads in doctor.CHECKS
    assert DECLARED["TB_AUDIT_HEAD_MAX_AGE_H"].default == "36"


# ------------------------------------------------------------------------------------------------ the installer
def test_the_installer_makes_the_key_and_schedules_the_night() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    cron = next(line for line in text.splitlines() if "tools.trialbox audit-sign" in line)
    daily = next(line for line in text.splitlines() if "tools.trialbox logs daily" in line)
    assert "trialbox-retention" in text[text.index(daily) : text.index(cron) + len(cron)]  # the same cron file
    # the key is made where both install forms seal the site keys, once, and a failure there is not a stop (OPS-003)
    seal = (ROOT / "deploy" / "hardening" / "seal_keys.sh").read_text(encoding="utf-8")
    step = seal[seal.index("audit_key() {") :].split("\n}\n", 1)[0]
    assert "tools.trialbox.audit_heads --init-key" in step and "hb_die" not in step and "|| hb_say" in step
    assert seal.count("\naudit_key\n") + seal.count("\n  audit_key\n") == 2  # a new KEK, and a KEK that was there


def test_init_key_keeps_a_key_that_is_there(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    before = (box["secrets"] / audit.SIGN_PUB_FILE).read_bytes()
    assert audit_heads.main(["--init-key", "--secrets", str(box["secrets"])]) == 0
    assert (box["secrets"] / audit.SIGN_PUB_FILE).read_bytes() == before and "kept" in capsys.readouterr().out


def test_make_audit_verify_takes_the_anchor_folder() -> None:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    body = mk[mk.index("\naudit-verify:") :].split("\n\n", 1)[0]
    assert "--heads" in body and "ANCHOR" in body


def test_the_event_has_its_label_in_three_languages() -> None:
    from console import i18n_audit

    for lang in ("en", "ja", "zh-TW"):
        assert i18n_audit.event_label(lang, audit.SIGNED_EVENT) != audit.SIGNED_EVENT
