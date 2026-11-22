"""R22-36 (review C-M1): the unsigned tail of the audit chain removed together with ``HEAD.json``.

A chain with events, a signed head over an earlier point, then events after it. Someone who can write the audit
volume cuts the events after the signed head and deletes ``HEAD.json``. The rest of the chain is internally sound and
agrees with every signed head, so before this card the next ordinary write adopted it (``audit.anchored``, a note in
``verify``) and the next night signed the shortened chain.

The rule held here: once a head has been signed, a chain without its head file is never adopted silently. The writer
refuses, ``verify`` fails with a named reason, and the signers refuse, until a person runs the explicit repair
(``tools/audit_verify.py --reanchor``), which is itself an event in the chain. A first start with no signed head, and a
chain from before the anchor existed, are still adopted as before.

The second half: a head file written again to match the cut, not deleted. The head file is not keyed, so the writer and
``verify`` hold the chain to the signed heads in the anchor folders they are given: a chain cut below a signed head is
refused whatever the head file says. A cut above the newest signed head with the head file written to match still
passes; that needs a head kept off the box, and a test below says so. Synthetic events and a test key only."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tb_common import audit, kek
from tb_common.audit import HEAD, AuditAnchorBroken, AuditLog, canonical, line_hash, read_signed_heads, verify

from tools import audit_verify
from tools.trialbox import audit_heads

T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)
NIGHT = datetime(2026, 11, 7, 0, 25, tzinfo=UTC)

pytestmark = pytest.mark.nodb


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV):
        monkeypatch.delenv(var, raising=False)
    paths = {name: tmp_path / name for name in ("audit", "share", "secrets", "run")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert audit_verify.init_key(paths["secrets"]) == 0  # a test key in a temporary secrets folder
    return paths


def _keys(box: dict[str, Path]) -> tuple[bytes, bytes]:
    return (kek.load_key_file(box["secrets"] / audit.SIGN_KEY_FILE),
            (box["secrets"] / audit.SIGN_PUB_FILE).read_bytes())  # fmt: skip


def _events(log: AuditLog, n: int, start: int = 0, kind: str = "job.created") -> None:
    for i in range(start, start + n):
        log.append(kind, ts=T0 + timedelta(minutes=i), actor="tester", detail={"i": i})


def _day_file(box: dict[str, Path]) -> Path:
    files = sorted(box["audit"].glob("*.jsonl"))
    assert len(files) == 1
    return files[0]


def _cut(box: dict[str, Path], keep: int) -> None:
    """The attack: keep the first ``keep`` events, remove the rest and ``HEAD.json``."""
    f = _day_file(box)
    f.write_text("".join(x + "\n" for x in f.read_text(encoding="utf-8").splitlines()[:keep]), encoding="utf-8")
    (box["audit"] / HEAD).unlink()


def _signed_chain(box: dict[str, Path]) -> AuditLog:
    """5 events, a head signed over them (event 6 is ``audit.head_signed``), then 5 unsigned events: 11 in all."""
    log = AuditLog(box["audit"], "UTC")
    _events(log, 5)
    priv, pub = _keys(box)
    log.sign_head(priv, pub, [box["share"]], actor="trialbox:audit-sign", ts=T0 + timedelta(minutes=5))
    _events(log, 5, start=6, kind="console.reveal")
    assert verify(box["audit"]).lines == 11
    return log


def _checked(box: dict[str, Path]) -> audit.VerifyResult:
    return verify(box["audit"], signed_heads=read_signed_heads(box["share"]),
                  trusted_keys=audit.read_public_keys([box["secrets"] / audit.SIGN_PUB_FILE]))  # fmt: skip


def _night(box: dict[str, Path], now: datetime = NIGHT) -> audit_heads.Night:
    return audit_heads.check_and_sign(box["audit"], box["secrets"], [box["share"]], now)


# ------------------------------------------------------------------------------------------------ the invariant
def test_once_a_head_is_signed_a_removed_head_file_is_never_silently_re_anchored(box: dict[str, Path]) -> None:
    """The reviewer's sequence: the tail after the signed head cut, ``HEAD.json`` deleted."""
    log = _signed_chain(box)
    _cut(box, keep=6)  # the signed events and the chain's own audit.head_signed stay; the 5 reveals go
    cut = _day_file(box).read_bytes()

    res = _checked(box)
    assert not res.ok and any("no head anchor" in e for e in res.errors), res.errors

    # the next ordinary write does not adopt the chain: nothing is written until a person has looked
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    assert _day_file(box).read_bytes() == cut and not (box["audit"] / HEAD).exists()
    res = _checked(box)
    assert not res.ok and not any("audit.anchored" in n for n in res.notes), (res.errors, res.notes)

    # neither signer signs the shortened chain
    night = _night(box)
    assert not night.ok and night.signed is None, night.problems
    priv, pub = _keys(box)
    with pytest.raises((AuditAnchorBroken, audit.AuditSignError)):
        log.sign_head(priv, pub, [box["share"]], ts=NIGHT)
    assert [h["lines"] for h in read_signed_heads(box["share"])] == [5]
    assert _day_file(box).read_bytes() == cut


