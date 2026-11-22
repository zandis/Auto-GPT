"""R22-36 (review C-M1): the unsigned tail of the audit chain removed together with ``HEAD.json``.

A chain with events, a signed head over an earlier point, then events after it. Someone who can write the audit
volume cuts the events after the signed head and deletes ``HEAD.json``. The rest of the chain is internally sound and
agrees with every signed head, so before this card the next ordinary write adopted it (``audit.anchored``, a note in
``verify``) and the next night signed the shortened chain.

The rule held here: once a head has been signed, a chain without its head file is never adopted silently. The writer
refuses, ``verify`` fails with a named reason, and the signers refuse, until a person runs the explicit repair
(``tools/audit_verify.py --reanchor``), which is itself an event in the chain. A first start with no signed head, and a
chain from before the anchor existed, are still adopted as before. Synthetic events and a test key only."""

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
