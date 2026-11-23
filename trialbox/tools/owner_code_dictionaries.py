"""The mapping check on a hospital's own code dictionaries, on its own machine; only a summary leaves (lane M).

    python tools/owner_code_dictionaries.py --config tables.json --out summary.json
    python tools/owner_code_dictionaries.py --table diagnosis:icd-10-cm:dx.csv:ICD_CODE,DX_NAME --out summary.json

Run it **only on the machine that holds the dictionaries**, from a checkout of this repository (``make venv`` once).
It reads code dictionaries (the lab-item, order, department, diagnosis and drug code tables): one row per code, never a
patient. It runs ``tools.mapping_coverage`` on them and writes ``--out``: counts by domain and route, the unmapped
codes with their dictionary names, and how many of each ruleset value set's codes the dictionaries reach. Nothing
else: no file path, no row of a file that was refused, no value of any column but the code and its name.

**Refused** (exit 2, nothing written) when a file

* has a column whose header names a patient identifier or a person's details (chart number, patient id, national
  id, name of a patient, birth date, telephone, address: :data:`PATIENT_HEADERS`, in English, Japanese and
  Traditional Chinese);
* has a cell shaped like a Taiwanese national identity number (letter, 1 or 2, eight digits, check digit valid);
* repeats its codes (more than a fifth of its rows carry a code an earlier row has): that is a table of events, not a
  dictionary.

The refusal names the file's position in the list, the column header or the line number, never a cell's value.

A table is ``kind:system:file[:code_column,name_column[,target_column]]``. ``kind`` is ``diagnosis``, ``lab``,
``drug``, ``order`` or ``department`` (a check that the system belongs to it); ``system`` one of
``tools.mapping_coverage.SYSTEMS``; the columns default to ``local_code`` and ``local_name``. A ``--config`` JSON file
holds the same as ``{"tables": [{"kind", "system", "file", "code", "name", "target"}], "lab_lookup", "jlac10",
"byomei", "yj", "ingredient_atc", "nhi_drug", "who_icd10cm", "department_table"}`` (the eight optional cross-walks
of the site, each a path). Files are CSV or tab-separated, UTF-8, Big5 (cp950) or Shift_JIS (cp932), detected.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import mapping_coverage as mc  # noqa: E402

KINDS = {"diagnosis": "diagnosis", "lab": "lab", "drug": "medication", "order": "procedure", "department": "department"}
ENCODINGS = ("utf-8-sig", "cp950", "cp932")
REPEAT_LIMIT = 0.2

#: header words (normalised: NFKC, lower case, no blank, ``_`` or ``-``) that name a patient identifier or a person's
#: details. A header containing one of the long forms, or equal to one of the short ones, refuses the file.
PATIENT_HEADERS = (
    "mrn", "chartno", "chartnumber", "medicalrecord", "patientid", "patid", "patientno", "patientnumber",
    "patientname", "personid", "subjectid", "nationalid", "idno", "idnumber", "nhicard", "insuranceno",
    "insurednumber", "birth", "telephone", "phone", "mobile", "address", "email",
    "病歷號", "病歷", "病患", "病人", "身分證", "身份證", "姓名", "生日", "出生", "電話", "地址", "住址",
    "患者id", "患者番号", "患者コード", "患者氏名", "カルテ番号", "カルテno", "氏名", "生年月日", "住所", "電話番号",
    "保険者番号", "被保険者",
)  # fmt: skip
SHORT_HEADERS = ("pid", "dob", "tel", "sex", "gender")
_TW_ID = re.compile(r"^[A-Z][12][0-9]{8}$")
_TW_LETTER = "ABCDEFGHJKLMNPQRSTUVXYWZIO"  # the letter's value is its position + 10


def tw_id_valid(s: str) -> bool:
    """A Taiwanese national identity number with a valid check digit."""
    if not _TW_ID.match(s):
        return False
    n = _TW_LETTER.index(s[0]) + 10
    digits = [n // 10, n % 10, *(int(c) for c in s[1:])]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(d * w for d, w in zip(digits, weights, strict=True)) % 10 == 0


def _norm(h: str) -> str:
    return re.sub(r"[\s_\-]", "", unicodedata.normalize("NFKC", h or "").lower())


def patient_header(header: str) -> bool:
    h = _norm(header)
    return h in SHORT_HEADERS or any(w in h for w in PATIENT_HEADERS)


class Refused(Exception):
    """A file the check will not read; the message holds no cell value."""


@dataclass
class Table:
    kind: str
    system: str
    file: Path
    code: str = "local_code"
    name: str = "local_name"
    target: str = ""


def parse_table(spec: str) -> Table:
    parts = spec.split(":", 3)
    if len(parts) < 3:
        raise ValueError(f"--table wants kind:system:file[:code,name[,target]], got {len(parts)} part(s)")
    kind, system, file = parts[0], parts[1], parts[2]
    cols = parts[3].split(",") if len(parts) == 4 else []
    return Table(kind, system, Path(file), *(c.strip() for c in cols[:3]))


def decode(data: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise Refused("not UTF-8, Big5 or Shift_JIS")


def read_table(t: Table, label: str) -> list[dict[str, str]]:
    """The table's rows as the check's list rows; :class:`Refused` before any row is used when the file is not a
    dictionary."""
    if t.kind not in KINDS:
        raise Refused(f"{label}: kind must be one of {', '.join(KINDS)}")
    if t.system not in mc.SYSTEMS or mc.SYSTEMS[t.system][0] != KINDS[t.kind]:
        raise Refused(f"{label}: system {t.system!r} is not a {t.kind} code system of tools.mapping_coverage")
    text = decode(t.file.read_bytes())
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = next(reader, [])
    for i, h in enumerate(header, 1):
        if patient_header(h):
            raise Refused(f"{label}: column {i} ({h.strip()!r}) names a patient identifier or a person's details")
    index = {h.strip(): i for i, h in enumerate(header)}
    for col in (t.code, t.name, t.target):
        if col and col not in index:
            raise Refused(f"{label}: no column {col!r}")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    repeats = 0
    for line, cells in enumerate(reader, 2):
        for c in cells:
            if tw_id_valid(c.strip().upper()):
                raise Refused(f"{label}: line {line} holds a value shaped like a national identity number")
        if not any(c.strip() for c in cells):
            continue

        def cell(col: str, cells: list[str] = cells) -> str:
            return cells[index[col]].strip() if col and index[col] < len(cells) else ""

        code = cell(t.code)
        repeats += code in seen
        seen.add(code)
        rows.append({"local_code": code, "local_name": cell(t.name), "system": t.system, "target_code": cell(t.target)})
    if rows and repeats > REPEAT_LIMIT * len(rows):
        raise Refused(f"{label}: {repeats} of {len(rows)} rows repeat a code: a table of events, not a dictionary")
    return rows


def summary(tables: list[Table], ref: mc.Reference) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    files = []
    for n, t in enumerate(tables, 1):
        label = f"table {n} ({t.kind}, {t.system})"
        got = read_table(t, label)
        files.append({"table": n, "kind": t.kind, "system": t.system, "codes": len(got)})
        rows += got
    report = mc.coverage(rows, ref)
    return {
        "format": "tb-mapping-coverage-summary/1",
        "tables": files,
        "codes": report["codes"],
        "mapped": report["mapped"],
        "by_domain": report["by_domain"],
        "unmapped": report["unmapped"],
        "valuesets": [
            {k: v[k] for k in ("ruleset", "valueset", "domain", "systems", "site_codes", "list_given", "criteria")}
            for v in report["valuesets"]
        ],
        "valuesets_reached": report["valuesets_reached"],
        "valuesets_not_reached": report["valuesets_not_reached"],
        "references": {k: Path(v).name if not v.startswith("services/") else v for k, v in ref.sources.items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/owner_code_dictionaries.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, help="JSON file naming the tables and the site's cross-walks")
    ap.add_argument("--table", action="append", default=[], help="kind:system:file[:code,name[,target]]")
    ap.add_argument("--out", type=Path, required=True, help="the summary JSON (the only file written)")
    a = ap.parse_args(argv)
    tables = [parse_table(s) for s in a.table]
    xwalk: dict[str, Path | None] = dict.fromkeys(
        ("lab_lookup", "jlac10", "byomei", "yj", "ingredient_atc", "nhi_drug", "who_icd10cm", "department_table")
    )
    if a.config:
        cfg = json.loads(a.config.read_text(encoding="utf-8"))
        base = a.config.parent
        for t in cfg.get("tables") or []:
            tables.append(
                Table(
                    t["kind"],
                    t["system"],
                    base / t["file"],
                    t.get("code", "local_code"),
                    t.get("name", "local_name"),
                    t.get("target", ""),
                )
            )
        for k in xwalk:
            if cfg.get(k):
                xwalk[k] = base / cfg[k]
    if not tables:
        ap.error("give --table or --config")
    try:
        ref = mc.Reference.load(*xwalk.values())
        out = summary(tables, ref)
    except Refused as exc:
        print(f"refused, nothing written: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"refused, nothing written: a file could not be read ({exc.strerror})", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        mc.render({**out, "valuesets_without_list": []}, "Mapping coverage of the hospital's dictionaries")
    )  # same as the file
    print(f"summary written: {a.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