def test_a_cut_back_to_the_signed_head_is_adopted_visibly_but_fails_and_is_not_signed(box: dict[str, Path]) -> None:
    """The cut also removes the chain's own ``audit.head_signed`` event, so the chain alone shows nothing: the next
    write adopts it, as for a chain from before the anchor. The signed heads off the box then name the adoption."""
    log = _signed_chain(box)
    _cut(box, keep=5)
    log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    res = _checked(box)
    assert not res.ok, res.notes
    assert any("audit.anchored" in e and "signed head" in e for e in res.errors), res.errors
    night = _night(box)
    assert not night.ok and night.signed is None, night.problems
    assert [h["lines"] for h in read_signed_heads(box["share"])] == [5]


def _adopt_as_an_earlier_writer_did(box: dict[str, Path]) -> None:
    """What the writer before this card wrote on the next event: ``audit.anchored`` over the cut chain."""
    f = _day_file(box)
    lines = f.read_text(encoding="utf-8").splitlines()
    prev = json.loads(lines[-1])["hash"]
    body = {"ts": "2026-11-06T13:00:00.000+00:00", "event": "audit.anchored", "actor": "tb_common.audit",
            "detail": {"lines": len(lines), "head": prev}, "prev_hash": prev}  # fmt: skip
    body["hash"] = line_hash(prev, body)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(canonical(body) + "\n")
    audit.write_head(box["audit"], len(lines) + 1, body["hash"], f.name)


def test_a_chain_adopted_after_a_signed_head_fails_even_without_the_anchor_folder(box: dict[str, Path]) -> None:
    _signed_chain(box)
    _cut(box, keep=6)
    _adopt_as_an_earlier_writer_did(box)
    for res in (verify(box["audit"]), _checked(box)):
        assert not res.ok and any("audit.anchored" in e and "signed head" in e for e in res.errors), res.errors
    assert not _night(box).ok
    # the explicit repair is the way out, and it stays in the chain
    AuditLog(box["audit"], "UTC").reanchor("audit_verify:steward", "tail lost, ticket TEST-36")
    res = _checked(box)
    assert res.ok, res.errors
    assert any("audit.reanchored" in n for n in res.notes) and any("audit.anchored" in n for n in res.notes)


