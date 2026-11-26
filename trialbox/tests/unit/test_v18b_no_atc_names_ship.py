"""V-18b review F2 (D-1183): no shipped file pairs an ATC code with a name, so NOTICE's "no ATC names are shipped" holds.

ATC codes ship as identifiers (D-536). A name beside one is allowed only in the files named here, each for its
reason (NOTICE, ATC entry): TrialBox's own matching text (generic drug names, INNs, which are public, the words a
matcher looks for in text), synthetic labels, and synthetic patient records. Anything else fails, with the line.

Two checks: every ValueSet or coding of the ATC system names its code by the code itself (no other display); and no
line outside the named files puts an ATC code beside one of the generic names TrialBox's own matching text uses."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.synth import catalog

ROOT = Path(__file__).resolve().parents[2]
ATC_URI = "http://www.whocc.no/atc"
ATC_CODE = re.compile(r"\b[A-Z]\d{2}[A-Z]{2}\d{2}\b")
# each file allowed to put a generic name beside an ATC code, and why (NOTICE names the same files)
ALLOWED = {
    "tools/synth/catalog.py": "the synthetic generator's drugs: matching words and synthetic product labels",
    "tools/synth_charts.py": "the synthetic chart writer's drug words (matching text)",
    "tools/imperfect_feed.py": "synthetic product labels of a made-up feed",
    "tools/e2e_simple.py": "a check's message",
    "services/sitesetup/mapping.py": "site setup's drug words (matching text)",
    "services/llm_stub/handlers.py": "the model stub's drug words (matching text)",
    "services/adapter/mapping/mimic/tables/drug_to_atc.csv": "its pattern column: the words matched in MIMIC's text",
    "services/criteria_compiler/terminology/src/synonyms.csv": "TrialBox's own groupers: a concept name and its codes",
    "services/criteria_compiler/terminology/src/nhi_drug.csv": "synthetic NHI product labels",
}
# synthetic patient records: a drug's text beside its code is the record, not the index
RECORDS = (
    re.compile(r"^rulesets/[^/]+/tests/patients\.ndjson$"),
    re.compile(r"^tests/fixtures/synthetic_patients/"),
    re.compile(r"^tests/fixtures/equivalence/"),
    re.compile(r"^tests/fixtures/sitesetup_code_tables/"),  # captured site set-up answers: a site's product names
)
SKIP_SUFFIX = (".parquet", ".png", ".gz", ".zip", ".pdf", ".xlsx", ".woff2", ".ttf", ".ico", ".jpg", ".svg")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\n") if f and not f.startswith("docs/") and not f.endswith((".md", *SKIP_SUFFIX))
            and not (f.startswith("tests/") and f.endswith(".py"))]  # fmt: skip


def _text(rel: str) -> str | None:
    try:
        return (ROOT / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None


def _atc_concepts(o: Any) -> Iterator[dict[str, Any]]:
    """Each object of the ATC system with a code: a ValueSet include's concepts and every coding."""
    if isinstance(o, dict):
        if o.get("system") == ATC_URI:
            if isinstance(o.get("code"), str):
                yield o
            for c in o.get("concept") or []:
                if isinstance(c, dict):
                    yield c
        for v in o.values():
            yield from _atc_concepts(v)
    elif isinstance(o, list):
        for v in o:
            yield from _atc_concepts(v)


def test_no_atc_valueset_or_coding_names_its_code_with_a_name() -> None:
    bad = []
    for rel in _tracked():
        if not rel.endswith((".json", ".ndjson")) or any(p.search(rel) for p in RECORDS) or rel in ALLOWED:
            continue
        text = _text(rel)
        if text is None or ATC_URI not in text:
            continue
        docs = [text] if rel.endswith(".json") else [ln for ln in text.splitlines() if ln.strip()]
        for doc in docs:
            try:
                obj = json.loads(doc)
            except ValueError:
                continue
            bad += [f"{rel}: {c['code']} {c['display']!r}" for c in _atc_concepts(obj)
                    if c.get("display") not in (None, "", c.get("code"))]  # fmt: skip
    assert bad == []


def test_no_shipped_file_outside_the_named_ones_puts_a_generic_name_beside_an_atc_code() -> None:
    names = {k.lower() for k in catalog.DRUGS} | {"warfarin", "apixaban", "furosemide", "bumetanide", "torasemide"}
    word = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b", re.I)
    bad = []
    for rel in _tracked():
        if rel in ALLOWED or any(p.search(rel) for p in RECORDS):
            continue
        text = _text(rel)
        if text is None or not ATC_CODE.search(text):
            continue
        bad += [f"{rel}:{i}" for i, ln in enumerate(text.splitlines(), 1) if ATC_CODE.search(ln) and word.search(ln)]
    assert bad == []


def test_the_named_files_are_named_in_notice() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert [f for f in ALLOWED if f not in notice] == []
