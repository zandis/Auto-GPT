"""``NOTICE`` names every third-party source the demo image ships (T-617a, STD-044, plan v6 §9.4).

The demo image (``demo/Dockerfile``) copies the whole ``trialbox/`` folder minus ``.dockerignore``. A *vocabulary
folder* is a folder of that copy holding code lists, code maps or value sets: a CSV, TSV, text or Parquet file whose
name or header names a code system (LOINC, ATC, ICD, SNOMED, UCUM, YJ, JLAC10, MEDIS, NHI, ...), or a FHIR ValueSet,
CodeSystem or ConceptMap. Each one must be named in the NOTICE section "Shipped vocabulary folders" (a ``*`` there
stands for one path segment), and each line of that section must still name a shipped folder.
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTICE = ROOT / "NOTICE"
SECTION = "SHIPPED VOCABULARY FOLDERS"
# never in the image whatever .dockerignore says (local tool state), or not data at all
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
TOKENS = {
    "atc", "byomei", "cdisc", "ctcae", "hot", "icd", "icd9", "icd10", "icd10cm", "icd11", "jlac10", "jlac11",
    "loinc", "meddra", "medis", "nhi", "rxnorm", "snomed", "ucum", "umls", "yakka", "yj",
}  # fmt: skip
TABULAR = (".csv", ".tsv", ".txt", ".csv.gz", ".parquet")
FHIR_TERMINOLOGY = re.compile(rb'"resourceType"\s*:\s*"(ValueSet|CodeSystem|ConceptMap)"')


def _dockerignore() -> list[re.Pattern[str]]:
    """The patterns of ``.dockerignore`` as regular expressions over a path relative to the build context (Docker
    anchors every pattern at the context root; ``**`` is any number of segments)."""
    out = []
    for raw in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        rx = ""
        i = 0
        while i < len(line):
            if line.startswith("**/", i):
                rx += "(?:.*/)?"
                i += 3
            elif line.startswith("**", i):
                rx += ".*"
                i += 2
            elif line[i] == "*":
                rx += "[^/]*"
                i += 1
            elif line[i] == "?":
                rx += "[^/]"
                i += 1
            else:
                rx += re.escape(line[i])
                i += 1
        out.append(re.compile(rx.strip("/") + "(?:/.*)?"))
    return out


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower()))


def _is_vocabulary(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(TABULAR):
        stem = name.removesuffix(".gz").rsplit(".", 1)[0]
        if _tokens(stem) & TOKENS:
            return True
        if name.endswith(".parquet"):
            return False
        opener = gzip.open if name.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
                header = fh.readline()
        except OSError:
            return False
        return bool(_tokens(header) & TOKENS)
    if name.endswith(".json"):
        with path.open("rb") as fh:
            return bool(FHIR_TERMINOLOGY.search(fh.read(4096)))
    return False


def shipped_vocabulary_folders() -> set[str]:
    """Folders of the demo image's copy of ``trialbox/`` that hold vocabulary files, relative and posix."""
    ignore = _dockerignore()
    found: set[str] = set()
    stack = [ROOT]
    while stack:
        here = stack.pop()
        for p in here.iterdir():
            rel = p.relative_to(ROOT).as_posix()
            if p.name in SKIP_DIRS or any(rx.fullmatch(rel) for rx in ignore):
                continue
            if p.is_dir() and not p.is_symlink():
                stack.append(p)
            elif p.is_file() and here != ROOT and _is_vocabulary(p):
                found.add(here.relative_to(ROOT).as_posix())
    return found


def notice_folders() -> list[str]:
    """The folder lines of the NOTICE section: the first word of each indented line that ends with ``/``."""
    text = NOTICE.read_text(encoding="utf-8")
    start = text.index(SECTION)
    body = re.sub(r"^\s*={3,}\n", "", text[start + len(SECTION) :])  # the heading's own underline
    end = re.search(r"\n={3,}\n", body)
    body = body[: end.start()] if end else body
    out = []
    for line in body.splitlines():
        m = re.match(r"\s+(\S+)/(?:\s|$)", line)
        if m:
            out.append(m.group(1))
    return out


def _matches(pattern: str, folder: str) -> bool:
    rx = "/".join("[^/]+" if seg == "*" else re.escape(seg) for seg in pattern.split("/"))
    return re.fullmatch(rx, folder) is not None


def test_every_shipped_vocabulary_folder_is_named_in_notice() -> None:
    entries = notice_folders()
    assert entries, f"NOTICE has no {SECTION} section"
    missing = sorted(f for f in shipped_vocabulary_folders() if not any(_matches(e, f) for e in entries))
    assert not missing, f"vocabulary folders shipped in the demo image but not named in NOTICE: {missing}"


def test_every_notice_folder_line_names_a_shipped_folder() -> None:
    shipped = shipped_vocabulary_folders()
    stale = [e for e in notice_folders() if not any(_matches(e, f) for f in shipped)]
    assert not stale, f"NOTICE names vocabulary folders the image does not ship: {stale}"


def test_the_detector_sees_the_known_folders() -> None:
    """A guard on the detector itself: the folders STD-044 names are found."""
    shipped = shipped_vocabulary_folders()
    for folder in (
        "services/criteria_compiler/terminology/src",
        "rulesets/GZQO/valuesets",
        "catalogue",
        "services/adapter/mapping/mimic/tables",
        "libs/tb_common/refdata_src",
    ):
        assert folder in shipped, folder


def test_a_new_vocabulary_folder_fails_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "vocab" / "new").mkdir(parents=True)
    (tmp_path / "vocab" / "new" / "codes.csv").write_text("local,loinc\nA,2160-0\n", encoding="utf-8")
    (tmp_path / "vocab" / "fhir").mkdir()
    (tmp_path / "vocab" / "fhir" / "vs.json").write_text('{"resourceType": "ValueSet"}', encoding="utf-8")
    (tmp_path / "vocab" / "plain").mkdir()
    (tmp_path / "vocab" / "plain" / "notes.csv").write_text("id,text\n1,hello\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "atc.csv").write_text("code,display\n", encoding="utf-8")  # dockerignored
    (tmp_path / ".dockerignore").write_text("data\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert shipped_vocabulary_folders() == {"vocab/new", "vocab/fhir"}


def test_the_jar_and_font_lists_are_named_in_notice() -> None:
    """The translator's direct dependency and every fetched jar (when ``tools/fetch_jvm_deps.sh`` has run), and
    every font of ``tools/fetch_fonts.py``, are named in NOTICE."""
    from tools.fetch_fonts import FONTS

    text = NOTICE.read_text(encoding="utf-8")
    pom = (ROOT / "services/criteria_compiler/compile_cql/translator/pom.xml").read_text(encoding="utf-8")
    for artifact, version in re.findall(r"<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>", pom):
        if artifact != "cql-translator":
            assert f"{artifact} {version}" in text, artifact
    for family in FONTS:
        assert re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family) in text, family
    lib = ROOT / ".cache/jvm/cql-translator/lib"
    jars = sorted(lib.glob("*.jar")) if lib.is_dir() else []
    missing = [j.name for j in jars if j.name.removesuffix(".jar") not in text]
    assert not missing, f"jars fetched for the image but not named in NOTICE: {missing}"
