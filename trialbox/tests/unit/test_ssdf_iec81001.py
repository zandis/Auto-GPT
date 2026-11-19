"""The secure-development mapping, ``docs/validation/ssdf-iec81001.csv`` (card 10G-19, D-1240).

One row per NIST SP 800-218 (SSDF v1.1) practice and task, and one row per IEC 81001-5-1:2021 clause or subclause of
clauses 4 to 9 that public summaries name. The exit of the card: every practice cites a file. This test holds it:
every status is from the allowed set, every ``met`` or ``partly`` row cites evidence that exists in the repository (a
deleted file, or a removed test, Makefile target or CI job named after ``::``, fails), every published SSDF task id
is present exactly once, and the page ``docs/security/11-secure-development-mapping.md`` agrees with the register.

The SSDF ids below are NIST's: the "SSDF table" of SP 800-218 v1.1 (February 2022),
https://csrc.nist.gov/files/pubs/sp/800/218/final/docs/nist.sp.800-218.ssdf-table.xlsx (a US government work).
IEC 81001-5-1 is not quoted: its rows carry our own short titles and say they are unverified against its text.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
MAP = ROOT / "docs" / "validation" / "ssdf-iec81001.csv"
PAGE = ROOT / "docs" / "security" / "11-secure-development-mapping.md"
PLAN10 = ROOT / "docs" / "plan" / "47-plan-10-2026-11-18.md"

COLUMNS = [
    "framework",
    "id",
    "kind",
    "group",
    "title",
    "status",
    "evidence",
    "gap",
    "weight",
    "size",
    "card",
    "reason",
    "source",
]
UNVERIFIED = "unverified against the standard's text"
STATUSES = ("met", "partly", "not met", "not applicable")
OPEN = ("partly", "not met")
WEIGHTS = ("high", "medium", "low")
SIZES = ("S", "M", "L")

# NIST SP 800-218 v1.1, the SSDF table: the 19 practices and their 42 tasks, in the publication's order.
# (v1.1 has no PW.3, PW.4.3 or PW.5.2: they were moved into other tasks.)
SSDF_TASKS: dict[str, tuple[str, ...]] = {
    "PO.1": ("PO.1.1", "PO.1.2", "PO.1.3"),
    "PO.2": ("PO.2.1", "PO.2.2", "PO.2.3"),
    "PO.3": ("PO.3.1", "PO.3.2", "PO.3.3"),
    "PO.4": ("PO.4.1", "PO.4.2"),
    "PO.5": ("PO.5.1", "PO.5.2"),
    "PS.1": ("PS.1.1",),
    "PS.2": ("PS.2.1",),
    "PS.3": ("PS.3.1", "PS.3.2"),
    "PW.1": ("PW.1.1", "PW.1.2", "PW.1.3"),
    "PW.2": ("PW.2.1",),
    "PW.4": ("PW.4.1", "PW.4.2", "PW.4.4"),
    "PW.5": ("PW.5.1",),
    "PW.6": ("PW.6.1", "PW.6.2"),
    "PW.7": ("PW.7.1", "PW.7.2"),
    "PW.8": ("PW.8.1", "PW.8.2"),
    "PW.9": ("PW.9.1", "PW.9.2"),
    "RV.1": ("RV.1.1", "RV.1.2", "RV.1.3"),
    "RV.2": ("RV.2.1", "RV.2.2"),
    "RV.3": ("RV.3.1", "RV.3.2", "RV.3.3", "RV.3.4"),
}
SSDF_GROUPS = ("PO", "PS", "PW", "RV")
IEC_GROUPS = ("4", "5", "6", "7", "8", "9")


def load(path: Path = MAP) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def items(field: str) -> list[str]:
    return [x.strip() for x in field.split(";") if x.strip()]


def evidence_exists(item: str, roots: tuple[Path, ...] = (ROOT, REPO)) -> bool:
    """A path from ``trialbox/`` or the repository root; ``path::name`` also needs ``name`` in the file: a Python
    ``def``, a Makefile target or a workflow job."""
    name, _, inner = item.partition("::")
    for base in roots:
        path = (base / name).resolve()
        if not path.is_relative_to(roots[-1].resolve()) or not path.is_file():
            continue
        if not inner:
            return True
        text = path.read_text("utf-8")
        n = re.escape(inner)
        return re.search(rf"^(\s*(async\s+)?def {n}\(|{n}:|  {n}:\s*$)", text, re.M) is not None
    return False


def problems(rows: list[dict[str, str]], roots: tuple[Path, ...] = (ROOT, REPO)) -> list[str]:
    out: list[str] = []
    for row in rows:
        rid = f"{row['framework']} {row['id']}"
        status, evidence = row["status"], items(row["evidence"])
        allowed = (*STATUSES, UNVERIFIED) if row["framework"] == "IEC 81001-5-1" else STATUSES
        if status not in allowed:
            out.append(f"{rid}: status {status!r}")
        if not row["title"].strip():
            out.append(f"{rid}: no title")
        if status in ("met", "partly") and not evidence:
            out.append(f"{rid}: {status} without evidence")
        out += [f"{rid}: evidence missing: {e}" for e in evidence if not evidence_exists(e, roots)]
        if status in ("not applicable", UNVERIFIED) and not row["reason"].strip():
            out.append(f"{rid}: {status} without a reason")
        if status == UNVERIFIED and evidence:
            out.append(f"{rid}: an unverified clause cites no evidence")
        if status in OPEN:
            if not row["gap"].strip():
                out.append(f"{rid}: {status} without a gap")
            if not row["card"].strip():
                out.append(f"{rid}: {status} without a card or 'no card'")
            if row["kind"] != "practice" and (row["weight"] not in WEIGHTS or row["size"] not in SIZES):
                out.append(f"{rid}: weight {row['weight']!r}, size {row['size']!r}")
        elif row["gap"] or row["weight"] or row["size"] or row["card"]:
            out.append(f"{rid}: a {status} row carries a gap, weight, size or card")
    return out


def rows_of(kind: str) -> list[dict[str, str]]:
    return [r for r in load()[1] if r["kind"] == kind]


def derived(statuses: list[str]) -> str:
    s = [x for x in statuses if x != "not applicable"]
    if not s:
        return "not applicable"
    return s[0] if len(set(s)) == 1 else "partly"


def clause_key(cid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in cid.split("."))


# ---- the register ----


def test_columns() -> None:
    assert load()[0] == COLUMNS


def test_every_row_passes() -> None:
    assert problems(load()[1]) == []


def test_every_published_ssdf_task_is_there_exactly_once_in_order() -> None:
    ids = [r["id"] for r in rows_of("task")]
    published = [t for tasks in SSDF_TASKS.values() for t in tasks]
    assert len(published) == 42
    assert Counter(ids) == Counter(published), "every SSDF v1.1 task exactly once"
    assert ids == published


def test_every_ssdf_practice_is_there_once_with_its_tasks_after_it() -> None:
    ssdf = [r for r in load()[1] if r["framework"] == "SSDF"]
    expected = [(p, "practice") for p in SSDF_TASKS] + [(t, "task") for ts in SSDF_TASKS.values() for t in ts]
    assert sorted((r["id"], r["kind"]) for r in ssdf) == sorted(expected)
    order = [r["id"] for r in ssdf]
    assert order == [x for p, ts in SSDF_TASKS.items() for x in (p, *ts)]
    for r in ssdf:
        assert r["group"] == r["id"][:2] and r["group"] in SSDF_GROUPS, r["id"]
        assert r["source"] == "NIST SP 800-218 v1.1 table", r["id"]


def test_a_practice_claims_no_more_than_its_tasks() -> None:
    tasks = {r["id"]: r for r in rows_of("task")}
    for p in rows_of("practice"):
        mine = [tasks[t] for t in SSDF_TASKS[p["id"]]]
        assert p["status"] == derived([t["status"] for t in mine]), p["id"]
        task_evidence = {e for t in mine for e in items(t["evidence"])}
        assert set(items(p["evidence"])) <= task_evidence, f"{p['id']}: evidence not from its tasks"
        task_cards = {c for t in mine for c in items(t["card"]) if c != "no card"}
        assert set(items(p["card"])) - {"no card"} == task_cards, p["id"]


def test_iec_rows_are_clauses_4_to_9_in_order_and_say_they_are_unverified() -> None:
    iec = [r for r in load()[1] if r["framework"] == "IEC 81001-5-1"]
    assert iec, "the IEC 81001-5-1 rows are missing"
    ids = [r["id"] for r in iec]
    assert len(set(ids)) == len(ids), "clause ids must be unique"
    assert all(re.fullmatch(r"[4-9](\.\d+){0,2}", i) for i in ids), ids
    assert ids == sorted(ids, key=clause_key)
    assert {r["group"] for r in iec} == set(IEC_GROUPS), "every clause 4 to 9 has a row"
    for r in iec:
        assert r["kind"] == "clause" and r["group"] == r["id"].split(".")[0], r["id"]
        assert UNVERIFIED in r["source"], f"{r['id']}: every IEC row says it is unverified against the text"


def test_every_card_named_is_a_plan_10_card() -> None:
    plan = PLAN10.read_text("utf-8")
    for r in load()[1]:
        for card in items(r["card"]):
            if card == "no card":
                continue
            assert re.fullmatch(r"10[A-Z]-\d+", card), f"{r['id']}: card {card!r}"
            assert re.search(rf"^\| {re.escape(card)} \|", plan, re.M), f"{r['id']}: {card} is not in plan 10"


def test_a_deleted_file_or_target_fails(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    cited = tmp_path / "tools" / "x.py"
    cited.write_text("def check_it() -> None:\n    pass\n", "utf-8")
    (tmp_path / "Makefile").write_text("scan: venv\n\techo scan\n", "utf-8")
    roots = (tmp_path,)
    row = dict.fromkeys(COLUMNS, "") | {"framework": "SSDF", "id": "PO.3.1", "kind": "task", "title": "t"}
    row |= {"status": "met", "evidence": "tools/x.py;tools/x.py::check_it;Makefile::scan"}
    assert problems([row], roots) == []
    assert problems([row | {"evidence": "tools/x.py::gone"}], roots) == [
        "SSDF PO.3.1: evidence missing: tools/x.py::gone"
    ]
    assert problems([row | {"evidence": "Makefile::gone"}], roots) == ["SSDF PO.3.1: evidence missing: Makefile::gone"]
    cited.unlink()
    assert "SSDF PO.3.1: evidence missing: tools/x.py" in problems([row], roots)
    assert problems([row | {"evidence": ""}], roots) == ["SSDF PO.3.1: met without evidence"]
    assert problems([row | {"evidence": "../../etc/passwd"}], roots) == [
        "SSDF PO.3.1: evidence missing: ../../etc/passwd"
    ]


def test_bad_rows_are_caught() -> None:
    base = dict.fromkeys(COLUMNS, "") | {"framework": "SSDF", "id": "PO.2.3", "kind": "task", "title": "t"}
    assert problems([base | {"status": "done"}]) == ["SSDF PO.2.3: status 'done'"]
    assert problems([base | {"status": UNVERIFIED, "reason": "r"}]) == [f"SSDF PO.2.3: status {UNVERIFIED!r}"]
    assert problems([base | {"status": "not met"}]) == [
        "SSDF PO.2.3: not met without a gap",
        "SSDF PO.2.3: not met without a card or 'no card'",
        "SSDF PO.2.3: weight '', size ''",
    ]
    assert problems([base | {"status": "not applicable"}]) == ["SSDF PO.2.3: not applicable without a reason"]


# ---- the page is kept in step with the register ----


def summary_lines(rows: list[dict[str, str]]) -> list[str]:
    out = []
    for fw, groups in (("SSDF", SSDF_GROUPS), ("IEC 81001-5-1", IEC_GROUPS)):
        for g in groups:
            mine = [r for r in rows if r["framework"] == fw and r["group"] == g and r["kind"] != "practice"]
            c = Counter(r["status"] for r in mine)
            counts = " | ".join(str(c[s]) for s in (*STATUSES, UNVERIFIED))
            out.append(f"| {fw} | {g} | {len(mine)} | {counts} |")
    return out


def gap_lines(rows: list[dict[str, str]]) -> list[str]:
    gaps = [r for r in rows if r["kind"] != "practice" and r["status"] in OPEN]
    gaps.sort(key=lambda r: WEIGHTS.index(r["weight"]))  # stable: the register's order within a weight
    return [f"| {r['weight']} | {r['framework']} {r['id']} | {r['gap']} | {r['size']} | {r['card']} |" for r in gaps]


def page_table(marker: str) -> list[str]:
    """The table rows (not the header or rule) after ``<!-- marker -->`` on the page."""
    lines = PAGE.read_text("utf-8").splitlines()
    start = lines.index(f"<!-- {marker} -->")
    table: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("|"):
            if table:
                break
            continue
        table.append(line)
    return table[2:]


def test_the_page_summary_matches_the_register() -> None:
    assert page_table("summary") == summary_lines(load()[1]), "rewrite the summary table from the register"


def test_the_page_lists_every_gap_by_weight() -> None:
    assert page_table("gaps") == gap_lines(load()[1]), "rewrite the gap table from the register"


def test_the_page_claims_nothing() -> None:
    text = PAGE.read_text("utf-8")
    assert "self-assessment" in text
    assert "purchased standard" in text
    lowered = text.lower()
    for claim in ("we conform", "is compliant", "conforms to", "is certified", "certified to", "compliant with"):
        assert claim not in lowered, f"the page must not claim conformity: {claim!r}"
