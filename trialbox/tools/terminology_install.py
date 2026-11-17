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
    python -m tools.terminology_install atc <ATC index csv or tsv> --accepted-by "NAME" --version YEAR

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology import installed  # noqa: E402


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
    rm = sub.add_parser("remove-site-list", help="remove one of the site's own lists on purpose (audited)")
    rm.add_argument("--name", required=True, help="the list's name: the table is site_<name>")
    rm.add_argument("--by", required=True, help="who removes it (the audit's actor)")
    rm.add_argument("--audit-dir", type=Path, default=None, help="the audit folder (default: TB_AUDIT_DIR)")
    rm.add_argument("--dir", type=Path, default=None)
    args = ap.parse_args(argv)
    where = args.dir or installed.installed_dir()
    if args.cmd == "remove-site-list":
        return _remove(args, where)
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
    pcs = sub.add_parser("icd10pcs", help="ICD-10-PCS from CMS's code-files zip, or its order or codes text file")
    pcs.add_argument("file", type=Path)
    pcs.add_argument("--year", default="2026")
    pcs.add_argument("--dir", type=Path, default=None)
    for cmd, what in (("loinc", "LOINC from the site's own Regenstrief download (zip or Loinc.csv)"),
                      ("icd10who", "WHO ICD-10 from the site's own licensed copy (ClaML, or a code and title table)"),
                      ("atc", "the ATC index from the site's own copy (CSV or TSV)")):  # fmt: skip
        p = sub.add_parser(cmd, help=what)
        p.add_argument("file", type=Path)
        p.add_argument("--accepted-by", required=True, help="the named person who accepted the licence (D-1114)")
        p.add_argument("--accepted-on", default="", help="the day it was accepted, YYYY-MM-DD (default: today)")
        p.add_argument("--version", default="")
        p.add_argument("--dir", type=Path, default=None)
    site.add_argument("--version", default="")
    site.add_argument("--dir", type=Path, default=None)


def _load(args: argparse.Namespace, where: Path) -> dict[str, int]:
    if args.cmd == "site-list":
        return installed.install_site_list(args.file, where, args.name, args.system, args.version)
    if args.cmd == "nhi-drugs":
        return installed.install_nhi_drugs(args.file, where, args.version)
    if args.cmd == "nhi-services":
        return installed.install_nhi_services(args.file, where, args.version)
    if args.cmd == "icd10pcs":
        return installed.install_icd10pcs(args.file, where, args.year)
    loader = {"loinc": installed.install_loinc, "icd10who": installed.install_icd10_who, "atc": installed.install_atc}
    return loader[args.cmd](args.file, where, args.accepted_by, args.accepted_on, args.version)


if __name__ == "__main__":
    raise SystemExit(main())
