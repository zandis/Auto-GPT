"""TERM-2 guard (D-1116, D-1028 point 2 and 4): LOINC, WHO ICD-10, ATC and the site's own code lists are loaded at
install and never committed, not even as test fixtures.

* The places the site's IT stages them (``deploy/site/terminology/``) and a loaded folder inside the tree
  (``data/terminology/``) are ignored by git and by the image's build context, and no tracked file sits there.
* No tracked file is named like a table the loader writes for them, or is a manifest naming a licence acceptance.
* No tracked data file looks like one of them: LOINC's table (its ``LOINC_NUM`` and ``LONG_COMMON_NAME`` columns), a
  WHO ClaML file, the WHOCC's ATC index (``ATC level name``, or its DDD columns), or a site list in the loader's format
  (``local_code`` or ``local_name`` beside ``code``, and no other columns than ``system`` and ``display``; the
  adapter's demo maps of ``services/adapter/mapping``, TrialBox's own work, carry unit and profile columns). The detector is shown each kind first, so a test that finds nothing proves something.

The small curated LOINC and ATC rows the rulesets use (rows ``loinc`` and ``atc`` of the licence register, shipped
before D-1028) have neither shape."""

from __future__ import annotations

import gzip
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed

from tools import licence_register as lr

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           check=True).stdout.strip())  # fmt: skip
STAGE = ("deploy/site/terminology", "data/terminology")
LOADED_NAMES = {f"{t}.parquet" for t in (installed.LOINC_TABLE, installed.ICD10_WHO, installed.ATC_INDEX)}
DATA = (".csv", ".tsv", ".txt", ".xml", ".json", ".parquet", ".gz", ".zip", ".xlsx")
# a site-list-shaped file the licence register accounts for as TrialBox's own, synthetic or cleared data (the
# adapter's demo maps) is not a site's list; a site's list has no such row (its row is ``site-loaded``, no paths)
ACCOUNTED = frozenset({"own-work", "synthetic", "cleared"})


def _tracked() -> list[str]:
    """Every tracked file of the repository, from its root (TERM-2 review: not ``trialbox/`` only)."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _head(path: Path, n: int = 8192) -> bytes:
    with path.open("rb") as f:
        return f.read(n)


def _text(head: bytes) -> str:
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 with its BOM
        return head.decode("utf-16", "replace")
    return head.decode("utf-8", "replace").lstrip("\ufeff")


def _columns(text: str) -> set[str]:
    first = text.splitlines()[0].lower().replace('"', "") if text.strip() else ""
    return {c.strip() for c in re.split(r"[,\t;|]", first)}


def looks_like(name: str, head: bytes) -> str:
    """The kind of install-only table a file looks like (``loinc``, ``who-icd10``, ``atc-index``, ``site-list``,
    ``manifest``, ``loaded-table``), or ``""``. A zip or an xlsx is looked into: its members' names and heads."""
    low = name.lower()
    if low.endswith(".parquet"):
        return "loaded-table" if Path(low).name in LOADED_NAMES or Path(low).name.startswith("site_") else ""
    if low.endswith((".zip", ".xlsx")) or head.startswith(b"PK\x03\x04"):
        return _in_zip(head)
    if low.endswith(".gz") or head.startswith(b"\x1f\x8b"):
        try:
            return looks_like(low.removesuffix(".gz"), gzip.decompress(head)[:8192])
        except (OSError, EOFError):
            with gzip.GzipFile(fileobj=io.BytesIO(head)) as f:
                return looks_like(low.removesuffix(".gz"), f.read(8192))
    text = _text(head)
    cols = _columns(text)
    if "loinc_num" in cols:
        return "loinc"
    if "<claml" in text.lower():
        return "who-icd10"
    if low.endswith(".xml"):  # an xlsx keeps its header cells in xl/sharedStrings.xml
        words = text.lower()
        if "loinc_num" in words:
            return "loinc"
        if "atc level name" in words:
            return "atc-index"
    if "atc level name" in cols or "atc code" in cols or {"ddd", "adm.r"} <= cols:
        return "atc-index"
    if ({"local_code", "local_name"} & cols) and "code" in cols:
        return "site-list"
    if low.endswith(".json") and '"licence_accepted_by"' in text:
        return "manifest"
    return ""