# ------------------------------------------------------------------------------------------------ the repair
def test_the_explicit_repair_is_an_audited_act_and_lets_writing_and_signing_resume(box: dict[str, Path]) -> None:
    log = _signed_chain(box)
    _cut(box, keep=6)
    with pytest.raises(AuditAnchorBroken):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    on_disk = verify(box["audit"], require_head=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = audit_verify.main([str(box["audit"]), "--reanchor", "tail lost, ticket TEST-36", "--actor", "steward"])
    assert code == 0 and "audit.reanchored" in out.getvalue()
    newest = sorted(box["audit"].glob("*.jsonl"))[-1]  # the CLI writes at today's date
    last = json.loads(newest.read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == "audit.reanchored" and last["actor"] == "audit_verify:steward"
    assert last["detail"]["before"] is None  # the head file that was found: none
    assert last["detail"]["chain"] == {"lines": 6, "hash": on_disk.last_hash}  # the last event on disk
    assert last["detail"]["reason"] == "tail lost, ticket TEST-36"
    log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    res = _checked(box)
    assert res.ok and res.lines == 8, res.errors
    assert any("audit.reanchored" in n for n in res.notes)
    assert _night(box).ok


# ------------------------------------------------------------------------------------------------ what still passes
def test_a_first_start_and_a_chain_from_before_any_signed_head_are_still_adopted(box: dict[str, Path]) -> None:
    log = AuditLog(box["audit"], "UTC")
    _events(log, 3)
    assert verify(box["audit"]).ok
    (box["audit"] / HEAD).unlink()  # a chain from before the anchor: no signed head anywhere, none in the chain
    log.append("first.after.upgrade", ts=T0 + timedelta(hours=1), actor="tester")
    res = verify(box["audit"])
    assert res.ok and res.lines == 5 and any("audit.anchored" in n for n in res.notes), res.errors
    assert _night(box).ok  # nothing signed before the adoption: the first night signs it


def test_a_crash_between_the_line_and_its_head_is_still_accepted_after_a_signed_head(box: dict[str, Path]) -> None:
    log = _signed_chain(box)
    head = (box["audit"] / HEAD).read_bytes()
    log.append("crashed.after.line", ts=T0 + timedelta(hours=1), actor="tester")
    (box["audit"] / HEAD).write_bytes(head)
    res = _checked(box)
    assert res.ok and any("one event past" in n for n in res.notes), res.errors
    log.append("next", ts=T0 + timedelta(hours=2), actor="tester")
    assert _checked(box).ok and _night(box).ok


# ------------------------------------------------------------- the head file written, not deleted (lane F's review)
def _rewrite(box: dict[str, Path], keep: int, pad: int = 0) -> None:
    """The stronger attack: keep ``keep`` events, add ``pad`` rechained events, write ``HEAD.json`` to match."""
    f = _day_file(box)
    lines = f.read_text(encoding="utf-8").splitlines()[:keep]
    for i in range(pad):
        prev = json.loads(lines[-1])["hash"]
        body = {"ts": f"2026-11-06T14:{i:02d}:00.000+00:00", "event": "job.created", "actor": "tester", "prev_hash": prev}
        body["hash"] = line_hash(prev, body)
        lines.append(canonical(body))
    f.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    audit.write_head(box["audit"], len(lines), json.loads(lines[-1])["hash"], f.name)


@pytest.fixture
def seen(box: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A box whose writer is given the anchor folder (file mode; the console is given it on a composed box)."""
    monkeypatch.setenv(audit.ANCHOR_TARGETS_ENV, str(box["share"]))
    return box


@pytest.mark.parametrize(("keep", "pad"), [(3, 0), (4, 0), (3, 8), (2, 20)])
def test_a_head_file_written_to_match_a_cut_below_the_signed_head_is_refused(
    seen: dict[str, Path], keep: int, pad: int
) -> None:
    log = _signed_chain(seen)  # this writer has written the chain and seen it agree with the signed head
    _rewrite(seen, keep, pad)
    cut = _day_file(seen).read_bytes()
    for writer in (log, AuditLog(seen["audit"], "UTC")):
        with pytest.raises(AuditAnchorBroken, match="signed head"):
            writer.append("job.created", ts=T0 + timedelta(hours=3), actor="tester")
    assert _day_file(seen).read_bytes() == cut
    res = verify(seen["audit"])  # the plain check, with no heads handed to it
    assert not res.ok and any("signed head on the box (event 5)" in e for e in res.errors), res.errors
    assert audit.waits_for_a_person(seen["audit"])
    assert not _night(seen).ok
    # --reanchor is not the way out of this one: the signed head still says what the chain held
    AuditLog(seen["audit"], "UTC").reanchor("audit_verify:steward", "TEST-36")
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=4), actor="tester")
    assert not verify(seen["audit"]).ok


def test_a_cut_above_the_newest_signed_head_with_the_head_written_passes_until_a_head_off_the_box_says_no(
    seen: dict[str, Path],
) -> None:
    """The limit, stated: the events after the newest signed head are held by the head file alone, which is not
    keyed. Only a head signed after them (signing more often) or a copy of the head kept elsewhere shows the cut."""
    log = _signed_chain(seen)
    before = audit.read_head(seen["audit"])
    _rewrite(seen, keep=8)
    log.append("job.created", ts=T0 + timedelta(hours=3), actor="tester")
    assert verify(seen["audit"]).ok and _checked(seen).ok
    assert not verify(seen["audit"], anchor=before).ok  # the head as it stood, kept elsewhere


def test_a_writer_given_the_anchor_folder_never_adopts_a_chain_cut_back_to_the_signed_head(
    seen: dict[str, Path],
) -> None:
    """The cut removes the chain's own ``audit.head_signed`` event too: the chain alone shows nothing."""
    log = _signed_chain(seen)
    _cut(seen, keep=5)
    cut = _day_file(seen).read_bytes()
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    assert _day_file(seen).read_bytes() == cut and not (seen["audit"] / HEAD).exists()


def test_a_writer_given_the_anchor_folder_never_starts_a_new_chain_over_an_emptied_folder(
    seen: dict[str, Path],
) -> None:
    log = _signed_chain(seen)
    _day_file(seen).unlink()
    (seen["audit"] / HEAD).unlink()
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    assert not list(seen["audit"].glob("*.jsonl"))


def test_an_intact_chain_is_written_signed_and_checked_as_before_with_the_anchor_folder_seen(
    seen: dict[str, Path],
) -> None:
    log = _signed_chain(seen)
    assert verify(seen["audit"]).ok
    night = _night(seen)
    assert night.ok and night.signed is not None, night.problems
    _events(AuditLog(seen["audit"], "UTC"), 3, start=30)
    _events(log, 2, start=40)
    assert verify(seen["audit"]).ok and _checked(seen).ok
    assert audit.waits_for_a_person(seen["audit"]) is None


# ------------------------------------------------------------- chains of other shapes (the review's surviving mutants)
@pytest.mark.parametrize("keep", [6, 7, 8, 10])
def test_a_removed_head_file_is_refused_wherever_the_cut_is_after_the_signed_head(
    box: dict[str, Path], keep: int
) -> None:
    """The chain's ``audit.head_signed`` event is not always its last line."""
    log = _signed_chain(box)
    _cut(box, keep)
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    assert len(_day_file(box).read_text(encoding="utf-8").splitlines()) == keep


def test_a_removed_head_file_is_refused_when_the_signed_head_is_in_an_older_day_file(box: dict[str, Path]) -> None:
    log = AuditLog(box["audit"], "UTC")
    _events(log, 5)
    priv, pub = _keys(box)
    log.sign_head(priv, pub, [box["share"]], actor="trialbox:audit-sign", ts=T0 + timedelta(minutes=5))
    for day in (1, 2):
        for i in range(3):
            log.append("console.reveal", ts=T0 + timedelta(days=day, minutes=i), actor="tester")
    files = sorted(box["audit"].glob("*.jsonl"))
    assert len(files) == 3
    newest = files[-1]
    newest.write_text(newest.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    (box["audit"] / HEAD).unlink()
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(days=2, hours=1), actor="tester")
    _adopt_in(box, newest)
    res = verify(box["audit"])
    assert not res.ok and any("audit.anchored" in e and "signed head (event 6)" in e for e in res.errors), res.errors


def _adopt_in(box: dict[str, Path], f: Path) -> None:
    """``audit.anchored`` over the chain as an earlier writer wrote it, at the end of day file ``f``."""
    count = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in sorted(box["audit"].glob("*.jsonl")))
    prev = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])["hash"]
    body = {"ts": "2026-11-08T13:00:00.000+00:00", "event": "audit.anchored", "actor": "tb_common.audit",
            "detail": {"lines": count, "head": prev}, "prev_hash": prev}  # fmt: skip
    body["hash"] = line_hash(prev, body)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(canonical(body) + "\n")
    audit.write_head(box["audit"], count + 1, body["hash"], f.name)


