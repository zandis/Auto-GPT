"""M2 (V-19): the scheduled code-system update, from a signed pack on a stick or in a folder.

A pack is a folder with ``pack.json``, its raw Ed25519 signature ``pack.json.sig`` (the vendor's key, as the update
bundle's) and the Parquet tables ``pack.json`` names::

    {"version": "2026.12.1",
     "tables": {"<table>": {"file": "<table>.parquet", "sha256": "...", "rows": 3, "version": "...",
                            "licence": "...", "register_id": "<id of its row in docs/licences/register.csv>"}}}

Before anything changes it is checked: the signature, every file's sha256, a version newer than the last one applied,
and a licence row (``cleared`` or ``own-work``) for every table; a licensed system is never in a pack (the hospital's
own copy only, D-1114). Refused: by name, nothing changed, one audit line. Applied: the tables the pack replaces are
kept aside (``installed.save_tables``, the place ``deploy/terminology-update.sh --rollback pack-<version>`` reads),
the tables and the manifest are swapped in, the vocabulary and the FHIR store are loaded from the one manifest, and
any reader that fails puts the old release back everywhere (``installed.restore_tables``, then the readers again).
A journal written before the swap lets a run that was cut short finish by putting the old tables back.

    python -m tools.terminology_pack run --pack DIR [--terminology DIR] [--keep DIR] [--night HH:MM-HH:MM]
    python -m tools.terminology_pack find [--update-dir DIR] [--stick DIR ...]     # the pack that is waiting
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

PACK, SIG = "pack.json", "pack.json.sig"
STATE, JOURNAL = ".pack-state.json", ".pack-journal.json"  # in the terminology volume, beside manifest.json
OK_STATUS = frozenset({"cleared", "own-work"})  # the register rows a pack's tables may stand on
EVENT = "terminology.update"
_VERSION = re.compile(r"^\d+(\.\d+){0,3}$")


class PackRefused(ValueError):
    """The pack is not applied; the text names why. Nothing changed."""


def _ver(text: str, what: str) -> tuple[int, ...]:
    if not _VERSION.match(text or ""):
        raise PackRefused(f"{what}: version {text!r} is not dotted numbers (e.g. 2026.12.1)")
    return tuple(int(p) for p in text.split("."))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def applied_version(term_dir: Path) -> str:
    p = term_dir / STATE
    return str(json.loads(p.read_text("utf-8")).get("version") or "") if p.is_file() else ""


def check(pack: Path, term_dir: Path, keys: Mapping[str, Any], register: Iterable[Any]) -> dict[str, Any]:
    """The pack's manifest when every check passes; else :class:`PackRefused`. ``keys`` are the trusted vendor keys
    (``tools.verify_update.trusted_keys``); ``register`` the rows of ``docs/licences/register.csv``."""
    from criteria_compiler.terminology import installed

    from tools.verify_update import _signed_by_any

    body_path = pack / PACK
    if not body_path.is_file() or not (pack / SIG).is_file():
        raise PackRefused(f"{pack}: needs {PACK} and {SIG} (an unsigned pack is never applied)")
    body = body_path.read_bytes()
    if not _signed_by_any((pack / SIG).read_bytes(), body, dict(keys)):
        raise PackRefused(f"{pack}: {PACK} is not signed by a trusted vendor key")
    try:
        man = json.loads(body)
        tables = dict(man["tables"])
    except (ValueError, KeyError, TypeError) as exc:
        raise PackRefused(f"{pack}: {PACK} is not a pack manifest ({type(exc).__name__})") from exc
    now_v, have = _ver(str(man.get("version")), "the pack"), applied_version(term_dir)
    if have and now_v <= _ver(have, "the box"):
        raise PackRefused(f"version {man['version']} is not newer than {have}, which is applied")
    rows = {r.id: r for r in register}
    for name, line in sorted(tables.items()):
        if not installed._plain_name(name) or installed.is_licensed(name):
            raise PackRefused(
                f"{name}: not a table a pack may carry (a licensed system comes only from the hospital's copy)"
            )
        row = rows.get(str(line.get("register_id") or ""))
        if row is None or row.status not in OK_STATUS:
            raise PackRefused(
                f"{name}: licence class not accepted: register row {line.get('register_id')!r} is "
                f"{'missing' if row is None else row.status}"
            )
        f = pack / str(line.get("file") or "")
        if f.parent != pack or not f.is_file():
            raise PackRefused(f"{name}: its file {line.get('file')!r} is not in the pack")
        if _sha(f) != line.get("sha256"):
            raise PackRefused(f"{name}: sha256 of {f.name} differs from {PACK} (wrong hash)")
    return dict(man)


def in_night(now: datetime, window: str) -> bool:
    """``window`` is ``HH:MM-HH:MM`` (it may pass midnight); empty is never a night (and is said by the caller)."""
    if not window:
        return False
    a, b = (tuple(int(x) for x in t.split(":")) for t in window.split("-"))
    t, s, e = (now.hour, now.minute), a, b
    return s <= t < e if s <= e else (t >= s or t < e)


def _failed(report: Mapping[str, Any]) -> list[str]:
    from tools import terminology_load as tl

    return [*report.get("problems", []), *(f"{k}: {why}" for k, why, fault in tl.skipped(dict(report)) if fault)]


def _swap(pack: Path, man: Mapping[str, Any], term_dir: Path, now: datetime) -> None:
    """All the tables staged first, then renamed in, then the manifest once (write-then-rename, fsync)."""
    import fcntl

    from criteria_compiler.terminology import installed

    names = sorted(man["tables"])
    with (term_dir / ".manifest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for n in names:
            tmp = term_dir / f"{n}.parquet.tmp"
            shutil.copyfile(pack / man["tables"][n]["file"], tmp)
            with tmp.open("rb") as f:
                os.fsync(f.fileno())
            if _sha(tmp) != man["tables"][n]["sha256"]:  # OCR 1523-9: the bytes installed are the bytes checked
                for m in names:
                    (term_dir / f"{m}.parquet.tmp").unlink(missing_ok=True)
                raise PackRefused(f"{n}: {man['tables'][n]['file']} changed after it was checked")
        data = installed.manifest(term_dir)
        for n in names:
            os.replace(term_dir / f"{n}.parquet.tmp", term_dir / f"{n}.parquet")
            t = man["tables"][n]
            data["tables"][n] = {"source": f"pack {man['version']} ({t['file']})",
                                 "version": str(t.get("version") or man["version"]),
                                 "licence": str(t.get("licence") or ""), "loaded_at": now.isoformat(timespec="seconds"),
                                 "sha256": t["sha256"], "rows": t.get("rows")}  # fmt: skip
        _fsync_write(term_dir / installed.MANIFEST, json.dumps(data, indent=1, sort_keys=True) + "\n")


def _recover(term_dir: Path, readers: Callable[[Path], Mapping[str, Any]]) -> str:
    """A journal left by a run that was cut short: the old tables go back, into the readers too (OCR 1523-9), and the
    next run starts clean."""
    from criteria_compiler.terminology import installed

    j = term_dir / JOURNAL
    if not j.is_file():
        return ""
    keep = Path(json.loads(j.read_text("utf-8"))["keep"])
    installed.restore_tables(term_dir, keep)
    for tmp in term_dir.glob("*.parquet.tmp"):
        tmp.unlink()
    readers(term_dir)
    j.unlink()
    return f"a cut-short update was undone from {keep}"


def run(pack: Path, term_dir: Path, keep_root: Path, keys: Mapping[str, Any], register: Iterable[Any],
        readers: Callable[[Path], Mapping[str, Any]], audit: Callable[..., Any], now: datetime,
        night: str = "") -> tuple[str, str]:  # fmt: skip
    """``(outcome, text)``: ``applied``, ``waits`` (a night is running), ``refused`` or ``reverted`` (a reader
    failed, the old release is back). One audit line for each but ``waits``."""
    from criteria_compiler.terminology import installed

    if in_night(now, night):
        return "waits", f"the night window {night} is running; the pack waits"
    undone = _recover(term_dir, readers)
    try:
        man = check(pack, term_dir, keys, register)
    except PackRefused as exc:
        audit(EVENT, outcome="refused", reason=str(exc)[:300])
        return "refused", str(exc)
    keep = keep_root / f"pack-{man['version']}"
    installed.save_tables(term_dir, keep)
    _fsync_write(term_dir / JOURNAL, json.dumps({"keep": str(keep)}))
    before = installed.manifest(term_dir)
    try:
        _swap(pack, man, term_dir, now)
    except PackRefused as exc:
        (term_dir / JOURNAL).unlink()
        audit(EVENT, outcome="refused", reason=str(exc)[:300])
        return "refused", str(exc)
    try:
        bad = _failed(readers(term_dir))
    except Exception as exc:  # a reader that raises is a reader that failed
        bad = [f"{type(exc).__name__}: {str(exc)[:200]}"]
    if bad:
        installed.restore_tables(term_dir, keep)
        readers(term_dir)  # the old release into every reader again
        (term_dir / JOURNAL).unlink(missing_ok=True)
        audit(EVENT, outcome="reverted", version=man["version"], reason="; ".join(bad)[:300])
        return "reverted", f"a reader failed ({'; '.join(bad)[:200]}); the old release is back everywhere"
    _fsync_write(
        term_dir / STATE, json.dumps({"version": man["version"], "applied_at": now.isoformat(timespec="seconds")})
    )
    (term_dir / JOURNAL).unlink(missing_ok=True)
    changed = sorted(n for n, ln in installed.manifest(term_dir)["tables"].items() if before["tables"].get(n) != ln)
    audit(EVENT, outcome="applied", version=man["version"], tables=changed)
    return "applied", f"version {man['version']}: {', '.join(changed)}" + (f"; {undone}" if undone else "")


def find(update_dir: str, sticks: Iterable[str]) -> Path | None:
    """The pack folder waiting: the configured folder first, then each stick's top folder or its ``terminology``."""
    for base in [update_dir, *sticks]:
        for cand in (Path(base), Path(base) / "terminology") if base else ():
            if (cand / PACK).is_file():
                return cand
    return None


