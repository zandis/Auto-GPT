"""One install step: the code systems of one manifest into the three readers (V-18 with DB-C1, D-1182).

The **one manifest** is the box's terminology: the tables shipped in the image (``criteria_compiler.terminology``'s
Parquet, by their sha256) and the tables loaded at install into ``TB_TERMINOLOGY_DIR`` (its ``manifest.json``: each
table's sha256, version and licence line). Its digest is the **release** (``TL-`` and 12 hex). The three readers are:

* the compiler's folder (``TB_TERMINOLOGY_DIR`` itself; the compiler reads it as loaded);
* the OMOP vocabulary (``omop.concept`` and its relations, ``omop.vocab_load``): the shipped Parquet, and each table
  loaded at install as its code system's release;
* the FHIR store (``tools.fhir_codesystems``): each system the box may carry, one resource each.

All three are fed from the same rows, in one run. The run's **report** (``--report``, JSON) names the release and each
reader's result. ``check`` compares a report with the terminology as it is now: the doctor fails when the tables
changed after the last run, or a reader was not loaded. A system that is missing or not allowed never stops the run:
it is a warning, a line of ``poc-stops.jsonl`` (``--deploy``), and it is loaded later by the same command.

    python -m tools.terminology_load load [--terminology DIR] [--fhir URL] [--deploy DIR] [--report FILE]
    python -m tools.terminology_load check --report FILE [--terminology DIR]
    python -m tools.terminology_load skipped --report FILE      # one 'key<TAB>why' line each, for the installer

Offline: reads files on the box, the vocabulary database and the FHIR store; never copies a table anywhere else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

BY = "terminology_load"
# what a reader that fails raises: said in the report, never a stop (a database or store error, a file refused)
FAILED = (OSError, RuntimeError, ValueError, LookupError, TypeError)
RELEASE_PREFIX = "TL-"
# the tables loaded at install that are code lists (code, display) of one system; the ICD-10-CM blocks and index are
# names for the mapper, and a site list maps local codes (each row its own system): neither is a code system release
CODE_COLUMNS = {"nhi_drug_list": ("nhi_code", "name")}


def httpx_error() -> type[Exception]:
    import httpx  # here, not at the top: the installer's host reads a report with the standard library only

    return httpx.HTTPError


def shipped_dir() -> Path:
    from criteria_compiler.terminology.mapper import TERM_DIR

    return TERM_DIR


def manifest(term_dir: Path) -> dict[str, Any]:
    """The one manifest: what is shipped and what was loaded at install, by sha256, and its release digest."""
    from criteria_compiler.terminology import installed as inst
    from omop.vocab_load import parquet_sha

    tables = inst.manifest(term_dir).get("tables") or {}
    loaded = {name: {"sha256": str(line.get("sha256") or ""), "version": str(line.get("version") or ""),
                     "rows": line.get("rows")} for name, line in sorted(tables.items())}  # fmt: skip
    shipped = parquet_sha(shipped_dir())
    body = json.dumps({"shipped": shipped, "loaded": {k: v["sha256"] for k, v in loaded.items()}}, sort_keys=True)
    return {"release": RELEASE_PREFIX + hashlib.sha256(body.encode()).hexdigest()[:12], "shipped": shipped,
            "loaded": loaded}  # fmt: skip


def code_lists(term_dir: Path) -> dict[str, tuple[str, str, list[tuple[str, str]]]]:
    """``table -> (system, version, [(code, display)])`` for each table loaded at install that is one system's codes."""
    from criteria_compiler.terminology import installed as inst
    from criteria_compiler.terminology.mapper import table_system

    out: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    for name, line in sorted((inst.manifest(term_dir).get("tables") or {}).items()):
        system = table_system(name)
        if not system or system == "site" or name.startswith("icd10cm_"):
            continue
        rows = inst.read_table(term_dir, name) or []  # refused: TerminologyRefused, said by the caller
        code, disp = CODE_COLUMNS.get(name, ("code", "display"))
        pairs = [(str(r.get(code) or ""), str(r.get(disp) or "")) for r in rows if r.get(code)]
        out[name] = (system, str(line.get("version") or ""), pairs)
    return out