def test_a_signed_head_event_that_came_through_the_journal_counts_as_the_box_writes_it(box: dict[str, Path]) -> None:
    """On a box the nightly signer's event arrives through the journal, so it carries ``journal``."""
    log = AuditLog(box["audit"], "UTC")
    _events(log, 5)
    log.append(audit.SIGNED_EVENT, ts=T0 + timedelta(minutes=5), actor="trialbox:audit-sign",
               journal={"seq": 6, "role": "tb_orchestrator", "at": "2026-11-06T12:05:00+00:00"},
               detail={"lines": 5, "anchors": 1})  # fmt: skip
    _events(log, 5, start=6, kind="console.reveal")
    _cut(box, keep=8)
    with pytest.raises(AuditAnchorBroken, match="signed head"):
        log.append("job.created", ts=T0 + timedelta(hours=1), actor="tester")
    _adopt_as_an_earlier_writer_did(box)
    res = verify(box["audit"])
    assert not res.ok and any("audit.anchored" in e and "signed head (event 6)" in e for e in res.errors), res.errors


# ------------------------------------------------------------- a box an earlier writer already re-anchored
def test_a_box_already_adopted_is_told_why_it_waits_and_is_not_stopped(box: dict[str, Path]) -> None:
    _signed_chain(box)
    _cut(box, keep=6)
    _adopt_as_an_earlier_writer_did(box)
    why = audit.waits_for_a_person(box["audit"])
    assert why and "--reanchor" in why and "05-updates-backup-restore-secrets.md" in why
    night = _night(box)
    assert not night.ok and any("--reanchor" in p and "05-updates" in p for p in night.problems), night.problems
    AuditLog(box["audit"], "UTC").append("job.created", ts=T0 + timedelta(hours=2), actor="tester")  # not stalled
    AuditLog(box["audit"], "UTC").reanchor("audit_verify:steward", "tail lost, ticket TEST-36")
    assert audit.waits_for_a_person(box["audit"]) is None and _night(box).ok


def test_the_update_says_once_per_run_that_the_audit_chain_waits_and_goes_on(box: dict[str, Path]) -> None:
    from types import SimpleNamespace

    from tools.trialbox.update import Updater

    _signed_chain(box)
    up = Updater.__new__(Updater)
    up.box = SimpleNamespace(env={"TB_AUDIT_HOST_DIR": str(box["audit"])})
    assert up._audit_waits() == []
    _cut(box, keep=6)
    _adopt_as_an_earlier_writer_did(box)
    notes = up._audit_waits()
    assert len(notes) == 1 and "WAITS FOR A PERSON" in notes[0] and "--reanchor" in notes[0], notes


def test_a_chain_that_refuses_is_asked_again_less_and_less_often(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import audit_writer

    class Stop(Exception):
        pass

    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 9:
            raise Stop

    def step(alive: Path | None = None) -> int:
        raise AuditAnchorBroken("waits for a person")

    drain = audit_writer.Drain.__new__(audit_writer.Drain)
    monkeypatch.setattr(drain, "step", step, raising=False)
    monkeypatch.setattr(audit_writer.time, "sleep", sleep)
    with pytest.raises(Stop):
        drain.run(alive=None)
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]
