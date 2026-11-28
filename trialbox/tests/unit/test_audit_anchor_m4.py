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


def _recorder(log: AuditLog) -> audit_heads.Recorder:
    def record(event: str, actor: str, detail: dict[str, Any]) -> None:
        log.append(event, actor=actor, detail=detail)

    return record


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


# ------------------------------------------------------------------------------------------------ OCR 1523
def _two_nights(box: dict[str, Path], second: Path, missed: str) -> None:
    """Three nights into two folders; the second folder is away on the middle one. ``missed``: ``written`` (the signer
    tries it and fails) or ``absent`` (the host leaves a folder that is not there out, ``sign_on_box``)."""
    log = AuditLog(box["audit"])
    two = [box["share"], second]

    def rec(event: str, actor: str, detail: dict[str, Any]) -> None:
        if missed == "absent" and detail["anchors"] == 1:  # what sign_on_box adds for a folder that is not there
            detail["failed"] = [
                f"the anchor folder {second} is not there (not mounted?): no signed head was written to it"
            ]
        log.append(event, actor=actor, detail=detail)

    def sign(folders: list[Path], day: int) -> Any:
        return audit_heads.sign_night(
            box["audit"], box["secrets"], folders, record=rec, now=NIGHT + timedelta(days=day)
        )

    _events(log, 3)
    assert sign(two, 0).ok
    log.append("test.event", ts=NIGHT + timedelta(hours=1), actor="tester", detail={"n": 9})
    off = second.rename(second.with_name("second-off"))
    if missed == "written":
        second.write_text("not mounted")  # the head cannot be written there tonight
        assert not sign(two, 1).ok
        second.unlink()
    else:
        sign([two[0]], 1)
    off.rename(second)
    log.append("test.event", ts=NIGHT + timedelta(days=1, hours=1), actor="tester", detail={"n": 10})
    assert sign(two, 2).ok


@pytest.mark.parametrize("missed", ["written", "absent"])
def test_a_second_folder_that_missed_one_night_is_not_called_tampered(
    box: dict[str, Path], tmp_path: Path, missed: str
) -> None:
    """OCR 1523-4: the chain names the folder that did not take a head: it is not looked for there."""
    second = tmp_path / "second"
    second.mkdir()
    _two_nights(box, second, missed)
    own, later = audit_heads.own_keys(box["secrets"]), NIGHT + timedelta(days=2, hours=1)
    for folder in (box["share"], second):
        assert audit.anchor_state(folder, box["audit"], own, later)[0] == "ok"
    # the folder that took that night's head is still held to it
    sorted((box["share"] / "heads").iterdir())[1].unlink()
    assert audit.anchor_state(box["share"], box["audit"], own, later)[0] == "tampered"


def test_a_folder_added_later_is_not_held_to_the_heads_before_it(box: dict[str, Path], tmp_path: Path) -> None:
    """OCR 1523-4, the same list: a second folder set up after the first nights holds no head from before."""
    log = AuditLog(box["audit"])
    record = _recorder(log)
    _events(log, 3)
    assert audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=record, now=NIGHT).ok
    log.append("test.event", ts=NIGHT + timedelta(hours=1), actor="tester", detail={"n": 9})
    second = tmp_path / "second"
    second.mkdir()
    both = [box["share"], second]
    day = NIGHT + timedelta(days=1)
    assert audit_heads.sign_night(box["audit"], box["secrets"], both, record=record, now=day).ok
    own = audit_heads.own_keys(box["secrets"])
    for folder in both:
        assert audit.anchor_state(folder, box["audit"], own, day + timedelta(hours=1))[0] == "ok"


def test_an_anchor_folder_emptied_after_a_signed_night_is_tampered_a_fail_and_never_signed_over(
    box: dict[str, Path],
) -> None:
    """OCR 1523-17: the chain records a head written to the folder and the folder holds none: deleted, never only
    "missing". The nightly signer refuses (V8-05, V8-06) until a person signs by hand."""
    log = AuditLog(box["audit"])
    _events(log, 3)
    record = _recorder(log)
    assert audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=record, now=NIGHT).ok
    for f in (box["share"] / "heads").iterdir():
        f.unlink()
    state, text = _state(box, NIGHT + timedelta(hours=1))
    assert state == "tampered" and "emptied" in text
    for env in ("PRODUCTION", "VALIDATION", "DEV"):
        assert _doctor(box, env, NIGHT + timedelta(hours=1)).status == "FAIL"
    log.append("test.event", ts=NIGHT + timedelta(hours=1), actor="tester", detail={"n": 9})
    night = audit_heads.sign_night(
        box["audit"], box["secrets"], [box["share"]], record=record, now=NIGHT + timedelta(days=1)
    )
    assert not night.ok and "emptied" in " ".join(night.problems) and not list((box["share"] / "heads").iterdir())