def update_row(env: Mapping[str, str], where: Path) -> tuple[str, str, str]:
    """The doctor's row of the update's state: the pack waiting against the version applied in ``where``. Standard
    library only: it reads the host's folders, where a pack is. What cannot be read is said by name, never a FAIL."""
    key = "terminology_update"
    try:
        have = applied_version(where) if where.is_dir() else ""
        pack = find(
            env.get("TB_TERMINOLOGY_UPDATE_DIR", ""), [s for s in env.get("TB_TERMINOLOGY_STICK", "").split(":") if s]
        )
        if pack is None:
            return key, "PASS", f"current: pack version {have or 'none applied'}; no pack waiting"
    except (OSError, ValueError) as exc:
        return key, "WARN", f"NOT CHECKED: {where} cannot be read ({type(exc).__name__})"
    try:
        want = str(json.loads((pack / PACK).read_text("utf-8")).get("version"))
        due = _ver(want, "the pack") > _ver(have, "the box") if have else True
        since = datetime.fromtimestamp((pack / PACK).stat().st_mtime).date().isoformat()
    except (OSError, ValueError, PackRefused) as exc:
        return key, "WARN", f"NOT CHECKED: the pack in {pack} cannot be read ({type(exc).__name__})"
    if due:
        return key, "WARN", f"update due since {since}: pack {want} in {pack}, applied {have or 'none'}"
    return key, "PASS", f"current: pack {want} already applied"


