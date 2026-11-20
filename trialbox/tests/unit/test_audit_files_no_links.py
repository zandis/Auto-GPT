"""H-68 (D-1351): the audit writer opens its folder once and every file in it through that folder, never through a
symbolic link, a hard link, a FIFO, a folder or a file of another owner put in a file's place.

The hole (lane K, 2026-11-20): ``write_head``, the day file and ``.lock`` were opened by path and followed links, so
an account that can write the audit folder (the audit writer's uid 10001 owns the volume) could plant
``.HEAD.json.tmp`` or a day file as a link, and the next command run as root (``trialbox restore``, a key ceremony,
``audit_verify.py --reanchor``) truncated or appended to the file it points at. These tests plant each such name and
check that nothing outside the folder changes (the "victim" is a file beside the folder), as any user: nothing here
needs root, and ownership is checked with a stand-in for the owners the folder allows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from tb_common import audit
from tb_common.audit import AuditAnchorBroken, AuditLog, verify, write_head

UTC = ZoneInfo("UTC")
T = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
DAY = "2026-11-20.jsonl"
VICTIM = b"root:x:0:0 a file of root's, outside the audit folder\n"


@pytest.fixture
def box(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / "audit"
    folder.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(VICTIM)
    victim.chmod(0o600)
    return folder, victim


def _two_events(folder: Path) -> AuditLog:
    log = AuditLog(folder, "UTC")
    log.append("job.created", ts=T, job_id="J1")
    log.append("job.done", ts=T, job_id="J1")
    return log


def _unchanged(victim: Path) -> None:
    assert victim.read_bytes() == VICTIM, "the file outside the audit folder was written through the planted name"


# ------------------------------------------------------------------------------------------------ symbolic links
@pytest.mark.parametrize("name", [DAY, ".HEAD.json.tmp", ".lock", "HEAD.json"])
def test_a_link_planted_in_a_files_place_is_refused_and_its_target_is_not_written(
    box: tuple[Path, Path], name: str
) -> None:
    folder, victim = box
    (folder / name).symlink_to(victim)
    with pytest.raises(AuditAnchorBroken, match="symbolic link"):
        AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
    _unchanged(victim)
    assert (folder / name).is_symlink()  # left as found, for a person to look at


@pytest.mark.parametrize("name", [DAY, ".HEAD.json.tmp"])
def test_a_link_planted_before_a_later_write_is_refused_too(box: tuple[Path, Path], name: str) -> None:
    folder, victim = box
    log = _two_events(folder)
    if name == DAY:
        (folder / DAY).unlink()
        write_head(folder, 0, audit.GENESIS, None)  # a chain whose day file the link replaced
    (folder / name).symlink_to(victim)
    with pytest.raises(AuditAnchorBroken, match="symbolic link"):
        log.append("job.again", ts=T, job_id="J1")
    _unchanged(victim)


@pytest.mark.parametrize("name", [".lock", ".HEAD.json.tmp", DAY])
def test_a_dangling_link_makes_no_file_outside_the_folder(box: tuple[Path, Path], name: str) -> None:
    folder, victim = box
    absent = victim.with_name("made-by-root")
    (folder / name).symlink_to(absent)
    with pytest.raises(AuditAnchorBroken, match="symbolic link"):
        AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
    assert not absent.exists()


def test_a_link_in_the_torn_evidence_name_is_not_followed(box: tuple[Path, Path]) -> None:
    folder, victim = box
    log = _two_events(folder)
    absent = victim.with_name("made-by-root")
    (folder / f"{DAY}.torn-1").symlink_to(absent)
    with (folder / DAY).open("ab") as fh:
        fh.write(b'{"event":"half')  # a torn line: the next write moves it to the first free .torn-<n>
    log.append("job.after", ts=T, job_id="J1")
    assert not absent.exists()
    assert (folder / f"{DAY}.torn-1").is_symlink()
    assert (folder / f"{DAY}.torn-2").read_bytes() == b'{"event":"half'
    assert verify(folder).ok


def test_the_folder_itself_a_link_is_refused(box: tuple[Path, Path]) -> None:
    folder, _victim = box
    elsewhere = folder.with_name("elsewhere")
    elsewhere.mkdir()
    link = folder.with_name("audit-link")
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(AuditAnchorBroken, match="symbolic link"):
        AuditLog(link, "UTC").append("job.created", ts=T, job_id="J1")
    assert list(elsewhere.iterdir()) == []


# ------------------------------------------------------------------------------------------------ other things in a file's place
def test_a_hard_link_to_a_file_outside_is_refused(box: tuple[Path, Path]) -> None:
    folder, victim = box
    os.link(victim, folder / DAY)  # where protected_hardlinks is off, or the planter owns the target
    with pytest.raises(AuditAnchorBroken, match="hard link"):
        AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
    _unchanged(victim)


@pytest.mark.parametrize("name", [DAY, ".lock", "HEAD.json"])
def test_a_fifo_in_a_files_place_is_refused_without_hanging(box: tuple[Path, Path], name: str) -> None:
    folder, _victim = box
    os.mkfifo(folder / name)
    out: list[BaseException | None] = []

    def run() -> None:
        try:
            AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
            out.append(None)
        except BaseException as exc:  # handed to the test thread
            out.append(exc)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(20)
    assert out, "the writer hung on a FIFO planted in the audit folder"
    assert isinstance(out[0], AuditAnchorBroken) and "not a plain file" in str(out[0])


@pytest.mark.parametrize("name", [DAY, ".lock", ".HEAD.json.tmp"])
def test_a_folder_in_a_files_place_is_refused(box: tuple[Path, Path], name: str) -> None:
    folder, _victim = box
    (folder / name).mkdir()
    with pytest.raises(AuditAnchorBroken, match="not a plain file|symbolic link"):
        AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")


def test_a_file_of_another_owner_is_refused(box: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    folder, _victim = box
    log = _two_events(folder)
    before = (folder / DAY).read_bytes()
    # the stand-in: the owners the folder allows no longer include this file's owner, as a file planted by another
    # account would be (a test as root could chown it; CI runs as a user who cannot)
    mine = (folder / DAY).stat().st_uid
    monkeypatch.setattr(audit, "_owners_allowed", lambda folder_stat: {mine + 4242})
    with pytest.raises(AuditAnchorBroken, match="owned by uid"):
        log.append("job.again", ts=T, job_id="J1")
    assert (folder / DAY).read_bytes() == before


def test_a_world_writable_folder_is_refused(box: tuple[Path, Path]) -> None:
    folder, _victim = box
    folder.chmod(0o777)  # anyone could plant a name there
    try:
        with pytest.raises(AuditAnchorBroken, match="writable by every account"):
            AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
    finally:
        folder.chmod(0o755)
    assert list(folder.iterdir()) == []


def test_a_refusal_names_the_file_not_the_target_and_is_logged(
    box: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    folder, victim = box
    (folder / ".HEAD.json.tmp").symlink_to(victim)
    with caplog.at_level(logging.ERROR, logger="tb_common.audit"), pytest.raises(AuditAnchorBroken) as exc:
        AuditLog(folder, "UTC").append("job.created", ts=T, job_id="J1")
    msg = str(exc.value)
    assert ".HEAD.json.tmp" in msg and str(victim) not in msg and "victim" not in msg
    assert any(".HEAD.json.tmp" in r.getMessage() and "victim" not in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------------------------------------ the format does not move
def _events(folder: Path) -> dict[str, str]:
    """A fixed run through every writing path: a chain from before the anchor (adopted), events on two days, a torn
    line repaired, a reanchor; the sha256 of every file it leaves."""
    folder.mkdir()
    pre = {"ts": "2026-11-19T08:00:00.000+00:00", "event": "job.created", "job_id": "J0", "prev_hash": audit.GENESIS}
    pre["hash"] = audit.line_hash(audit.GENESIS, pre)
    (folder / "2026-11-19.jsonl").write_text(audit.canonical(pre) + "\n", encoding="utf-8")
    log = AuditLog(folder, "UTC")
    log.append("job.done", ts=datetime(2026, 11, 19, 9, 0, tzinfo=UTC), job_id="J0", actor="pi1", extra="x")
    log.append("job.created", ts=T, job_id="J1", detail={"mrn": "•••", "n": 3})
    with (folder / DAY).open("ab") as fh:
        fh.write(b'{"event":"to')
    log.append("job.done", ts=T, job_id="J1", recipients=["a@example.org"])
    write_head(folder, 1, "f" * 64, "2026-11-19.jsonl")
    log.reanchor("tester", "a planted gap, for the byte test", ts=T)
    log.append("job.after", ts=T, job_id="J2")
    assert verify(folder).ok
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


#: the same run on master before H-68 (2026-11-20, dfb92007): the files must stay byte for byte what they were
BEFORE = {
    ".lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "2026-11-19.jsonl": "67d8b7d9d5021a711c01489136420b77c5977f98af8ea98db62f473d80bd5593",
    "2026-11-20.jsonl": "cf96ee9e77c4bedd624041509f5ea12a914eb6f6d98b3804f6f3bc8b2808460e",
    "2026-11-20.jsonl.torn-1": "7f0fdc58ea1b72f3fa1b666d79004df91aca96628743ef45d6638029d6a037ec",
    "HEAD.json": "a339a1fa483aabb8f4f6b6916675a344ee14ef6062487963d5fcc7729c908e53",
}


def test_the_files_written_are_byte_for_byte_what_they_were_before(tmp_path: Path) -> None:
    got = _events(tmp_path / "audit")
    assert got == BEFORE
    head = json.loads((tmp_path / "audit" / "HEAD.json").read_text(encoding="utf-8"))
    assert sorted(head) == ["file", "hash", "lines"]