def test_a_night_no_folder_took_does_not_hide_a_deleted_newest_head(box: dict[str, Path]) -> None:
    log = AuditLog(box["audit"])
    _events(log, 3)
    record = _recorder(log)
    for d in (0, 1):
        log.append("test.event", ts=NIGHT + timedelta(days=d), actor="tester", detail={"n": d})
        now = NIGHT + timedelta(days=d, hours=1)
        assert audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=record, now=now).ok
    log.append(audit.SIGNED_EVENT, actor="t", detail={"lines": 99, "head": "f" * 64, "anchors": 0, "failed": ["x"]})
    sorted((box["share"] / "heads").iterdir())[-1].unlink()
    night = audit_heads.sign_night(
        box["audit"], box["secrets"], [box["share"]], record=record, now=NIGHT + timedelta(days=2)
    )
    assert not night.ok and "deleted" in " ".join(night.problems)


def test_a_torn_last_line_is_not_tampered(box: dict[str, Path]) -> None:
    """V8-01: a write cut short is neither tampering nor signed over."""
    _events(AuditLog(box["audit"]), 4)
    assert _night(box).ok
    AuditLog(box["audit"]).append("test.event", ts=NIGHT, actor="t", detail={})
    log_file = sorted(box["audit"].glob("*.jsonl"))[-1]
    log_file.write_bytes(log_file.read_bytes()[:-20])
    assert _state(box, NIGHT + timedelta(hours=1))[0] == "ok"
    night = _night(box, NIGHT + timedelta(hours=1))
    assert not night.ok and "not tampering" in " ".join(night.problems)


def test_a_link_planted_at_the_temporary_name_is_not_followed(box: dict[str, Path], tmp_path: Path) -> None:
    """OCR 1523-8: the share is a folder other machines write; the signer is root."""
    other = tmp_path / "other"
    other.write_text("kept")
    heads = box["share"] / "heads"
    heads.mkdir()
    (heads / ".a.json.tmp").symlink_to(other)
    assert audit._write_once(heads / "a.json", b"new") is True
    assert other.read_text() == "kept" and (heads / "a.json").read_bytes() == b"new"
    assert [p.name for p in heads.iterdir()] == ["a.json"]