def _in_zip(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ""
    with z:
        for member in z.namelist():
            m = member.lower()
            if m.endswith(("loinc.csv", "loinctablecore.csv")):
                return "loinc"
            if m.endswith((".csv", ".tsv", ".txt", ".xml", ".json", ".gz")):
                with z.open(member) as f:
                    kind = looks_like(m, f.read(65536))
                if kind:
                    return kind
    return ""


def _accounted(rel: str, rows: list[lr.Row]) -> bool:
    inner = rel.removeprefix("trialbox/")
    return any(r.status in ACCOUNTED and any(lr._matches(p, inner) for p in r.paths) for r in rows)


@pytest.mark.parametrize(("name", "head", "kind"), [
    ("x/Loinc.csv", b'"LOINC_NUM","COMPONENT","LONG_COMMON_NAME"\n"99990-1","x","y"\n', "loinc"),
    ("x/icd102019en.xml", b'<?xml version="1.0"?>\n<!DOCTYPE ClaML SYSTEM "ClaML.dtd">\n<ClaML version="2.0.0">', "who-icd10"),
    ("x/atc.tsv", b"ATC code\tATC level name\tDDD\tU\tAdm.R\tNote\n", "atc-index"),
    ("x/dx_local.csv", b"local_code,local_name,system,code\nZZ1,x,icd10cm,I10\n", "site-list"),
    ("x/manifest.json", b'{"tables": {"loinc_table": {"licence_accepted_by": "someone"}}}', "manifest"),
    ("x/loinc_table.parquet", b"PAR1", "loaded-table"),
    ("x/site_dx.parquet", b"PAR1", "loaded-table"),
    ("x/loinc_tw.csv", b"code,display,display_zh,unit,component_of,system\n", ""),
    ("x/lab_local_to_loinc.csv", b"local_code,system,code,display,ucum,factor,category,value_type,profile\n",
     "site-list"),  # site-list-shaped: the scan lets it pass only through its licence-register row (own work)
    ("x/atc.csv", b"code,display\nM04AA01,allopurinol\n", ""),
    ("x/LoincTableCore.csv", b"LOINC_NUM\n99990-1\n", "loinc"),  # the LOINC column alone
    ("x/atc;.csv", b"ATC code;ATC level name\nZ99AA01;x\n", "atc-index"),  # semicolon-separated
    ("x/u16.csv", "local_name\tcode\nx\tI10\n".encode("utf-16"), "site-list"),  # UTF-16 with its BOM
    ("x/more.csv", b"local_code,local_name,code,unit,note\nZZ1,x,I10,,\n", "site-list"),  # extra columns too
    ("x/claml.xml.gz", gzip.compress(b'<?xml version="1.0"?><ClaML version="2.0.0">'), "who-icd10"),
])  # fmt: skip
def test_the_detector_knows_each_kind(name: str, head: bytes, kind: str) -> None:
    assert looks_like(name, head) == kind


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    return buf.getvalue()


@pytest.mark.parametrize(("members", "kind"), [
    ({"LoincTable/Loinc.csv": b"x"}, "loinc"),
    ({"icd102019en.xml": b'<?xml version="1.0"?>\n<ClaML version="2.0.0">'}, "who-icd10"),
    ({"xl/sharedStrings.xml": b"<sst><si><t>ATC code</t></si><si><t>ATC level name</t></si></sst>"}, "atc-index"),
    ({"xl/sharedStrings.xml": b"<sst><si><t>LOINC_NUM</t></si></sst>"}, "loinc"),
    ({"readme.txt": b"hello"}, ""),
])  # fmt: skip
def test_the_detector_looks_into_a_zip_or_an_xlsx(members: dict[str, bytes], kind: str) -> None:
    assert looks_like("x/media.zip", _zip(members)) == kind


def test_the_staging_folders_are_ignored_and_hold_no_tracked_file() -> None:
    for d in STAGE:
        for f in ("Loinc.csv", "icd102019en.xml", "atc.tsv", "site_dx.parquet", "manifest.json"):
            r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", f"{d}/{f}"], check=False)
            assert r.returncode == 0, f"{d}/{f} is not ignored by git"
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", *STAGE], capture_output=True, text=True,
                             check=True).stdout.split()  # fmt: skip
    assert tracked == []
    ignored = {line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    assert {"deploy/site", "data"} <= ignored  # never in the image's build context either


def test_no_tracked_file_is_an_install_only_table() -> None:
    rows = lr.load()
    found = []
    for rel in _tracked():
        p = REPO / rel
        if not rel.lower().endswith(DATA) or not p.is_file() or p.is_symlink():
            continue
        whole = rel.lower().endswith((".zip", ".xlsx", ".gz"))
        kind = looks_like(rel, b"" if rel.endswith(".parquet") else (p.read_bytes() if whole else _head(p)))
        if kind == "site-list" and _accounted(rel, rows):
            continue
        if kind:
            found.append(f"{rel}: {kind}")
    assert found == [], "install-only code-system data is tracked (D-1116): " + "; ".join(found)


def test_the_scan_reads_the_whole_repository() -> None:
    files = _tracked()
    assert any(f.startswith("trialbox/") for f in files) and any(not f.startswith("trialbox/") for f in files)


def test_the_loader_writes_its_tables_where_the_guard_looks(tmp_path: Path) -> None:
    """The loader's own output, written into a folder named as on the box, is caught by the detector."""
    where = tmp_path / "data/terminology"
    src = tmp_path / "s.csv"
    src.write_text("local_code,local_name,system,code\nZZ1,SYNTHETIC name,icd10cm,I10\n", encoding="utf-8")
    installed.install_site_list(src, where, "dx")
    assert looks_like("data/terminology/site_dx.parquet", b"") == "loaded-table"
    assert looks_like(str(src), src.read_bytes()) == "site-list"
    assert json.loads((where / "manifest.json").read_text(encoding="utf-8"))["tables"]["site_dx"]["rows"] == 1