def tables_row(env: Mapping[str, str]) -> tuple[str, str, str]:
    """The doctor's row of every table with its rows, version and hash (shipped and loaded): the box image's part
    (``doctor.IMAGE_CHECKS``), where the compiler's package is."""
    from criteria_compiler.terminology import installed

    key, lines = "terminology_tables", dict[str, Any]()
    try:
        if installed.shipped_tables():
            lines.update(installed.manifest(installed.SHIPPED_DIR)["tables"])
        lines.update(installed.manifest(installed.installed_dir(dict(env)))["tables"])
    except installed.TerminologyRefused as exc:
        return key, "WARN", f"NOT CHECKED: {exc}"
    said = "; ".join(f"{n} {ln.get('rows')} rows ({ln.get('version')}, sha256 {str(ln.get('sha256'))[:12]})"
                     for n, ln in sorted(lines.items()))  # fmt: skip
    return key, "PASS", said or "no tables loaded"


def doctor_checks(env: Mapping[str, str], now: datetime) -> list[tuple[str, str, str]]:
    """Both rows ``(key, PASS|WARN|FAIL, text)``, where the code systems' folder and the compiler's package are."""
    from criteria_compiler.terminology import installed

    return [update_row(env, installed.installed_dir(dict(env))), tables_row(env)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.terminology_pack", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="check and apply one pack")
    r.add_argument("--pack", required=True)
    r.add_argument("--terminology", default="")
    r.add_argument("--keep", default="/data/terminology-previous")
    r.add_argument(
        "--night", default=os.environ.get("TB_TERMINOLOGY_NIGHT", ""), help="HH:MM-HH:MM; empty: not checked"
    )
    f = sub.add_parser("find", help="print the pack folder that is waiting, else nothing")
    f.add_argument("--update-dir", default=os.environ.get("TB_TERMINOLOGY_UPDATE_DIR", ""))
    f.add_argument("--stick", action="append", default=[])
    a = p.parse_args(argv)
    if a.cmd == "find":
        got = find(a.update_dir, a.stick)
        print(got or "")
        return 0
    from criteria_compiler.terminology import installed
    from tb_common.audit_writer import open_audit

    from tools import licence_register
    from tools import terminology_load as tl
    from tools.verify_update import trusted_keys

    audit_dir = os.environ.get("TB_AUDIT_DIR", "")
    if not audit_dir:
        print(
            "terminology_pack: TB_AUDIT_DIR is not set; an update is never applied without its audit line",
            file=sys.stderr,
        )
        return 2
    keys, _ = trusted_keys(None, sorted(Path(os.environ.get("TB_VENDOR_KEYS", "deploy/keys")).glob("*.pub")))
    term = Path(a.terminology) if a.terminology else installed.installed_dir()
    log = open_audit(Path(audit_dir))  # the journal on a box (D-394), never the chain's own files
    out, text = run(Path(a.pack), term, Path(a.keep), keys, licence_register.load(),
                    tl.run_here, log.append,
                    datetime.now().astimezone(), a.night)  # fmt: skip
    print(f"terminology_pack: {out}: {text}")
    return {"applied": 0, "waits": 0, "refused": 3, "reverted": 4}[out]


if __name__ == "__main__":
    raise SystemExit(main())