def test_a_host_without_the_crypto_library_reads_what_it_can(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 1523-14: the dates and the chain as before M4; the signatures are said not checked, never a FAIL for it."""
    _events(AuditLog(box["audit"]), 3)
    assert _night(box).ok

    def gone(*_a: Any) -> Any:
        raise ModuleNotFoundError("No module named 'cryptography'", name="cryptography")

    monkeypatch.setattr(audit_heads, "own_keys", gone)
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=1))
    assert c.status == "PASS" and "signatures not checked" in c.detail
    assert _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=40)).status == "WARN"  # stale all the same


def test_a_folder_the_doctor_may_not_read_is_a_warn_that_says_so(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _events(AuditLog(box["audit"]), 3)
    assert _night(box).ok

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise PermissionError(13, "Permission denied", str(box["audit"]))

    monkeypatch.setattr(audit, "anchor_state", refuse)
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=1))
    assert c.status == "WARN" and "cannot look" in c.detail


def test_an_audit_folder_not_seen_here_is_a_warn_not_a_tampered_trail(box: dict[str, Path]) -> None:
    """REAL2 M-5: the host check's doctor (the box image) had the anchor folder but not the audit volume; it read
    "the trail has 0 events" against the head at event 308 and called a healthy trail tampered (FAIL)."""
    _events(AuditLog(box["audit"]), 3)
    assert _night(box).ok
    box["gone"] = box["audit"].parent / "audit-volume-not-mounted-here"
    c = _doctor(box, "PRODUCTION", NIGHT + timedelta(hours=1), which="gone")
    assert c.status == "WARN" and str(box["gone"]) in c.detail and "not compared" in c.detail, c
    assert "removed or rewritten" not in c.detail


def _sign_at(box: dict[str, Path], targets: list[Path], log: AuditLog, now: datetime) -> Any:
    log.append("test.event", ts=now - timedelta(minutes=5), actor="tester", detail={"n": 1})
    return audit_heads.sign_night(box["audit"], box["secrets"], targets, record=_recorder(log), now=now)


def test_a_folder_just_added_is_no_head_yet_not_tampered(box: dict[str, Path], tmp_path: Path) -> None:
    """OCR 1523-21: the chain's heads were written to the folders of their night, not to one set up since."""
    log = AuditLog(box["audit"])
    _events(log, 3)
    assert _sign_at(box, [box["share"]], log, NIGHT).ok
    new = tmp_path / "new"
    new.mkdir()
    state = audit.anchor_state(new, box["audit"], audit_heads.own_keys(box["secrets"]), NIGHT + timedelta(hours=1))
    assert state[0] == "missing" and "no signed head" in state[1]


def test_one_of_two_folders_emptied_is_never_signed_over(box: dict[str, Path], tmp_path: Path) -> None:
    """OCR 1523-17: the other folder's heads do not let the night sign over the emptied one."""
    log = AuditLog(box["audit"])
    _events(log, 3)
    both = [box["share"], tmp_path / "b"]
    both[1].mkdir()
    assert _sign_at(box, both, log, NIGHT).ok
    for f in (both[1] / "heads").iterdir():
        f.unlink()
    night = _sign_at(box, both, log, NIGHT + timedelta(days=1))
    own = audit_heads.own_keys(box["secrets"])
    assert not night.ok and not list((both[1] / "heads").iterdir())
    assert audit.anchor_state(both[1], box["audit"], own, NIGHT + timedelta(days=1, hours=1))[0] == "tampered"
    assert audit.anchor_state(both[0], box["audit"], own, NIGHT + timedelta(days=1, hours=1))[0] == "ok"


def test_a_share_not_mounted_one_night_is_not_tampered_once_mounted_again(box: dict[str, Path], tmp_path: Path) -> None:
    """OCR 1523-4: a share that is not mounted leaves its mount point, an empty folder: the night writes nothing there."""
    log = AuditLog(box["audit"])
    _events(log, 3)
    point = tmp_path / "mnt-b"
    point.mkdir()
    both = [box["share"], point]
    assert _sign_at(box, both, log, NIGHT).ok
    server = point.rename(tmp_path / "server")
    point.mkdir()
    assert not _sign_at(box, both, log, NIGHT + timedelta(days=1)).ok
    point.rmdir()
    server.rename(point)
    own = audit_heads.own_keys(box["secrets"])
    assert audit.anchor_state(point, box["audit"], own, NIGHT + timedelta(days=1, hours=1))[0] == "ok"


def test_a_folder_added_after_the_upgrade_is_not_held_to_events_that_name_no_folder(
    box: dict[str, Path], tmp_path: Path
) -> None:
    """1523 review M2: a head event written before the events named their folders does not hold a folder set up since:
    it is no head yet, and the next night writes its first."""
    log = AuditLog(box["audit"])
    _events(log, 3)

    def before(event: str, actor: str, detail: dict[str, Any]) -> None:  # the event as it was before OCR 1523-21
        log.append(event, actor=actor, detail={k: v for k, v in detail.items() if k != "to"})

    log.append("test.event", ts=NIGHT - timedelta(minutes=5), actor="tester", detail={"n": 1})
    assert audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=before, now=NIGHT).ok
    new = tmp_path / "new"
    new.mkdir()
    own = audit_heads.own_keys(box["secrets"])
    assert audit.anchor_state(new, box["audit"], own, NIGHT + timedelta(hours=1), holding=1)[0] == "missing"
    assert _sign_at(box, [box["share"], new], log, NIGHT + timedelta(days=1)).ok
    assert list((new / "heads").iterdir())
    assert audit.anchor_state(new, box["audit"], own, NIGHT + timedelta(days=1, hours=1))[0] == "ok"


@pytest.mark.parametrize("how", ["emptied", "mount_point"])
def test_a_folder_from_before_the_upgrade_emptied_is_tampered_not_new(
    box: dict[str, Path], tmp_path: Path, how: str
) -> None:
    """1523 review M2, round 2: two folders took the heads before the events named them; one is emptied (or its share
    is not mounted: an empty mount point). The other's heads do not make it a folder added since: tampered, never
    signed over."""
    log = AuditLog(box["audit"])
    _events(log, 3)

    def before(event: str, actor: str, detail: dict[str, Any]) -> None:  # the event as it was before OCR 1523-21
        log.append(event, actor=actor, detail={k: v for k, v in detail.items() if k != "to"})

    both = [box["share"], tmp_path / "b"]
    both[1].mkdir()
    log.append("test.event", ts=NIGHT - timedelta(minutes=5), actor="tester", detail={"n": 1})
    assert audit_heads.sign_night(box["audit"], box["secrets"], both, record=before, now=NIGHT).ok
    if how == "emptied":
        for f in (both[1] / "heads").iterdir():
            f.unlink()
    else:
        both[1].rename(tmp_path / "server")
        both[1].mkdir()
    own = audit_heads.own_keys(box["secrets"])
    assert audit.anchor_state(both[1], box["audit"], own, NIGHT + timedelta(hours=1), holding=1)[0] == "tampered"
    assert not _sign_at(box, both, log, NIGHT + timedelta(days=1)).ok
    assert not (both[1] / "heads").is_dir() or not list((both[1] / "heads").iterdir())