def load_omop(db: Any, term_dir: Path, release: str, by: str = BY) -> list[dict[str, Any]]:
    """The shipped Parquet and each table loaded at install into the vocabulary; a table that cannot be read is said."""
    from criteria_compiler.terminology import installed as inst
    from omop import vocab_load as vl

    out = [{"table": "shipped", **vl.load_terminology(db, shipped_dir(), by=by).as_dict()}]
    try:
        lists = code_lists(term_dir)
    except inst.TerminologyRefused as exc:
        return [*out, {"table": "loaded", "state": "skipped", "detail": str(exc)}]
    for name, (system, version, pairs) in lists.items():
        res = vl.load_code_list(db, system, version or "loaded", pairs, source=f"{name} ({release})", by=by)
        out.append({"table": name, "system": system, **res.as_dict()})
    return out


def run(term_dir: Path, fhir: str, db: Any | None, wait: float = 900.0, by: str = BY) -> dict[str, Any]:
    """One pass: the manifest, then the vocabulary, then the FHIR store. A reader that fails is said, never a stop."""
    from tools import fhir_codesystems as fc

    man = manifest(term_dir)
    report: dict[str, Any] = {"release": man["release"], "manifest": man, "omop": [], "fhir": [], "problems": []}
    if db is None:
        report["problems"].append("omop: the vocabulary database could not be opened")
    else:
        try:
            report["omop"] = load_omop(db, term_dir, man["release"], by)
        except FAILED as exc:
            report["problems"].append(f"omop: {type(exc).__name__}: {str(exc)[:300]}")
    try:
        outcomes = fc.load(fc.Store(fhir), term_dir, wait=wait)
        report["fhir"] = [
            {"key": o.key, "state": o.state, "detail": o.detail, "id": o.id, "absent": o.absent} for o in outcomes
        ]
    except (*FAILED, httpx_error()) as exc:
        report["problems"].append(f"fhir: {type(exc).__name__}: {str(exc)[:300]}")
    report["atc_losses"] = atc_losses(term_dir)
    return report


def atc_losses(term_dir: Path) -> dict[str, list[str]]:
    """V-18b review F1: the groupers whose ATC families no code of the site's copy, the NHI lists or the grouper
    itself fills (``Terminology.atc_losses``), with the terminology as loaded now."""
    from criteria_compiler.terminology.mapper import Terminology

    return Terminology(installed=term_dir).atc_losses()


