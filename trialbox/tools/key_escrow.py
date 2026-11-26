"""The escrow copy of a TPM-sealed KEK (TB-SOP-03 §5, D-894): ``python -m tools.keys escrow-shares``.

A TPM box's KEK (back end ``file``) is bound to its board: a dead board opens nothing. An escrow set is that KEK
split into shares (GF(256), any ``threshold`` of ``count``), one per named custodian, written only to removable media
named on the command line (never to the box's disks; the folder must already be there, it is never made here). The
set is recorded in ``kek.json``'s ``escrow``: its id, the threshold and count, the KEK id it opens, the time, each
share's custodian and fingerprint. Never a share. Making it is the audit event ``keys.escrow``.

On a new board, with the secrets volume restored from the backup, ``python -m tools.keys unseal --share <file> ...
--witness <name>`` takes ``threshold`` escrow shares, writes the KEK to the runtime file and an escrow-use record
(``deploy/site/escrow-use-<time>.md`` and ``.json``, signed by the custodians who came and the witness; the audit
event ``keys.escrow_unseal``). Then ``rotate-kek --backend file ... --escrow-out <media>`` puts a new KEK on the new
board's TPM with a new escrow set: the old shares open only the old KEK.

Refused: a threshold under 2 or not under the count; a custodian count other than the share count, or a name twice; a
folder inside the secrets folder, on the secrets folder's or the system's disk, or on a disk that is not removable;
a second set for the same KEK (a lost or doubtful set is replaced by ``rotate-kek``, which makes the old shares
useless); no audit folder.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common import kek as K

EVENT = "keys.escrow"
USE_EVENT = "keys.escrow_unseal"
ACTOR = "python -m tools.keys escrow-shares"
USE_ACTOR = "python -m tools.keys unseal --share (escrow)"
FILE_PREFIX = "escrow-"
USE_PREFIX = "escrow-use-"
SYSFS = Path("/sys")


def share_fingerprint(text: str) -> str:
    from tools import key_ceremony as kc

    return kc.share_fingerprint(text)


def _dev(p: Path) -> int:
    return p.stat().st_dev


def removable(dev: int, sysfs: Path = SYSFS) -> bool:
    """Whether the block device ``dev`` (a ``st_dev``) is removable: sysfs ``removable`` is 1 on the disk or its
    parent (a partition's), or the device hangs off a USB bus."""
    node = sysfs / "dev" / "block" / f"{os.major(dev)}:{os.minor(dev)}"
    if not node.exists():
        return False
    real = node.resolve()
    for cand in (real, real.parent):
        try:
            if (cand / "removable").read_text(encoding="utf-8").strip() == "1":
                return True
        except OSError:
            continue
    return "/usb" in real.as_posix()


def media_problem(out: Path, sec: Path) -> str | None:
    """Why ``out`` may not take escrow shares, or None: they go only to removable media, never to the box's disks."""
    if not out.is_dir():
        return f"{out} is not there: name the mounted removable media's folder (it is never made here)"
    if K._inside(out, sec):
        return f"{out} is inside the secrets folder {sec}: shares go to removable media only"
    dev = _dev(out)
    if dev == _dev(sec):
        return f"{out} is on the same disk as the secrets folder {sec}: shares go to removable media only"
    if dev == _dev(Path("/")):
        return f"{out} is on the box's system disk: shares go to removable media only"
    if not removable(dev):
        return (
            f"{out} is not on removable media (the disk is not removable, nor on USB): shares never go to a fixed disk"
        )
    return None


def check(threshold: int, count: int, custodians: Sequence[str], out: Path | None, sec: Path) -> list[str]:
    """Every refusal before anything is made; returns the custodians' names, stripped."""
    names = [c.strip() for c in custodians if c.strip()]
    if threshold < 2:
        raise K.KekError(f"threshold {threshold}: at least 2 custodians must come together to open the KEK")
    if threshold >= count:
        raise K.KekError(f"threshold {threshold} of {count} shares: the threshold is fewer than the shares, so a "
                         "lost share does not lose the KEK")  # fmt: skip
    if count > 255:
        raise K.KekError("at most 255 shares")
    if len(names) != count:
        raise K.KekError(f"{count} shares and {len(names)} custodians named (--custodian, repeat): each share needs "
                         "one named custodian, in the order of the share numbers")  # fmt: skip
    if len(set(names)) != len(names):
        raise K.KekError("a custodian is named twice: each share goes to another person")
    if out is None:
        raise K.KekError("--escrow-out <removable media folder> is needed: the shares go there, one file each")
    why = media_problem(out, sec)
    if why:
        raise K.KekError(why)
    return names


def split(
    kek: bytes, threshold: int, names: Sequence[str], out: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    """Write one escrow share file per custodian to ``out`` (0600, never overwritten); return the ``escrow`` entry of
    ``kek.json`` (no share in it)."""
    set_id, shares = K.make_shares(kek, threshold, len(names))
    paths = [out / f"{FILE_PREFIX}{set_id}-{s.index}-of-{s.count}.txt" for s in shares]
    for p in paths:
        if p.exists():
            raise K.KekError(f"{p} exists: shares are never overwritten")
    rows = []
    for s, p, name in zip(shares, paths, names, strict=True):
        text = s.text() + "\n"
        K._write_private(p, text.encode())
        rows.append({"share": s.index, "of": s.count, "custodian": name, "fingerprint": share_fingerprint(text),
                     "file": p.name})  # fmt: skip
    return {"set_id": set_id, "threshold": threshold, "count": len(names), "kek_id": K.kek_id(kek),
            "made_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"), "shares": rows}  # fmt: skip


def current(meta: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The escrow set of ``kek.json``, whether or not it opens the current KEK; None without one."""
    esc = (meta or {}).get("escrow")
    return dict(esc) if isinstance(esc, Mapping) else None


def stale(meta: Mapping[str, Any] | None) -> bool:
    esc = current(meta)
    return esc is not None and esc.get("kek_id") != (meta or {}).get("kek_id")


#: the back end whose KEK is bound to the board (a TPM): only an escrow set opens it on new hardware (D-894)
BOARD_BOUND = "file"
GATE = "go-live gate key-escrow"  # INT-M5 (R22-33): the doctor names it while open; the acceptance refuses


def go_live(sec: Path, deploy: Path) -> tuple[bool, str]:
    """INT-M5 (R22-33): whether the box's KEK can be opened on new hardware, as go-live asks it: ``(ok, why)``. Fails
    closed: a secrets folder that is not here or cannot be read, no KEK, a TPM KEK with no escrow set, a set of an
    older KEK, no ceremony record of the current KEK, a newest record that does not list the set."""
    from tools import key_ceremony as kc

    how = "python -m tools.keys escrow-shares, then a new ceremony record (TB-SOP-03 §5; docs/security/10)"
    if not sec.is_dir():
        return False, f"the secrets folder {sec} is not here: the KEK was not read"
    try:
        meta = K.read_meta(sec)
    except (K.KekError, PermissionError) as exc:
        return False, f"the KEK's record cannot be read ({exc})"
    if meta is None:
        return False, f"no KEK in {sec}: the site keys are not under a KEK (python -m tools.keys init)"
    kek_id, backend = str(meta.get("kek_id")), str(meta.get("backend"))
    if backend != BOARD_BOUND:
        return True, f"KEK {kek_id} ({backend}) is not bound to the board: no escrow set is needed"
    esc = current(meta)
    if esc is None:
        return False, (f"the TPM-sealed KEK {kek_id} has no escrow set: a dead board opens nothing and a restore on "
                       f"new hardware fails. Make one: {how}")  # fmt: skip
    if stale(meta):
        return False, (f"the escrow set {esc.get('set_id')} is of an older KEK ({esc.get('kek_id')}); the KEK is "
                       f"now {kek_id}: its shares open nothing. A new set: {how}")  # fmt: skip
    rec = kc.newest(deploy)
    if rec is None:
        return False, f"no key ceremony record in {deploy / 'site'} for KEK {kek_id}: {how}"
    if (rec.get("kek") or {}).get("kek_id") != kek_id:
        return False, (f"the newest ceremony record is of KEK {(rec.get('kek') or {}).get('kek_id')}, not "
                       f"{kek_id}: {how}")  # fmt: skip
    if (rec.get("escrow") or {}).get("set_id") != esc.get("set_id"):
        return False, (f"the escrow set {esc.get('set_id')} is not on the newest ceremony record: its custodians "
                       f"have not signed it. {how}")  # fmt: skip
    return True, (f"escrow set {esc.get('set_id')} ({esc.get('threshold')} of {esc.get('count')}) opens KEK "
                  f"{kek_id}, on the ceremony record of {str(rec.get('at'))[:10]}")  # fmt: skip


def audit_dir(env: Mapping[str, str], arg: str | None) -> Path:
    where = Path(arg) if arg else Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None
    if where is None or not where.is_dir():
        raise K.KekError("no audit folder (--audit-dir, TB_AUDIT_DIR): the escrow is an audit event, refused without")
    return where


def audit(where: Path, event: str, actor: str, detail: Mapping[str, Any]) -> None:
    from tb_common.audit import AuditLog

    AuditLog(where).append(event, actor=actor, input_sha="", detail=dict(detail))


def summary(esc: Mapping[str, Any]) -> dict[str, Any]:
    """What the audit and the ceremony record carry: fingerprints and names only."""
    return {k: esc[k] for k in ("set_id", "threshold", "count", "kek_id", "made_at", "shares")}


def use_record(deploy: Path, esc: Mapping[str, Any], indices: Sequence[int], witness: str, *,
               now: datetime | None = None) -> tuple[Path, dict[str, Any]]:  # fmt: skip
    """The escrow-use record: which custodians brought which share, the witness, the time; never a share."""
    by = {int(r["share"]): r for r in esc.get("shares", [])}
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    rows = [{"share": i, "custodian": by.get(i, {}).get("custodian", "unknown"),
             "fingerprint": by.get(i, {}).get("fingerprint", "")} for i in indices]  # fmt: skip
    rec = {"format": "tb-escrow-use/1", "at": at, "set_id": esc["set_id"], "kek_id": esc["kek_id"],
           "witness": witness, "shares": rows}  # fmt: skip
    site = deploy / "site"
    site.mkdir(parents=True, exist_ok=True)
    stem = USE_PREFIX + at.replace(":", "").replace("-", "").replace("+0000", "Z")
    md = site / f"{stem}.md"
    if md.exists():
        raise K.KekError(f"{md} exists: an escrow-use record is never overwritten")
    lines = [f"# Escrow shares used ({at})", "",
             f"The KEK {esc['kek_id']} was opened from escrow set {esc['set_id']} ({esc['threshold']} of "
             f"{esc['count']}). Next: rotate-kek onto this board's TPM with a new escrow set (TB-SOP-03 §5).", "",
             "| Share | Custodian | Share fingerprint |", "| --- | --- | --- |"]  # fmt: skip
    lines += [f"| {s['share']} | {s['custodian']} | `{s['fingerprint']}` |" for s in rec["shares"]]
    lines += ["", "No share is in this record. Signed by:", ""]
    lines += [f"- Custodian {s['custodian']}: ____________________ date ______" for s in rec["shares"]]
    lines += [f"- Witness {witness}: ____________________ date ______", ""]
    md.write_text("\n".join(lines), encoding="utf-8")
    (site / f"{stem}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return md, rec
