"""D-272 (register CR-054, CR-016): the audit chain's head anchor, the archive that never overwrites a changed closed
day, and chart numbers kept out of the chain. Synthetic events only; chart numbers are ``TEST-…``."""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from tb_common.audit import (
    GENESIS,
    HEAD,
    AuditAnchorBroken,
    AuditLog,
    canonical,
    clear_ids,
    line_hash,
    mask_detail,
    mask_ids,
    read_head,
    verify,
)

from tools.trialbox import logs as tl

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)


def _chain(audit: Path, days: int = 3, per_day: int = 3) -> AuditLog:
    log = AuditLog(audit, "UTC")
    for i in range(days):
        for j in range(per_day):
            log.append("test.event", ts=T0 + timedelta(days=i, minutes=j), actor="tester", detail={"n": j})
    return log


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _rehash_all(audit: Path, change: dict[str, object]) -> str:
    """What an attacker with write access does: change every event, recompute every hash (the chain stays valid)."""
    prev = GENESIS
    for f in sorted(audit.glob("*.jsonl")):
        out = []
        for raw in _lines(f):
            rec = json.loads(raw)
            rec.pop("hash")
            rec.update(change)
            rec["prev_hash"] = prev
            rec["hash"] = prev = line_hash(prev, rec)
            out.append(canonical(rec))
        f.write_text("\n".join(out) + "\n", encoding="utf-8")
    return prev


def test_the_anchor_follows_every_write(tmp_path: Path) -> None:
    log = _chain(tmp_path)
    head = read_head(tmp_path)
    res = verify(tmp_path)
    assert res.ok, res.errors
    assert head == {"file": "2026-11-08.jsonl", "hash": res.last_hash, "lines": 9}
    rec = log.append("one.more", ts=T0 + timedelta(days=2, hours=1))
    assert read_head(tmp_path) == {"file": "2026-11-08.jsonl", "hash": rec["hash"], "lines": 10}


def test_dropping_the_last_events_fails(tmp_path: Path) -> None:
    _chain(tmp_path)
    f = tmp_path / "2026-11-08.jsonl"
    f.write_text("\n".join(_lines(f)[:1]) + "\n", encoding="utf-8")
    res = verify(tmp_path)
    assert not res.ok and any("head anchor says event 9" in e for e in res.errors)


def test_deleting_the_newest_day_file_fails(tmp_path: Path) -> None:
    _chain(tmp_path)
    (tmp_path / "2026-11-08.jsonl").unlink()
    assert not verify(tmp_path).ok


@pytest.mark.parametrize("keep_head", [True, False])
def test_deleting_everything_fails(tmp_path: Path, keep_head: bool) -> None:
    _chain(tmp_path)
    for f in tmp_path.glob("*.jsonl"):
        f.unlink()
    if not keep_head:
        (tmp_path / HEAD).unlink()
    res = verify(tmp_path)
    assert not res.ok and res.lines == 0
    assert any(("no head anchor" if not keep_head else "head anchor says") in e for e in res.errors)


def test_rewriting_and_rehashing_everything_fails(tmp_path: Path) -> None:
    _chain(tmp_path)
    kept = dict(read_head(tmp_path) or {})  # the archive's copy of the anchor, kept off the audit volume
    new_head = _rehash_all(tmp_path, {"actor": "someone-else"})
    assert not verify(tmp_path).ok  # the anchor in the folder no longer matches
    # an attacker who also rewrites HEAD.json passes the folder's own check, not the anchor kept elsewhere
    (tmp_path / HEAD).write_text(canonical({"file": None, "hash": new_head, "lines": 9}) + "\n", encoding="utf-8")
    assert verify(tmp_path).ok
    res = verify(tmp_path, anchor=kept)
    assert not res.ok and any("rewritten" in e for e in res.errors)


def test_a_writer_refuses_a_cut_chain_until_a_person_reanchors(tmp_path: Path) -> None:
    log = _chain(tmp_path)
    f = tmp_path / "2026-11-08.jsonl"
    before = _lines(f)
    f.write_text("\n".join(before[:1]) + "\n", encoding="utf-8")
    with pytest.raises(AuditAnchorBroken):
        log.append("after.cut", ts=T0 + timedelta(days=2, hours=1))
    assert _lines(f) == before[:1]  # nothing written over the gap
    rec = log.reanchor("audit_verify:steward", "two events lost in a restore, ticket TEST-1")
    assert rec["event"] == "audit.reanchored" and rec["detail"]["before"]["lines"] == 9
    assert rec["detail"]["chain"]["lines"] == 7
    log.append("after.cut", ts=T0 + timedelta(days=2, hours=1))
    res = verify(tmp_path)
    assert res.ok, res.errors
    assert any("audit.reanchored" in n for n in res.notes)  # the gap stays visible in the chain