def skipped(report: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """``(key, why, fault)`` of each system or reader the run did not load. ``fault`` is false for a system the box
    was not given, or may not carry: the "information still needed" page lists it, but nothing failed."""
    out = [(f"fhir/{r['key']}", r["detail"], not r.get("absent")) for r in report.get("fhir") or []
           if r.get("state") == "skipped"]  # fmt: skip
    out += [(f"omop/{r['table']}", r.get("detail", ""), True) for r in report.get("omop") or []
            if r.get("state") == "skipped"]  # fmt: skip
    out += [(p.split(":", 1)[0], p, True) for p in report.get("problems") or []]
    # V-18b F1: a grouper that lost ATC codes reads its families only: information still needed, not a fault
    out += [(f"atc/{name}", f"ATC families with no code to list ({', '.join(codes)}): load the site's ATC copy",
             False) for name, codes in (report.get("atc_losses") or {}).items()]  # fmt: skip
    return out


def changed(report: dict[str, Any]) -> list[str]:
    """V-18b (D-1183): the systems this run loaded into the FHIR store anew (a new version, or one rolled back). The
    store keeps its ``$lookup`` and ``$validate-code`` answers for minutes, and no operation of the pinned store clears
    them: after such a load it is restarted, so no caller sees the earlier version's answer (V18-01)."""
    loaded = [str(r["key"]) for r in report.get("fhir") or [] if r.get("state") == "loaded"]
    return sorted({*loaded, *(str(k) for k in report.get("pending_restart") or [])})


def carry(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Review 1439-4: the systems an earlier load changed whose restart never ran or did not answer stay pending in
    the new report (``pending_restart``), so a rerun that finds them unchanged still restarts the store, and the
    doctor keeps its warning until a restart answers."""
    if not old:
        return new
    done = old.get("store_restart")
    pending = set() if isinstance(done, dict) and done.get("answered") else set(changed(old))
    return {**new, "pending_restart": sorted(pending)} if pending else new


def restarted(report: dict[str, Any], answered: bool, seconds: int, at: str) -> dict[str, Any]:
    """The report with the store's restart after the load (``store_restart``): when, whether it answered again, and
    how long it took. The doctor reads it."""
    return {**report, "store_restart": {"at": at, "answered": answered, "seconds": seconds,
                                        "systems": changed(report)}}  # fmt: skip


def write_text_whole(path: Path, text: str) -> None:
    """``text`` written whole or not at all: a temporary file beside it, synced, then renamed, so neither a kill nor
    a power cut leaves a half-written or empty file, and a failed write leaves the earlier one."""
    import os

    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_report(path: Path, report: dict[str, Any]) -> None:
    """The report written whole or not at all (``write_text_whole``): the doctor never reads a half-written one."""
    write_text_whole(path, json.dumps(report, indent=1, ensure_ascii=False) + "\n")


def restart_line(report: dict[str, Any]) -> tuple[Literal["PASS", "WARN"], str]:
    """The doctor's word on the store's restart after a load that changed a system: WARN when it was not restarted
    (it may answer from the earlier version for minutes) or did not answer again; nothing when nothing changed."""
    systems = changed(report)
    if not systems:
        return "PASS", ""
    done = report.get("store_restart")
    if not isinstance(done, dict):
        return "WARN", (f"the FHIR store was not restarted after loading {', '.join(systems)}: it may answer from the "
                        "earlier version for minutes (deploy/terminology-update.sh restarts it)")  # fmt: skip
    if not done.get("answered"):
        return "WARN", (f"the FHIR store did not answer after its restart at {done.get('at')}: see "
                        "docker compose ps fhir-store")  # fmt: skip
    return "PASS", f"the FHIR store restarted at {done.get('at')} after the load ({done.get('seconds')} s)"


def check(report: dict[str, Any] | None, term_dir: Path) -> list[str]:
    """What the doctor says: the readers hold another release than the terminology now, or one was not loaded."""
    if report is None:
        return ["the code systems were never loaded into the vocabulary and the FHIR store: run the load step"]
    out = []
    now = manifest(term_dir)["release"]
    if report.get("release") != now:
        out.append(f"the terminology is release {now}, but the vocabulary and the FHIR store were loaded from "
                   f"{report.get('release')}: run the load step again")  # fmt: skip
    out += [f"{key}: {why}" for key, why, _ in skipped(report) if not key.startswith("fhir/")]
    return out


REPORT = "terminology-load.json"  # in the site folder, written by the installer's step
NEEDED = "needed.jsonl"  # in the site folder: what is still needed, for the U-5 page (U5-1 reads it)
NEXT = "deploy/terminology-update.sh"  # the one command that loads it later


def folder_lines(text: str) -> list[tuple[str, str, bool]]:
    """``(system, why, fault)`` of each system the hospital's folder did not load (``terminology_install folder``
    output): a missing one is not a fault, a refused one is (its files are there but did not pass)."""
    out = []
    for line in text.splitlines():
        label, _, rest = line.partition(": ")
        state, _, why = rest.partition(": ")
        if state in ("missing", "refused") and label:
            out.append((f"folder/{label}", f"{state}: {why}", state == "refused"))
    return out


def _ours(key: str, folder: bool) -> bool:
    """A line of ``needed.jsonl`` this run rewrites: this step's, and the folder's only when the folder was read."""
    return key.startswith("terminology/") and (folder or not key.startswith("terminology/folder/"))


def needed(site: Path, items: list[tuple[str, str, bool]], by: str = BY, folder: bool = True) -> None:
    """Rewrite this step's lines of ``site/needed.jsonl`` (``terminology/...``): one per system still needed, with
    why, whether it is a fault, and the command that loads it later; the other steps' lines stay. Standard library
    only (the host runs it). ``folder=False``: the hospital's folder was not read this time, so its lines stay."""
    from datetime import UTC, datetime

    path = site / NEEDED
    keep = [ln for ln in (path.read_text("utf-8").splitlines() if path.is_file() else [])
            if ln.strip() and not _ours(str(json.loads(ln).get("key", "")), folder)]  # fmt: skip
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = [json.dumps({"key": f"terminology/{k}", "what": f"code system {k.split('/', 1)[-1]} is not loaded",
                       "why": why, "fault": fault, "next": NEXT, "at": at, "by": by}, ensure_ascii=False)
           for k, why, fault in items]  # fmt: skip
    site.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{ln}\n" for ln in [*keep, *new]), encoding="utf-8")


def doctor_line(site: Path, term_dir: Path) -> tuple[Literal["PASS", "WARN", "FAIL"], str]:
    """``(status, detail)`` for the doctor: FAIL when the readers hold another release than the terminology now or
    a reader was not loaded; WARN when the folder cannot be read here; else each system's version in the FHIR store
    and the release. Nothing (``PASS`` and no text) when the step never ran: there is nothing to compare."""
    path = site / REPORT
    if not path.is_file():  # no step yet (a box installed before it): nothing to compare, the terminology check stands
        return "PASS", ""
    report = json.loads(path.read_text("utf-8"))
    loaded = [f"{r['key']} {r['detail'].split(' (')[0].split(' ')[-1]}" for r in report.get("fhir") or []
              if r.get("state") != "skipped"]  # fmt: skip
    said = f"release {report.get('release')}; in the FHIR store: {', '.join(loaded) or 'none'}"
    not_loaded = [k.split("/", 1)[-1] for k, _, _ in skipped(report) if k.startswith("fhir/")]
    said += f"; not loaded: {', '.join(not_loaded)}" if not_loaded else ""
    restart, why = restart_line(report)
    said += f"; {why}" if why else ""
    if not term_dir.is_dir():
        return "WARN", f"{said}; {term_dir} cannot be read here: the release was not compared"
    problems = check(report, term_dir)
    return ("FAIL", "; ".join(problems) + f" ({said})") if problems else (restart, said)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.terminology_load", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load", help="the one install step: the manifest into the vocabulary and the FHIR store")
    ld.add_argument("--terminology", default="", help="TB_TERMINOLOGY_DIR (default: the loader's own)")
    ld.add_argument("--fhir", default="", help="the FHIR store's base URL (default: the settings' fhir_base_url)")
    ld.add_argument("--deploy", default="", help="the deploy folder: each system not loaded is a line of poc-stops")
    ld.add_argument("--report", default="", help="write the run's report (JSON) here; '-' for standard output")
    ld.add_argument("--wait", type=float, default=900.0, help="seconds to wait for the FHIR store to store a system")
    sk = sub.add_parser("skipped", help="each system a report did not load, one 'key<TAB>why' line (the installer)")
    sk.add_argument("--report", required=True)
    sk.add_argument("--folder-log", default="", help="the hospital's folder step's output: its systems not loaded")
    sk.add_argument("--site", default="", help="also rewrite this step's lines of <site>/needed.jsonl (U-5)")
    sn = sub.add_parser("still-needed", help="this step's lines of <site>/needed.jsonl, one 'key<TAB>why' each")
    sn.add_argument("--site", required=True)
    sn.add_argument("--faults", action="store_true", help="only the faults: a system given but refused or not loaded")
    ch = sub.add_parser("changed", help="the systems a report loaded anew, one a line; exit 1 when none (V18-01)")
    ch.add_argument("--report", required=True)
    cy = sub.add_parser("carry", help="keep in a new report the systems an earlier load changed and no restart served")
    cy.add_argument("--old", required=True)
    cy.add_argument("--new", required=True)
    rs = sub.add_parser("restarted", help="record the FHIR store's restart after the load in the report")
    rs.add_argument("--report", required=True)
    rs.add_argument("--answered", choices=("yes", "no"), required=True)
    rs.add_argument("--seconds", type=int, default=0)
    ck = sub.add_parser("check", help="compare a report with the terminology as it is now (the doctor)")
    ck.add_argument("--report", required=True)
    ck.add_argument("--terminology", default="")
    a = p.parse_args(argv)
    if a.cmd == "still-needed":  # the standard library only: the installer lists the faults in poc-stops.jsonl
        path = Path(a.site) / NEEDED
        for ln in path.read_text("utf-8").splitlines() if path.is_file() else []:
            rec = json.loads(ln) if ln.strip() else {}
            if str(rec.get("key", "")).startswith("terminology/") and (rec.get("fault", True) or not a.faults):
                print(f"{rec['key'].split('/', 1)[1]}\t{' '.join(str(rec.get('why', '')).split())}")
        return 0
    if a.cmd == "carry":  # the standard library only: deploy/terminology-update.sh, on the host
        old, new = Path(a.old), Path(a.new)
        try:
            before = json.loads(old.read_text("utf-8")) if old.is_file() else None
        except ValueError:
            before = None  # an unreadable earlier report carries nothing
        write_report(new, carry(before, json.loads(new.read_text("utf-8"))))
        return 0
    if a.cmd in ("changed", "restarted"):  # the standard library only: deploy/terminology-update.sh, on the host
        rp = Path(a.report)
        rep = json.loads(rp.read_text("utf-8")) if rp.is_file() else {}
        if a.cmd == "changed":
            print("\n".join(changed(rep)))
            return 0 if changed(rep) else 1
        from datetime import UTC, datetime

        at = datetime.now(UTC).isoformat(timespec="seconds")
        write_report(rp, restarted(rep, a.answered == "yes", a.seconds, at))
        return 0
    if a.cmd == "skipped":  # the standard library only: the installer runs it on the host
        rp = Path(a.report)
        items = skipped(json.loads(rp.read_text("utf-8"))) if rp.is_file() else [("load", "the step did not run", True)]
        log = Path(a.folder_log) if a.folder_log else None
        items = (folder_lines(log.read_text("utf-8")) if log and log.is_file() else []) + items
        for key, why, _ in items:
            print(f"{key}\t{' '.join(why.split())}")
        if a.site:
            needed(Path(a.site), items, folder=bool(a.folder_log))
        return 0
    from criteria_compiler.terminology import installed as inst

    where = Path(a.terminology) if a.terminology else inst.installed_dir()
    if a.cmd == "check":
        path = Path(a.report)
        problems = check(json.loads(path.read_text("utf-8")) if path.is_file() else None, where)
        for line in problems:
            print(f"{BY}: {line}")
        return 1 if problems else 0
    from tb_common.config import load_env

    db = None
    try:
        from omop import schema

        db = schema.connect()
    except FAILED as exc:  # the vocabulary out of reach: said in the report, never a stop
        print(f"{BY}: warning: the vocabulary database could not be opened ({type(exc).__name__})", file=sys.stderr)
    try:
        report = run(where, a.fhir or load_env().fhir_base_url, db, a.wait)
    finally:
        if db is not None:
            db.close()
    for key, why, fault in skipped(report):
        print(f"{BY}: warning: {key} not loaded: {why}", file=sys.stderr)
        if a.deploy and fault:
            from tools.trialbox import stops

            stops.append(Path(a.deploy), f"{BY}/{key}", f"code system {key} not loaded", why, by=BY)
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if a.report == "-":
        print(text)
    elif a.report:
        Path(a.report).write_text(text + "\n", encoding="utf-8")
    print(f"{BY}: release {report['release']}: {sum(r.get('state') != 'skipped' for r in report['fhir'])} systems in "
          f"the FHIR store, {len(report['omop'])} releases in the vocabulary", file=sys.stderr)  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
