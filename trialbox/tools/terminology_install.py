"""Load code systems onto the box (D-1028; TERM-1, D-858): ``python -m tools.terminology_install``.

A code system that may not be committed (D-1028 as amended by D-1029) is supplied by the site or the vendor and this
command loads it into ``TB_TERMINOLOGY_DIR`` (default ``/data/terminology``), each table
with its manifest line (source, version, licence note, sha256). ``trialbox doctor`` reports what is loaded.

    python -m tools.terminology_install icd10cm <CMS code-tables zip> [--year 2026] [--dir DIR]
    python -m tools.terminology_install status [--dir DIR]

TERM-2 (D-1113 to D-1116), in the order of the install step (``docs/handover/OFFLINE-MEDIA.md``):

    python -m tools.terminology_install site-list <csv or tsv> --name NAME [--system S] [--version V] [--dir DIR]
    python -m tools.terminology_install nhi-drugs <健保用藥品項 csv> [--version V] [--dir DIR]
    python -m tools.terminology_install nhi-services <醫療服務給付項目 csv> [--version V] [--dir DIR]
    python -m tools.terminology_install icd10pcs <CMS ICD-10-PCS zip or order/codes txt> [--year 2026] [--dir DIR]
    python -m tools.terminology_install loinc <Regenstrief zip or Loinc.csv> --accepted-by "NAME" [--accepted-on D]
    python -m tools.terminology_install icd10who <ClaML xml or code table> --accepted-by "NAME" [--version V]
    python -m tools.terminology_install atc <ATC/DDD index xlsx, csv or tsv> --accepted-by "NAME" --version YEAR

V-18 (D-1182): SNOMED CT and the UMLS from the hospital's own copy, and every system of the hospital's folder at once
(the layout: ``docs/handover/terminology-folder.md``); a system missing or refused is said, never a stop:

    python -m tools.terminology_install snomed <RF2 Snapshot folder or zip> --accepted-by "NAME" [--sha256 S]
    python -m tools.terminology_install umls <RRF subset folder or zip> --accepted-by "NAME" [--version 2025AB]
    python -m tools.terminology_install folder <the hospital's folder> [--accepted-by "NAME"]

H-17 (D-1127): the NHI open data as it ships in the image (D-1028 point 3), built by the integrator from the files
it fetched (``docs/licences/nhi-open-data-fetch.md``), and checked:

    python -m tools.terminology_install nhi-build drugs|services <csv> --version V --fetched-on D --sha256 S
    python -m tools.terminology_install nhi-check [--dir DIR]

``nhi-drugs``, ``nhi-services`` and ``nhi-build`` take ``--column OURS=THEIRS`` (repeatable) when the publisher
renamed a column the loader reads.

E-TERM-3 (D-1048): a site list removed on purpose (its file and its manifest line; a list whose file is gone while its
line stays is refused, and while a site list is refused no ruleset is approved). The removal is in the hash-chained
audit (``terminology.remove``); without an audit folder it is refused:

    python -m tools.terminology_install remove-site-list --name NAME --by "WHO" [--audit-dir DIR] [--dir DIR]

``icd10cm``: CMS's ``<year>-code-tables-tabular-and-index.zip`` (US public domain; cms.gov, "ICD-10-CM" files),
read without unpacking: its tabular list's blocks and its Alphabetic Index. The FY2026 tables ship in the image
(D-1029); this loads a later release in their place.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology import installed  # noqa: E402

if TYPE_CHECKING:
    from tools import licence_register


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    icd = sub.add_parser("icd10cm", help="ICD-10-CM's blocks and Alphabetic Index from CMS's code-tables zip")
    icd.add_argument("zip", type=Path)
    icd.add_argument("--year", default="2026")
    icd.add_argument("--dir", type=Path, default=None)
    st = sub.add_parser("status", help="what is loaded, and what is refused")
    st.add_argument("--dir", type=Path, default=None)
    _term2(sub)
    _h17(sub)
    rm = sub.add_parser("remove-site-list", help="remove one of the site's own lists on purpose (audited)")
    rm.add_argument("--name", required=True, help="the list's name: the table is site_<name>")
    rm.add_argument("--by", required=True, help="who removes it (the audit's actor)")
    rm.add_argument("--audit-dir", type=Path, default=None, help="the audit folder (default: TB_AUDIT_DIR)")
    rm.add_argument("--dir", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.cmd in ("nhi-build", "nhi-check"):
        return _shipped(args)
    where = args.dir or installed.installed_dir()
    if args.cmd == "remove-site-list":
        return _remove(args, where)
    if args.cmd == "folder":  # V-18: never a stop; each system says what happened
        for label, (state, said) in installed.install_folder(args.folder, where, args.accepted_by,
                                                             args.accepted_on).items():  # fmt: skip
            print(f"{label}: {state}: {said}", file=sys.stdout if state == "loaded" else sys.stderr)
        return 0
    if args.cmd == "icd10cm":
        for name, n in installed.install_icd10cm(args.zip, where, args.year).items():
            print(f"{name}: {n} rows loaded into {where}")
        return 0
    if args.cmd != "status":
        try:
            got = _load(args, where)
        except (ValueError, OSError, installed.TerminologyRefused) as exc:
            print(f"terminology_install {args.cmd}: refused: {exc}", file=sys.stderr)
            return 2
        for name, n in got.items():
            print(f"{name}: {n} rows loaded into {where}")
        return 0
    bad = 0
    for t in installed.status(where):
        said = installed.accepted(where, t.name) if not t.problem else ""
        print(f"{t.name}: {'REFUSED: ' + t.problem if t.problem else f'{t.rows} rows, {t.version}'}"
              + (f", {said}" if said else ""))  # fmt: skip
        bad += bool(t.problem)
    return 1 if bad else 0


def _remove(args: argparse.Namespace, where: Path) -> int:
    """E-TERM-3 (D-1048): the removal is audited, or it does not happen."""
    import os

    from tb_common.audit_writer import open_audit
    from tb_common.config import site_tz

    adir = args.audit_dir or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
    if adir is None or not args.by.strip():
        print("terminology_install remove-site-list: refused: name an audit folder (--audit-dir or TB_AUDIT_DIR) "
              "and who removes it (--by); a removal is audited", file=sys.stderr)  # fmt: skip
        return 2
    audit = open_audit(adir, site_tz())  # opened first: a removal the audit cannot take does not happen
    try:
        gone = installed.remove_site_list(where, args.name)
    except (ValueError, OSError, installed.TerminologyRefused) as exc:
        print(f"terminology_install remove-site-list: refused: {exc}", file=sys.stderr)
        return 2
    audit.append("terminology.remove", actor=args.by.strip(), output_sha=gone.get("sha256") or None,
                 detail={**gone, "dir": str(where)})  # fmt: skip
    print(f"{gone['table']}: removed from {where}")
    return 0


def _term2(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """TERM-2's subcommands (D-1113 to D-1116), beside TERM-1's."""
    site = sub.add_parser("site-list", help="one of the site's own code lists (local code or name -> standard code)")
    site.add_argument("file", type=Path)
    site.add_argument("--name", required=True, help="the list's name: the table is site_<name>")
    site.add_argument(
        "--system", default="", help=f"one system for the whole file: {', '.join(installed.SITE_SYSTEMS)}"
    )
    for cmd, what in (("nhi-drugs", "the NHI drug list 健保用藥品項查詢項目檔 (data.gov.tw 23715), its CSV"),
                      ("nhi-services", "the NHI service and order codes (data.gov.tw 174450), its CSV")):  # fmt: skip
        p = sub.add_parser(cmd, help=what)
        p.add_argument("file", type=Path)
        p.add_argument("--version", default="")
        p.add_argument("--dir", type=Path, default=None)
        _column_option(p)
    pcs = sub.add_parser("icd10pcs", help="ICD-10-PCS from CMS's code-files zip, or its order or codes text file")
    pcs.add_argument("file", type=Path)
    pcs.add_argument("--year", default="2026")
    pcs.add_argument("--dir", type=Path, default=None)
    for cmd, what in (("loinc", "LOINC from the site's own Regenstrief download (zip or Loinc.csv)"),
                      ("icd10who", "WHO ICD-10 from the site's own licensed copy (ClaML, or a code and title table)"),
                      ("atc", "the ATC/DDD index from the site's own copy (xlsx, CSV or TSV)"),
                      ("snomed", "SNOMED CT from the site's own RF2 Snapshot (folder or zip; V-18)"),
                      ("umls", "the UMLS from the site's own RRF subset (folder or zip; V-18)")):  # fmt: skip
        p = sub.add_parser(cmd, help=what)
        p.add_argument("file", type=Path)
        p.add_argument("--accepted-by", required=True, help="the named person who accepted the licence (D-1114)")
        p.add_argument("--accepted-on", default="", help="the day it was accepted, YYYY-MM-DD (default: today)")
        p.add_argument("--version", default="")
        p.add_argument("--dir", type=Path, default=None)
        if cmd in ("atc", "snomed", "umls"):
            p.add_argument("--sha256", default="", help="the archive's sha256 as the person recorded it (V-18)")
    fo = sub.add_parser("folder", help="every system in the hospital's folder, one subfolder each (V-18)")
    fo.add_argument("folder", type=Path)
    fo.add_argument("--accepted-by", default="", help="the named person (default: the folder's acceptance.json)")
    fo.add_argument("--accepted-on", default="")
    fo.add_argument("--dir", type=Path, default=None)
    site.add_argument("--version", default="")
    site.add_argument("--dir", type=Path, default=None)


def _load(args: argparse.Namespace, where: Path) -> dict[str, int]:
    if args.cmd == "site-list":
        return installed.install_site_list(args.file, where, args.name, args.system, args.version)
    if args.cmd == "nhi-drugs":
        return installed.install_nhi_drugs(args.file, where, args.version, columns=_columns(args.column))
    if args.cmd == "nhi-services":
        return installed.install_nhi_services(args.file, where, args.version, columns=_columns(args.column))
    if args.cmd == "icd10pcs":
        return installed.install_icd10pcs(args.file, where, args.year)
    if args.cmd in ("atc", "snomed", "umls"):  # V-18: the site's copies, xlsx too, verified when they can be
        copies = {
            "atc": installed.install_atc_index,
            "snomed": installed.install_snomed,
            "umls": installed.install_umls,
        }
        return copies[args.cmd](args.file, where, args.accepted_by, args.accepted_on, args.version, args.sha256)
    loader = {"loinc": installed.install_loinc, "icd10who": installed.install_icd10_who}
    return loader[args.cmd](args.file, where, args.accepted_by, args.accepted_on, args.version)


# ------------------------------------------------------------------------ H-17 (D-1127): the NHI open data shipped
def _column_option(p: argparse.ArgumentParser) -> None:
    what = "the header the publisher now uses for a column the loader reads, e.g. ATC代碼=ATC CODE"
    p.add_argument("--column", action="append", default=[], metavar="OURS=THEIRS", help=what)


def _columns(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        ours, sep, theirs = pair.partition("=")
        if not sep or not ours.strip() or not theirs.strip():
            raise ValueError(f"--column {pair!r}: write it OURS=THEIRS, e.g. ATC代碼=ATC CODE")
        out[ours.strip()] = theirs.strip()
    return out


def _h17(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    b = sub.add_parser("nhi-build", help="build the shipped NHI table from the publisher's file the integrator fetched")
    b.add_argument("kind", choices=("drugs", "services"))
    b.add_argument("file", type=Path)
    b.add_argument("--version", required=True, help="the publisher's version: the data set's file update time")
    b.add_argument("--fetched-on", required=True, help="the day the file was fetched, YYYY-MM-DD")
    b.add_argument("--sha256", required=True, help="the file's sha256 as recorded at the fetch")
    b.add_argument("--out", type=Path, default=None, help="default: the shipped folder beside the mapper")
    _column_option(b)
    c = sub.add_parser("nhi-check", help="check the shipped NHI tables: manifest, attribution, licence-register row")
    c.add_argument("--dir", type=Path, default=None)


def _shipped(args: argparse.Namespace) -> int:
    from tools import licence_register  # the register is read only by nhi-check

    where = args.out if args.cmd == "nhi-build" else args.dir
    where = where or installed.SHIPPED_DIR
    if args.cmd == "nhi-build":
        table = installed.NHI_DRUGS if args.kind == "drugs" else installed.NHI_SERVICES
        try:
            got = installed.build_shipped(table, args.file, args.version, args.fetched_on, args.sha256, where,
                                          _columns(args.column))  # fmt: skip
        except (ValueError, OSError, installed.TerminologyRefused) as exc:
            print(f"terminology_install nhi-build: refused: {exc}", file=sys.stderr)
            return 2
        line = installed.manifest(where)["tables"][table]
        print(f"{table}: {got[table]} rows built into {where}, sha256 {line['sha256']}")
        print(f"attribution: {line['ogdl_statement']}")
        return 0
    problems = installed.shipped_problems(where)
    lines = installed.manifest(where)["tables"] if where.is_dir() and not problems else {}
    problems += register_problems(where, lines, licence_register.load())
    if where.resolve() == installed.SHIPPED_DIR.resolve():  # the image's own folder: NOTICE must name it
        problems += notice_problems(lines, (ROOT / "NOTICE").read_text(encoding="utf-8"))
    for name, line in sorted(lines.items()):
        print(f"{name}: {line.get('rows')} rows, {line.get('version')}, sha256 {str(line.get('sha256'))[:16]}, "
              f"from {str(line.get('source_sha256'))[:16]} fetched {line.get('fetched_on')}")  # fmt: skip
    for p in problems:
        print(f"PROBLEM: {p}")
    if not lines and not problems:
        print(f"no NHI table ships ({where} holds none): the box loads them at install (D-1115)")
    return 1 if problems else 0


# H-17 review (D-1127): the line NOTICE's section 8 (shipped vocabulary folders) needs once an NHI table ships; the
# attribution of each shipped table must be in NOTICE too (both are there today, for the samples)
NOTICE_FOLDER_LINE = (
    "  services/criteria_compiler/terminology/shipped/  NHI drug list and service codes, full lists (section 1)"
)


def notice_problems(lines: Mapping[str, Any], notice: str) -> list[str]:
    """What NOTICE lacks for the shipped tables ``lines``: the folder line, and each table's attribution (compared
    with NOTICE's line breaks and indents read as one space)."""
    if not lines:
        return []
    flat = " ".join(notice.split())
    out = []
    if not any(line.split()[:1] == NOTICE_FOLDER_LINE.split()[:1] for line in notice.splitlines()):
        out.append("NOTICE section 8 lacks the line: " + NOTICE_FOLDER_LINE.strip())
    for name in sorted(lines):
        if installed.SHIPPABLE[name] not in flat:
            out.append(f"NOTICE lacks the attribution of {name}: {installed.SHIPPABLE[name]}")
    return out


def register_problems(where: Path, lines: Mapping[str, Any], rows: list[licence_register.Row]) -> list[str]:
    """Each shipped table and the shipped manifest need a ``cleared`` licence-register row naming them (D-1028
    point 3, D-1127)."""
    from tools import licence_register

    try:
        rel = where.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return []  # a folder outside the tree (a test's) is not shipped
    out = []
    for f in [f"{rel}/{n}.parquet" for n in sorted(lines)] + ([f"{rel}/manifest.json"] if lines else []):
        hit = [r for r in rows if any(licence_register._matches(p, f) for p in r.paths)]
        if not any(r.status == "cleared" and r.spdx == "LicenseRef-OGDL-Taiwan-1.0" for r in hit):
            out.append(f"{f}: no cleared OGDL row in docs/licences/register.csv names it (row nhi-open-data-full)")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
