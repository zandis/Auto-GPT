"""Card V-8 (a): tampering with the audit chain is caught, and the verifier says where.

A chain of three days is written through the product's own writer (``tb_common.audit.AuditLog``, which the
``audit-writer`` drain uses), with a signed head published to an off-box anchor folder each night, as
``trialbox audit-sign`` does (D-562). Each tampering is applied to a copy of the audit folder. The copy is then checked
by the two entries a person uses: ``tools/audit_verify.py <dir> --heads <anchor>`` (``make audit-verify ANCHOR=...``)
and the console audit page's Verify (``console.audit_page.verify_now``). Both must fail, and an error must name the
place. ``tests/unit/test_audit.py`` and ``test_audit_integrity.py`` hold the first cases; this file is the full set.

``AUDIT_TRAIL_OUT=<folder>`` writes ``tamper.json`` (one row per case) for the findings page. Synthetic events only."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common.audit import GENESIS, AuditLog, canonical, line_hash, write_head
from tb_common.crypto import ed25519_generate

from tools import audit_verify

DAYS = ("2026-11-14", "2026-11-15", "2026-11-16")
PER_DAY = 120
ACTORS = ("crc_lin", "pi_wu", "admin", "dm_chen")
KINDS = ("console.reveal", "registry.mark", "console.site_optout", "edc.signed", "console.login")


def _event(log: AuditLog, day: str, i: int) -> None:
    ts = datetime.fromisoformat(f"{day}T01:00:00+00:00") + timedelta(minutes=i)
    log.append(KINDS[i % len(KINDS)], ts=ts, actor=ACTORS[i % len(ACTORS)], job_id=f"J{i:05d}",
               detail={"ruleset": "GZQO", "pid": f"{i:032x}".replace("0", "a"), "n": i})  # fmt: skip


def _sign(log: AuditLog, share: Path, keys: tuple[bytes, bytes], day: str) -> None:
    log.sign_head(keys[0], keys[1], [share], actor="trialbox:audit-sign",
                  ts=datetime.fromisoformat(f"{day}T16:20:00+00:00"))  # fmt: skip


def _read(d: Path) -> dict[str, list[dict[str, Any]]]:
    return {f.name: [json.loads(x) for x in f.read_text("utf-8").splitlines()] for f in sorted(d.glob("*.jsonl"))}


def _write(d: Path, files: dict[str, list[dict[str, Any]]], *, rechain: bool = False, head: bool = False) -> None:
    """Write the files back. ``rechain``: recompute every ``prev_hash``/``hash`` from the start, as a forger who can
    write the volume does. ``head``: rewrite ``HEAD.json`` to the new end too."""
    for f in d.glob("*.jsonl"):
        f.unlink()
    prev, n, last = GENESIS, 0, None
    for name, recs in files.items():
        out = []
        for rec in recs:
            if rechain:
                rec = {k: v for k, v in rec.items() if k != "hash"}
                rec["prev_hash"] = prev
                rec["hash"] = prev = line_hash(prev, rec)
            out.append(canonical(rec))
            prev = str(rec["hash"])
            n += 1
        (d / name).write_text("".join(x + "\n" for x in out), encoding="utf-8")
        last = name
    if head:
        write_head(d, n, prev, last)


def _rehash_one(rec: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return {**body, "hash": line_hash(str(body["prev_hash"]), body)}


# ------------------------------------------------------------------------------------------------ the cases
D1, D2, D3 = (f"{d}.jsonl" for d in DAYS)


def _field(name: str, idx: int) -> Callable[[Path, dict[str, Any]], None]:
    def op(d: Path, ctx: dict[str, Any]) -> None:
        files = _read(d)
        files[name][idx]["actor"] = "someone_else"
        _write(d, files)

    return op


def _own_hash(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    files[D2][50]["actor"] = "someone_else"
    files[D2][50] = _rehash_one(files[D2][50])
    _write(d, files)


def _rechained(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    files[D2][50]["actor"] = "someone_else"
    _write(d, files, rechain=True, head=True)


def _delete(name: str, idx: int) -> Callable[[Path, dict[str, Any]], None]:
    def op(d: Path, ctx: dict[str, Any]) -> None:
        files = _read(d)
        del files[name][idx]
        _write(d, files)

    return op


def _reorder(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    files[D2][30], files[D2][31] = files[D2][31], files[D2][30]
    _write(d, files)


def _cut_tail(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    files[D3] = files[D3][:-5]
    _write(d, files)


def _drop_file(d: Path, ctx: dict[str, Any]) -> None:
    (d / D3).unlink()


def _prefix(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    del files[D3]
    files[D2] = files[D2][:-10]
    _write(d, files, head=True)


def _fresh(d: Path, ctx: dict[str, Any]) -> None:
    for f in d.iterdir():
        f.unlink()
    log = AuditLog(d, "UTC")
    for i in range(60):
        _event(log, DAYS[0], i)


def _duplicate(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    files[D2].insert(41, dict(files[D2][40]))
    _write(d, files)


def _insert(d: Path, ctx: dict[str, Any]) -> None:
    files = _read(d)
    prev = files[D2][40]["hash"]
    forged = {"ts": files[D2][40]["ts"], "event": "console.reveal", "actor": "pi_wu", "prev_hash": prev,
              "detail": {"ruleset": "GZQO", "n": -1}}  # fmt: skip
    forged["hash"] = line_hash(prev, forged)
    files[D2].insert(41, forged)
    _write(d, files)


def _swap_files(d: Path, ctx: dict[str, Any]) -> None:
    a, b = (d / D1).read_bytes(), (d / D2).read_bytes()
    (d / D1).write_bytes(b)
    (d / D2).write_bytes(a)


def _torn(d: Path, ctx: dict[str, Any]) -> None:
    """Power lost while the last line was written: the writer writes the line, then the anchor (audit.py ``_write``),
    so the anchor still names the line before it."""
    files = _read(d)
    n = sum(len(v) for v in files.values())
    raw = (d / D3).read_bytes()
    (d / D3).write_bytes(raw[: len(raw) - 40])  # the last line cut in its middle, no newline
    write_head(d, n - 1, files[D3][-2]["hash"], D3)


def _rollback(d: Path, ctx: dict[str, Any]) -> None:
    shutil.rmtree(d)
    shutil.copytree(ctx["backup"], d)  # yesterday's copy of the volume, its own HEAD.json included


def _rollback_unsigned(d: Path, ctx: dict[str, Any]) -> None:
    """Events written after the last signed head, then the volume rolled back before the next night signs."""
    shutil.rmtree(d)
    shutil.copytree(ctx["backup_unsigned"], d)


#: name, what is done, where the error must point (a regex over the errors), caught by design
CASES: list[tuple[str, Callable[[Path, dict[str, Any]], None], str]] = [
    ("field_first", _field(D1, 0), rf"{D1}:1: hash mismatch"),
    ("field_middle", _field(D2, 60), rf"{D2}:61: hash mismatch"),
    ("field_last", _field(D3, -1), rf"{D3}:\d+: hash mismatch"),
    ("own_hash_recomputed", _own_hash, rf"{D2}:52: prev_hash"),
    ("rechained_with_head", _rechained, r"event \d+ does not have the signed hash"),
    ("delete_middle", _delete(D2, 50), rf"{D2}:51: prev_hash"),
    ("delete_last", _delete(D3, -1), r"HEAD\.json: the chain ends at event"),
    ("reorder_two", _reorder, rf"{D2}:31: prev_hash"),
    ("cut_tail_5", _cut_tail, r"HEAD\.json: the chain ends at event"),
    ("drop_last_file", _drop_file, r"HEAD\.json: the chain ends at event"),
    ("prefix_with_head", _prefix, r"the chain has only \d+ events"),
    ("fresh_chain_from_genesis", _fresh, r"does not have the signed hash|the chain has only \d+ events"),
    ("duplicate_event", _duplicate, rf"{D2}:42: prev_hash"),
    ("insert_forged", _insert, rf"{D2}:43: prev_hash"),
    ("swap_day_files", _swap_files, rf"{D1}:1: prev_hash"),
    ("torn_last_line", _torn, rf"{D3}:\d+: invalid JSON"),
    ("rollback_to_backup", _rollback, r"the chain has only \d+ events"),
]
#: shown not caught, by the rule that signs the head once a night (D-562; doctor FAILs a head older than 36 hours)
WINDOW = [("rollback_after_last_signed_head", _rollback_unsigned)]


def run_cli(d: Path, share: Path | None) -> dict[str, Any]:
    out = io.StringIO()
    argv = [str(d), "--json"] + (["--heads", str(share)] if share else [])
    with contextlib.redirect_stdout(out):
        code = audit_verify.main(argv)
    rec = json.loads(out.getvalue())
    return {"code": code, "ok": rec["ok"], "errors": rec["errors"], "notes": rec["notes"], "files": rec["files"],
            "lines": rec["lines"]}  # fmt: skip


def run_console(d: Path, share: Path) -> dict[str, Any]:
    from console.audit_page import verify_now

    return verify_now(d, [share])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    root = tmp_path_factory.mktemp("tamper")
    good, share = root / "audit", root / "share"
    share.mkdir()
    keys = ed25519_generate()
    log = AuditLog(good, "UTC")
    ctx: dict[str, Any] = {}
    for k, day in enumerate(DAYS):
        for i in range(PER_DAY):
            _event(log, day, i)
        _sign(log, share, keys, day)
        if k == 1:
            ctx["backup"] = root / "backup"
            shutil.copytree(good, ctx["backup"])
    # the window case: a box whose last night is signed, then a day of events, then a rollback before the night
    wshare, wgood = root / "wshare", root / "wgood"
    wshare.mkdir()
    wlog = AuditLog(wgood, "UTC")
    for i in range(PER_DAY):
        _event(wlog, DAYS[0], i)
    _sign(wlog, wshare, keys, DAYS[0])
    ctx["backup_unsigned"] = root / "wbackup"
    shutil.copytree(wgood, ctx["backup_unsigned"])
    for i in range(PER_DAY):
        _event(wlog, DAYS[1], i)

    out: dict[str, dict[str, Any]] = {}
    base = {"cli": run_cli(good, share), "console": run_console(good, share), "files": len(list(good.glob("*.jsonl")))}
    out["_untouched"] = {**base, "where": "", "lines": base["cli"]}
    for name, op, where in CASES:
        d = root / name
        shutil.copytree(good, d)
        op(d, ctx)
        out[name] = {"cli": run_cli(d, share), "console": run_console(d, share), "cli_no_heads": run_cli(d, None),
                     "where": where}  # fmt: skip
    for name, op in WINDOW:
        d = root / name
        shutil.copytree(wgood, d)
        op(d, ctx)
        out[name] = {"cli": run_cli(d, wshare), "console": run_console(d, wshare), "cli_no_heads": run_cli(d, None),
                     "where": ""}  # fmt: skip
    torn = root / "torn_then_written"
    shutil.copytree(good, torn)
    _torn(torn, ctx)
    AuditLog(torn, "UTC").append("console.login", actor="admin", ts=datetime(2026, 11, 16, 9, tzinfo=UTC))
    out["torn_then_written"] = {"cli": run_cli(torn, share), "console": run_console(torn, share), "where": ""}
    if os.environ.get("AUDIT_TRAIL_OUT"):
        rows = []
        for name, r in out.items():
            if name.startswith("_"):
                continue
            rows.append({"case": name, "cli_heads_ok": r["cli"]["ok"], "console_ok": r["console"]["ok"],
                         "cli_no_heads_ok": r.get("cli_no_heads", {}).get("ok"),
                         "where_expected": r["where"], "first_error": (r["cli"]["errors"] or [""])[0]})  # fmt: skip
        dest = Path(os.environ["AUDIT_TRAIL_OUT"]) / "tamper.json"
        dest.write_text(json.dumps({"events": base["cli"], "cases": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


def test_the_untouched_chain_verifies_on_both_entries(results: dict[str, dict[str, Any]]) -> None:
    r = results["_untouched"]
    assert r["cli"]["ok"] and r["console"]["ok"], (r["cli"]["errors"], r["console"]["errors"])
    assert r["files"] == 3


@pytest.mark.parametrize("name", [c[0] for c in CASES if c[0] != "torn_last_line"])
def test_tampering_fails_and_says_where(results: dict[str, dict[str, Any]], name: str) -> None:
    r = results[name]
    for entry in ("cli", "console"):
        assert not r[entry]["ok"], f"{entry} passed a tampered chain ({name})"
        assert any(re.search(r["where"], e) for e in r[entry]["errors"]), (entry, r["where"], r[entry]["errors"])


def test_a_torn_last_line_fails_the_check_and_the_next_write_repairs_it_visibly(
    results: dict[str, dict[str, Any]],
) -> None:
    r = results["torn_last_line"]
    assert not r["cli"]["ok"] and any(re.search(r["where"], e) for e in r["cli"]["errors"])
    after = results["torn_then_written"]
    assert after["cli"]["ok"], after["cli"]["errors"]  # D-127: the writer moves the torn bytes aside, chained


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="V8-01: a torn last line is reported as tampering, never named a write cut short")  # fmt: skip
def test_a_torn_last_line_is_told_apart_from_tampering(results: dict[str, dict[str, Any]]) -> None:
    """A write cut short (power, disk) is not an attack: the person reading the check must be told which it is. The
    torn line is the file's last and has no newline; any wording that names it as such passes."""
    r = results["torn_last_line"]
    said = " ".join(r["cli"]["errors"] + r["cli"]["notes"])
    assert re.search(r"torn|cut short|incomplete|partial|interrupted|unfinished", said, re.I), said