def test_a_line_written_before_its_anchor_is_accepted(tmp_path: Path) -> None:
    """A crash between the line and the anchor leaves the chain one event past the anchor, chained to it."""
    log = _chain(tmp_path)
    head = (tmp_path / HEAD).read_bytes()
    log.append("crashed.after.line", ts=T0 + timedelta(days=2, hours=1))
    (tmp_path / HEAD).write_bytes(head)
    res = verify(tmp_path)
    assert res.ok and any("one event past" in n for n in res.notes)
    log.append("next", ts=T0 + timedelta(days=2, hours=2))
    res = verify(tmp_path)
    assert res.ok and res.lines == 11 and read_head(tmp_path)["lines"] == 11  # type: ignore[index]


def test_a_chain_from_before_the_anchor_is_adopted_visibly(tmp_path: Path) -> None:
    log = _chain(tmp_path)
    (tmp_path / HEAD).unlink()
    assert not verify(tmp_path).ok
    log.append("first.after.upgrade", ts=T0 + timedelta(days=2, hours=1))
    res = verify(tmp_path)
    assert res.ok, res.errors
    events = [json.loads(x)["event"] for x in _lines(tmp_path / "2026-11-08.jsonl")]
    assert events[-2:] == ["audit.anchored", "first.after.upgrade"]
    assert res.lines == 11 and any("audit.anchored" in n for n in res.notes)


def test_a_torn_line_and_the_anchor(tmp_path: Path) -> None:
    log = _chain(tmp_path)
    with (tmp_path / "2026-11-08.jsonl").open("ab") as fh:
        fh.write(b'{"event":"half')
    log.append("after.tear", ts=T0 + timedelta(days=2, hours=1))
    res = verify(tmp_path)
    assert res.ok, res.errors
    assert res.lines == 11 and read_head(tmp_path)["lines"] == 11  # type: ignore[index]


# ------------------------------------------------------------------------------------------------ archive
def test_the_archive_refuses_to_overwrite_a_changed_closed_day(tmp_path: Path) -> None:
    audit, archive = tmp_path / "audit", tmp_path / "archive"
    _chain(audit)
    assert tl.archive_audit(audit, archive, date(2026, 11, 8)) == ["2026-11-06.jsonl", "2026-11-07.jsonl"]
    assert json.loads((archive / "HEAD.json").read_text())["lines"] == 6
    packed = (archive / "2026/2026-11-06.jsonl.gz").read_bytes()
    _rehash_all(audit, {"actor": "someone-else"})
    (audit / HEAD).write_text(canonical({"file": None, "hash": verify(audit).last_hash, "lines": 9}) + "\n")
    assert verify(audit).ok  # the folder alone cannot tell; the archive's anchor can
    with pytest.raises(RuntimeError, match="rewritten"):
        tl.archive_audit(audit, archive, date(2026, 11, 9))
    assert (archive / "2026/2026-11-06.jsonl.gz").read_bytes() == packed  # never overwritten


def test_the_archive_refuses_a_changed_day_even_without_its_anchor(tmp_path: Path) -> None:
    audit, archive = tmp_path / "audit", tmp_path / "archive"
    _chain(audit)
    tl.archive_audit(audit, archive, date(2026, 11, 8))
    packed = (archive / "2026/2026-11-06.jsonl.gz").read_bytes()
    _rehash_all(audit, {"actor": "someone-else"})
    (audit / HEAD).write_text(canonical({"file": None, "hash": verify(audit).last_hash, "lines": 9}) + "\n")
    (archive / "HEAD.json").unlink()
    with pytest.raises(RuntimeError, match="changed since it was archived"):
        tl.archive_audit(audit, archive, date(2026, 11, 9))
    assert (archive / "2026/2026-11-06.jsonl.gz").read_bytes() == packed


def test_the_archive_takes_a_day_that_only_grew(tmp_path: Path) -> None:
    """The newest file can still take a late event after it was archived (stamped before midnight): that is growth,
    the archived copy is its start, and it is copied again."""
    audit, archive = tmp_path / "audit", tmp_path / "archive"
    log = _chain(audit, days=2)
    assert tl.archive_audit(audit, archive, date(2026, 11, 8)) == ["2026-11-06.jsonl", "2026-11-07.jsonl"]
    log.append("late.event", ts=T0 + timedelta(days=1, hours=11))  # 2026-11-07T23:00Z, still the newest file
    assert tl.archive_audit(audit, archive, date(2026, 11, 8)) == ["2026-11-07.jsonl"]
    assert gzip.decompress((archive / "2026/2026-11-07.jsonl.gz").read_bytes()).count(b"\n") == 4


def test_the_archive_refuses_a_missing_day_and_an_emptied_folder(tmp_path: Path) -> None:
    audit, archive = tmp_path / "audit", tmp_path / "archive"
    _chain(audit)
    tl.archive_audit(audit, archive, date(2026, 11, 9))
    shutil.rmtree(audit)
    log = AuditLog(audit, "UTC")
    log.append("fresh.start", ts=T0 + timedelta(days=3))  # a new chain where the old one was
    with pytest.raises(RuntimeError, match="does not verify|missing"):
        tl.archive_audit(audit, archive, date(2026, 11, 10))


