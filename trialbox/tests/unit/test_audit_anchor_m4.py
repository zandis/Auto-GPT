"""M4: the anchor's four states (ok, missing, stale, tampered) and the restored trail, the copy read back, losing the
anchor warning (never blocking), candidate places for the anchor, and a head killed while it is written. Synthetic."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit
from tb_common.audit import AuditLog, read_signed_heads

from tools import audit_verify
from tools.trialbox import anchors, audit_heads, doctor

pytestmark = pytest.mark.nodb
T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)
NIGHT = datetime(2026, 11, 7, 0, 25, tzinfo=UTC)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV):
        monkeypatch.delenv(var, raising=False)
    paths = {n: tmp_path / n for n in ("audit", "share", "secrets", "run", "deploy", "audit2", "audit3")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert audit_verify.init_key(paths["secrets"]) == 0
    return paths


def _events(log: AuditLog, n: int) -> None:
    for i in range(n):
        log.append("test.event", ts=T0 + timedelta(minutes=i), actor="tester", detail={"n": i})


def _night(box: dict[str, Path], now: datetime = NIGHT) -> Any:
    return audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=lambda *a: None, now=now)


def _state(box: dict[str, Path], now: datetime, which: str = "audit") -> tuple[str, str]:
    return audit.anchor_state(box["share"], box[which], audit_heads.own_keys(box["secrets"]), now)


def _doctor(box: dict[str, Path], env: str, now: datetime, which: str = "audit") -> doctor.Check:
    e = {
        "TB_ENV": env,
        "TB_SECRETS_HOST_DIR": str(box["secrets"]),
        "TB_AUDIT_HOST_DIR": str(box[which]),
        "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]),
    }
    return doctor.check_audit_heads(doctor.DoctorInputs(env=e, deploy=box["deploy"]), now=now)


def test_the_four_states_each_give_their_own_result_and_sentence(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 4)
    assert _state(box, NIGHT)[0] == "missing"  # no head yet
    assert _night(box).ok
    assert _state(box, NIGHT + timedelta(hours=2))[0] == "ok"
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=2))
    assert (c.status, c.name) == ("PASS", "audit_heads")
    state, text = _state(box, NIGHT + timedelta(hours=40))
    assert state == "stale" and "40 h old" in text
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=40))
    assert c.status == "WARN" and "40 h old" in c.detail
    # tampered: an event removed and the rest re-hashed, as one who can write the audit volume would
    log_file = next(box["audit"].glob("*.jsonl"))
    lines = log_file.read_text(encoding="utf-8").splitlines()
    prev, out = audit.GENESIS, []
    for i, raw in enumerate(lines):
        if i == 1:
            continue
        rec = json.loads(raw)
        rec.pop("hash", None)
        rec["prev_hash"] = prev
        rec["hash"] = prev = audit.line_hash(prev, rec)
        out.append(audit.canonical(rec))
    log_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    state, text = _state(box, NIGHT + timedelta(hours=2))
    assert state == "tampered" and "2026-11-07" in text and "nothing was deleted" in text
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=2))
    assert c.status == "FAIL" and "2026-11-07" in c.detail


def test_a_tampered_anchor_copy_is_named_not_trusted(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 3)
    assert _night(box).ok
    head = next((box["share"] / "heads").glob("*.json"))
    rec = json.loads(head.read_text(encoding="utf-8"))
    rec["hash"] = "0" * 64  # the anchor's copy is changed; its signature no longer holds
    head.write_text(audit.canonical(rec) + "\n", encoding="utf-8")
    state, text = _state(box, NIGHT)
    assert state == "tampered" and "not valid" in text
    rec["key_id"] = "someone-elses-key"
    head.write_text(audit.canonical(rec) + "\n", encoding="utf-8")
    state, text = _state(box, NIGHT)
    assert state == "tampered" and "someone-elses-key" in text and "not signed by this box" in text


@pytest.mark.parametrize("env", ["PRODUCTION", "DEV"])
def test_an_anchor_that_is_gone_warns_the_box_goes_on_and_production_names_the_gate(
    box: dict[str, Path], env: str
) -> None:
    _events(AuditLog(box["audit"]), 2)
    assert _night(box).ok
    gone = box["share"].rename(box["share"].with_name("share-gone"))
    c = _doctor(box, env, NIGHT + timedelta(hours=1))
    assert c.status == "WARN" and "not reachable" in c.detail
    assert (audit_heads.GATE in c.detail) == (env == "PRODUCTION")
    _events(AuditLog(box["audit"]), 1)  # the box still writes its audit trail
    night = _night(box)
    assert not night.ok and "not there" in " ".join(night.problems)  # the night says so; nothing else is stopped
    gone.rename(box["share"])
    assert _night(box, NIGHT + timedelta(days=1)).ok  # and the head is copied when the anchor returns


def test_a_copy_that_is_changed_in_transit_is_caught_removed_and_written_again(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _events(AuditLog(box["audit"]), 2)
    real = os.replace

    def bad(src: Any, dst: Any) -> None:
        real(src, dst)
        if "heads" in str(dst):
            Path(dst).write_bytes(b"{garbled")

    events: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(os, "replace", bad)
    night = audit_heads.sign_night(
        box["audit"], box["secrets"], [box["share"]], record=lambda *a: events.append(a), now=NIGHT
    )
    assert not night.ok and "read back" in " ".join(night.problems)
    assert list((box["share"] / "heads").glob("*.json")) == []  # the bad copy is not left as a head
    assert [e[0] for e in events] == [audit.SIGNED_EVENT] and events[0][2]["failed"]  # one audit line says so
    monkeypatch.setattr(os, "replace", real)
    assert _night(box, NIGHT + timedelta(days=1)).ok  # retried the next cycle
    assert _state(box, NIGHT + timedelta(days=1, hours=1))[0] == "ok"


def test_a_head_killed_while_it_is_written_leaves_the_next_start_a_valid_head(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _events(AuditLog(box["audit"]), 2)
    real = os.replace

    def killed(src: Any, dst: Any) -> None:
        if "heads" in str(dst):
            raise SystemExit(143)
        real(src, dst)

    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(SystemExit):
        _night(box)
    monkeypatch.setattr(os, "replace", real)
    assert read_signed_heads(box["share"]) == []  # no half head under a real name (the temp leftover is ignored)
    assert _night(box, NIGHT + timedelta(hours=1)).ok
    heads = read_signed_heads(box["share"])
    pub = audit_heads.own_keys(box["secrets"])[heads[0]["key_id"]]
    assert len(heads) == 1 and audit.signed_head_problem(heads[0], pub) is None


def test_a_restored_older_trail_is_named_restored_not_tampered(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"]), 4)
    assert _night(box).ok  # the anchor holds a head at event 4
    older = AuditLog(box["audit2"])  # the backup holds the first two events; the restore audits itself
    _events(older, 2)
    older.append("backup.restored", ts=T0 + timedelta(days=1), actor="trialbox:restore", detail={})
    state, text = _state(box, NIGHT + timedelta(hours=2), "audit2")
    assert state == "restored" and "restored to" in text and "tampered" not in text
    assert _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=2), "audit2").status == "WARN"
    # a trail that was cut and rewritten WITHOUT a restore event is still tampered
    rewritten = AuditLog(box["audit3"])
    _events(rewritten, 2)
    rewritten.append("test.event", ts=T0 + timedelta(days=1), actor="x", detail={})
    assert _state(box, NIGHT + timedelta(hours=2), "audit3")[0] == "tampered"


def test_candidate_places_lists_a_second_disk_or_share_and_never_the_audit_disk() -> None:
    mounts = (
        "/dev/sda2 / ext4 rw 0 0\n/dev/sdb1 /mnt/backup ext4 rw 0 0\n/dev/sda3 /var/lib/docker ext4 rw 0 0\n"
        "//nas/trial /srv/share cifs rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sda3 /mnt/same ext4 rw 0 0\n"
    )
    places, item = anchors.candidate_places(mounts, "/var/lib/docker/volumes/x/_data")
    assert places == ["/mnt/backup", "/srv/share"] and item is None  # /mnt/same is the audit disk
    none, item = anchors.candidate_places("/dev/sda2 / ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0\n", "/var/lib/audit")
    assert none == [] and "this machine for now" in str(item) and "open item" in str(item)