def test_without_signed_heads_a_rechained_forgery_passes(results: dict[str, dict[str, Any]]) -> None:
    """The fact the page states: only the signed heads off the box catch a forger who rewrote the chain and its
    HEAD.json (D-272 left this open, D-355 closed it). ``make audit-verify`` without ``ANCHOR`` checks no head."""
    for name in ("rechained_with_head", "prefix_with_head", "fresh_chain_from_genesis", "rollback_to_backup"):
        assert results[name]["cli_no_heads"]["ok"], name


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="V8-02: audit_verify without --heads says PASS and never says no signed head was checked")  # fmt: skip
def test_a_check_without_signed_heads_says_so(results: dict[str, dict[str, Any]]) -> None:
    """The console says "only the chain and its head anchor were checked" when no anchor folder is set; the tool that
    ``make audit-verify`` runs prints PASS on a fully re-chained forgery with no word that nothing signed was read."""
    r = results["rechained_with_head"]["cli_no_heads"]
    said = " ".join(r["notes"])
    assert re.search(r"signed head|--heads|anchor folder|not checked", said, re.I), r


def test_the_window_after_the_last_signed_head_is_open(results: dict[str, dict[str, Any]]) -> None:
    """Shown, ruled: events after the newest signed head can be rolled back unseen until the next night signs
    (D-562 signs nightly; doctor FAILs a head older than 36 hours)."""
    r = results["rollback_after_last_signed_head"]
    assert r["cli"]["ok"] and r["console"]["ok"]