# ------------------------------------------------------------------------------------------------ chart numbers
def test_mask_rules() -> None:
    assert mask_ids("CASE GZQO mrn=TEST-0000001 lang=en") == "CASE GZQO mrn=••• lang=en"
    assert mask_ids("Re: CASE GZQO MRN=TEST-0000001") == "Re: CASE GZQO MRN=•••"
    assert mask_ids("filename=x.pdf") == "filename=x.pdf"
    opts = {"mrn": "TEST-0000001", "lang": "en", "dob": "1900-01-01", "version": "1.0.0"}
    assert mask_detail({"options": opts, "error": {"message": "mrn='TEST-1' does not look like a chart number"}}) == {
        "options": {"mrn": "•••", "lang": "en", "dob": "•••", "version": "1.0.0"},
        "error": {"message": "mrn=••• does not look like a chart number"},
    }
    assert clear_ids({"detail": {"options": opts, "line": "CASE X mrn=•••"}}) == [
        "detail.options.mrn",
        "detail.options.dob",
    ]
    assert clear_ids({"detail": {"subject": "CASE X mrn=TEST-0000001", "s": "{'mrn': '•••'}"}}) == [
        "detail.subject:mrn"
    ]


def test_find_ids_lists_old_rows_without_their_values(tmp_path: Path) -> None:
    log = AuditLog(tmp_path, "UTC")
    log.append("job.state", ts=T0, job_id="J1", detail={"options": {"mrn": "TEST-0000001"}})  # before D-272
    log.append("mail.received", ts=T0, job_id="J1", detail={"subject": "CASE GZQO mrn=TEST-0000001"})
    log.append("job.state", ts=T0, job_id="J2", detail={"options": mask_detail({"mrn": "TEST-0000002"})})
    log.append("screen.reveal", ts=T0, job_id="J2", detail={"pid": "ab" * 16})
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_verify.py"), str(tmp_path), "--find-ids", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 1, out.stderr
    assert "TEST-000000" not in out.stdout  # the report never repeats a chart number
    rep = json.loads(out.stdout)
    assert [(r["line"], r["event"], r["fields"]) for r in rep["rows"]] == [
        (1, "job.state", ["detail.options.mrn"]),
        (2, "mail.received", ["detail.subject:mrn"]),
    ]
    assert rep["pseudonym_rows_by_event"] == {"screen.reveal": 1}
    # the chain itself is untouched by the report (OD-7: no rewrite before the owner rules)
    assert verify(tmp_path).ok


def test_the_cli_checks_an_anchor_kept_elsewhere_and_reanchors(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _chain(audit)
    kept = tmp_path / "kept-HEAD.json"
    shutil.copy(audit / HEAD, kept)
    cli = [sys.executable, str(ROOT / "tools" / "audit_verify.py"), str(audit)]
    assert subprocess.run([*cli, "--anchor", str(kept)], capture_output=True, check=False).returncode == 0
    _rehash_all(audit, {"actor": "someone-else"})
    (audit / HEAD).write_text(canonical({"file": None, "hash": verify(audit).last_hash, "lines": 9}) + "\n")
    out = subprocess.run([*cli, "--anchor", str(kept), "--json"], capture_output=True, text=True, check=False)
    assert out.returncode == 1 and any("rewritten" in e for e in json.loads(out.stdout)["errors"])
    assert subprocess.run([*cli, "--reanchor", "x"], capture_output=True, check=False).returncode == 2  # no actor
    copy = tmp_path / "copy"
    copy.mkdir()
    shutil.copy(audit / "2026-11-06.jsonl", copy)
    assert subprocess.run([*cli[:-1], str(copy)], capture_output=True, check=False).returncode == 1
    assert subprocess.run([*cli[:-1], str(copy), "--no-head"], capture_output=True, check=False).returncode == 0


def test_one_event_past_the_anchor_must_chain_to_the_anchored_event(tmp_path: Path) -> None:
    """The crash allowance above is for a line chained to the anchored event. Replacing the anchored (last) event and
    appending one more, every hash recomputed, leaves the chain one event longer than HEAD.json too: a rewrite, which
    must fail, not a note."""
    _chain(tmp_path)  # nine events, HEAD.json at event 9
    f = tmp_path / "2026-11-08.jsonl"
    lines = _lines(f)
    last = json.loads(lines[-1])
    last.pop("hash")
    last["actor"] = "someone-else"
    last["hash"] = line_hash(last["prev_hash"], last)
    extra = {k: v for k, v in last.items() if k != "hash"}
    extra.update(prev_hash=last["hash"], event="test.extra")
    extra["hash"] = line_hash(extra["prev_hash"], extra)
    f.write_text("\n".join([*lines[:-1], canonical(last), canonical(extra)]) + "\n", encoding="utf-8")
    res = verify(tmp_path)
    assert res.lines == 10
    assert not res.ok and any("head anchor says event 9" in e for e in res.errors), (res.errors, res.notes)
