"""INT-R2 (deep check row R2): a drug class's gap reads unknown, never False.

A drug class is a ValueSet of listed ATC codes plus code families (D-113, SCR-01). A medication code is read: listed,
a member (True); else inside a family, unknown, for review; else not a member (False). On master the classes held one
or two prefixes, so a member outside them read False: a patient silently passed over by an inclusion, or let through
by an exclusion.

``EXCLUDED`` is each class's definition from the other side: the branches of the ATC tree certain to hold no member.
Every other branch, one the tree does not have yet included, is a ``family`` row of ``synonyms.csv``: the rows are the
complement of ``EXCLUDED`` over the ATC grammar, held by a test here. So a code nobody placed reads unknown by
default, and False needs an exclusion. The exclusions and the members to confirm are on the card page
(``docs/handover/intr2-drug-class-gaps-2026-11-25.md``).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import SYSTEMS, YJ_STEM, Terminology, ValueSets, valueset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
ATC = SYSTEMS["atc"]
TERM_SRC = ROOT / "services/criteria_compiler/terminology/src"
TWCORE_ATC = "https://twcore.mohw.gov.tw/ig/twcore/ValueSet/medcation-atc-tw"
LEVEL1 = set("ABCDGHJLMNPRSV")  # the 14 anatomical main groups of ATC
UP = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GRAMMAR = [UP, range(10), range(10), UP, UP, range(10), range(10)]  # the seven characters of a level-5 code


def _b(*branches: str) -> set[str]:
    """Space-separated branches: ``"L01 L02"``."""
    return {x for b in branches for x in b.split()}


L04AX_SMALL = {f"L04AX{n:02d}" for n in (1, 2, 4, 5, 6, 7, 9, 10, 11)}  # 03 is methotrexate, 08 a cell therapy
BIOLOGIC = (
    (LEVEL1 - _b("C D J L M N R S"))
    | _b("C01 C02 C03 C04 C05 C07 C08 C09 C10AA C10AB C10AC C10AD C10B")
    | _b("D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 J01 J02 J04 J05 J07")
    | _b("L01A L01B L01C L01D L02 L04AA13 L04AD L04AE L04AH L04AK L04AX03")
    | _b("M01 M02 M03 M04 M09 N01 N03 N04 N05 N07 R01 R02 R05 R06 R07 S02 S03")
    | L04AX_SMALL
)
# the ATC branches certain to hold no member of the class; everything else is unknown unless listed
EXCLUDED: dict[str, set[str]] = {
    "urate-lowering therapy": (LEVEL1 - _b("M V")) | _b("M01 M02 M03 M05 M09 M04AC01 V01 V04 V06 V07 V08 V09 V10 V20"),
    "glp-1 receptor agonist": (LEVEL1 - {"A"})
    | _b("A01 A02 A03 A04 A05 A06 A07 A09 A11 A12 A13 A14 A15 A10AB0 A10AC0 A10AE0")
    | _b("A10BA0 A10BB0 A10BC0 A10BF0 A10BG0 A10BH0 A10BK0"),
    "colchicine": (LEVEL1 - {"M"}) | _b("M01 M02 M03 M05 M09 M04AA0 M04AB0"),
    "methotrexate": (LEVEL1 - _b("L M"))
    | _b("M01A M01B M02 M03 M04 M05 M09 L01A L01C L01D L01E L01F L01BA03 L01BA04 L01BA05 L02 L03")
    | _b("L04AA L04AB L04AC L04AD L04AE L04AF L04AG L04AH L04AJ L04AK L04AL L04AX08")
    | L04AX_SMALL,
    "conventional synthetic dmard other than methotrexate": _b("B C G H N R S V")
    | _b("A01 A02 A03 A04 A05 A06 A08 A09 A10 A11 A12 A13 A14 A15 A16")
    | _b("A07A A07B A07C A07D A07F A07X A07EA A07EC02")
    | _b("D01 D02 D03 D04 D06 D07 D08 D09 D10 D11 J01B J01C J01D J01E J01F J01G J01M J01R J01X J02 J04 J05 J06 J07")
    | _b("L01BA01 L01E L01F L02 L04AB L04AC L04AF L04AG L04AJ L04AL L04AX03")
    | _b("M01A M01B M02 M03 M04 M05 M09 P02 P03"),
    "tb preventive therapy": (LEVEL1 - {"J"}) | _b("J01A J01B J01C J01D J01E J01F J01G J01R J01X J02 J05 J06 J07"),
    "hbv antiviral prophylaxis": (LEVEL1 - _b("J L"))
    | _b("J01 J02 J04 J07 J05AA J05AB J05AC J05AD J05AE J05AG J05AH J05AJ L01 L02 L04"),
    "ra biologic": BIOLOGIC | _b("L01E L04AF"),
    "biologic dmard or jak inhibitor": BIOLOGIC
    | _b("L01EA L01EB L01EC L01ED L01EE L01EF L01EG L01EH L01EK L01EL L01EM L01EN L01EP"),
    "egfr tyrosine kinase inhibitor": (LEVEL1 - {"L"}) | _b("L01A L01B L01C L01D L02 L03 L04"),
    "anticoagulant": (LEVEL1 - _b("B C")) | _b("C01 C02 C03 C04 C06 C07 C08 C09 C10 B02 B03 B06 B01AC0 B01AC1 B01AC2"),
}
EXCLUDED["抗凝固薬"] = EXCLUDED["anticoagulant"]  # the Japanese name of the same class


def complement(covered: set[str], prefix: str = "") -> list[str]:
    """The shortest prefixes that together hold every ATC code no branch of ``covered`` holds."""
    if any(prefix.startswith(c) for c in covered):
        return []
    # "X" alone is split: it is the resource's alias in the CQL, and the translator refuses the literal 'X'
    if prefix not in ("", "X") and not any(c.startswith(prefix) for c in covered):
        return [prefix]
    return [p for ch in GRAMMAR[len(prefix)] for p in complement(covered, f"{prefix}{ch}")]


# members (or likely members) outside the listed prefixes: False on master. The deep check's own fixture was not
# available; these are its two kinds (biologics outside the prefixes, combination products) and the same gap elsewhere
MISSES: list[tuple[str, str]] = [
    *(
        (cls, code)
        for cls in ("ra biologic", "biologic dmard or jak inhibitor")
        for code in ("L04AA24", "L04AC14", "L04AC03", "L01FA01", "L01XC02", "L04AL01")
    ),
    ("glp-1 receptor agonist", "A10AE54"),
    ("glp-1 receptor agonist", "A10AE56"),
    ("glp-1 receptor agonist", "A10AE57"),
    ("colchicine", "M04AC51"),
    ("urate-lowering therapy", "M04AC51"),
    ("urate-lowering therapy", "M04AX02"),
    ("methotrexate", "L01BA01"),
    ("anticoagulant", "B01AB05"),
    ("anticoagulant", "B01AX05"),
    ("tb preventive therapy", "J04AB02"),
    ("tb preventive therapy", "J04AM02"),
    ("tb preventive therapy", "J01MA12"),
    ("hbv antiviral prophylaxis", "J05AF13"),
    ("conventional synthetic dmard other than methotrexate", "L04AD02"),
    ("conventional synthetic dmard other than methotrexate", "L04AK01"),
    ("egfr tyrosine kinase inhibitor", "L01XE03"),
]
# a code coarser than a class's own node cannot be placed either; nor can a branch the tree does not have today
UNPLACED = [
    ("ra biologic", "L04"),
    ("urate-lowering therapy", "M04A"),
    ("methotrexate", "L04AX"),
    ("glp-1 receptor agonist", "A10"),
    ("ra biologic", "L04AZ01"),
    ("anticoagulant", "X01AA01"),
]


def _shipped() -> dict[str, dict[str, Any]]:
    """Every shipped medication class: ``<ruleset>/<ValueSet>`` -> the ValueSet (its ATC codes and families)."""
    out = {}
    for f in sorted((ROOT / "rulesets").glob("*/valuesets/*.json")):
        vs = json.loads(f.read_text(encoding="utf-8"))
        if any(inc.get("system") == ATC for inc in vs["compose"]["include"]):
            out[f"{f.parent.parent.name}/{f.stem}"] = vs
    return out


SHIPPED = _shipped()


def _cls(vs: dict[str, Any]) -> str:
    return str(vs["title"])


def _fams(vs: dict[str, Any]) -> set[str]:
    return {pre for sy, pre in ValueSets("X", {"V": vs}).families("V") if sy == ATC}


def _listed(vs: dict[str, Any]) -> set[str]:
    return {c for s, c in ValueSets("X", {"V": vs}).codes("V") if s == ATC}


def _read(vs: dict[str, Any], code: str) -> bool | None:
    """The ValueSet's reading of one ATC code: listed True, inside or above a family unknown, else False."""
    if code in _listed(vs):
        return True
    return None if any(code.startswith(p) or p.startswith(code) for p in _fams(vs)) else False


def _rows(name: str) -> list[dict[str, str]]:
    with (TERM_SRC / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _synthetic() -> set[str]:
    return {r["atc"] for r in _rows("nhi_drug.csv") if r.get("atc")} | {c for _, c in MISSES}


def _corpus() -> set[str]:
    """Every level-5 ATC code the repository's terminology holds."""
    codes = _synthetic()
    codes |= {r["code"] for r in _rows("synonyms.csv") if r["table"] == "atc" and r["match"] == "exact"}
    tw = json.loads((ROOT / "services/adapter/validate/twcore_rules.json").read_text(encoding="utf-8"))
    codes |= set(tw["valuesets"][TWCORE_ATC]["codes"][ATC])
    return {c for c in codes if re.fullmatch(r"[A-Z]\d{2}[A-Z]{2}\d{2}", c)}


def _crit(title: str, duration: bool) -> CriterionIR:
    logic: dict[str, Any] = {"domain": "medication", "quantifier": "any", "valueset": "VS_X"}
    logic["window"] = {"anchor": "index", "from_days": -365, "to_days": 0}
    if duration:
        logic["duration"] = {"min_days": 90, "gap_days": 30}
    return CriterionIR.model_validate(
        {"id": "INTR-EXC-01", "ruleset": "INTR", "text": title, "kind": "exclusion", "class": "structured",
         "logic": logic}
    )  # fmt: skip


def _sql(
    vs: dict[str, Any], codes: list[str], duration: bool = False, start: str = "2026-01-01"
) -> dict[str, bool | None]:
    """The SQL engine's answer per code (one patient on one drug for 120 days): on the class, or on it for 90 days."""
    sql = SqlGenerator("INTR", "1.0.0", ValueSets("INTR", {"VS_X": vs})).render([_crit(vs["title"], duration)])
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE medication (pid VARCHAR, mid VARCHAR, atc VARCHAR, nhi_code VARCHAR, authored DATE, "
        'start DATE, "end" DATE)'
    )
    for c in codes:
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL, NULL)", [c])
        con.execute(
            "INSERT INTO medication VALUES (?, ?, ?, NULL, ?::DATE, ?::DATE, ?::DATE + 120)",
            [c, f"m-{c}", c, start, start, start],
        )
    rows = con.execute(sql, [["2026-06-01"], codes]).fetchall()
    cols = [d[0] for d in con.description]
    return {r[0]: next(v for k, v in zip(cols, r, strict=True) if k.startswith("C_")) for r in rows}


def _cql(vs: dict[str, Any], duration: bool = False) -> str:
    return CqlGenerator("INTR", "1.0.0", ValueSets("INTR", {"VS_X": vs})).render([_crit(vs["title"], duration)])


def _cql_families(cql: str) -> set[str]:
    """The ATC prefixes the CQL reads as inside the class and off its list; the same list serves the coarse codes."""
    atc = re.escape(ATC)
    down = set(re.findall(rf"Cd\.system\.value = '{atc}' and StartsWith\(Cd\.code\.value, '([^']+)'\)", cql))
    lists = re.findall(
        r"exists \(\(\{ ([^}]+) \}\) Fp where StartsWith\(Cd\.code\.value, Fp\) "
        r"or StartsWith\(Fp, Cd\.code\.value\)\)",
        cql,
    )
    up = {p for m in lists for p in re.findall(r"'([^']+)'", m)}
    assert down <= up
    return up


def test_every_shipped_drug_class_has_its_exclusions_written() -> None:
    assert len(SHIPPED) == 15
    assert {_cls(vs) for vs in SHIPPED.values()} <= set(EXCLUDED)


def test_the_family_rows_are_the_complement_of_the_exclusions() -> None:
    """Fail closed by construction: the rows of every class are exactly what EXCLUDED leaves of the ATC grammar."""
    rows = _rows("synonyms.csv")
    for name, excluded in EXCLUDED.items():
        mine = [r for r in rows if r["domain"] == "medication" and r["name"] == name]
        members = {r["code"] for r in mine if r["match"] == "prefix"}
        assert {r["code"] for r in mine if r["match"] == "family"} == set(complement(excluded | members)), name


def test_no_atc_code_at_all_reads_false_unless_its_branch_is_excluded() -> None:
    """The invariant over the whole grammar, on the shipped ValueSets: an exclusion or a family holds every code."""
    for key, vs in SHIPPED.items():
        assert complement(EXCLUDED[_cls(vs)] | _fams(vs)) == [], key
        assert not [c for c in _listed(vs) if any(c.startswith(x) for x in EXCLUDED[_cls(vs)])], key


def test_no_code_of_the_terminology_reads_false_unless_its_branch_is_excluded() -> None:
    """The invariant code by code, over every level-5 ATC code the repository's terminology holds."""
    corpus = _corpus()
    assert len(corpus) > 2000  # the TW Core value set is read
    gaps = [
        f"{key}: {c}"
        for key, vs in SHIPPED.items()
        for c in sorted(corpus)
        if _read(vs, c) is False and not any(c.startswith(x) for x in EXCLUDED[_cls(vs)])
    ]
    assert gaps == []


@pytest.mark.parametrize("duration", [False, True], ids=["presence", "duration"])
@pytest.mark.parametrize(("cls", "code"), [*MISSES, *UNPLACED])
def test_a_code_outside_the_listed_ones_is_unknown(cls: str, code: str, duration: bool) -> None:
    hits = {k: vs for k, vs in SHIPPED.items() if _cls(vs) == cls}
    assert hits, cls
    for key, vs in hits.items():
        assert _sql(vs, [code], duration)[code] is None, (key, code, "sql")
        fams = _cql_families(_cql(vs, duration))
        assert any(code.startswith(p) or p.startswith(code) for p in fams), (key, code, "cql")


@pytest.mark.parametrize("duration", [False, True], ids=["presence", "duration"])
def test_both_engines_read_the_class_as_its_valueset_says(duration: bool) -> None:
    codes = sorted(_synthetic())
    for key, vs in SHIPPED.items():
        assert _cql_families(_cql(vs, duration)) == _fams(vs), key
        assert _sql(vs, codes, duration) == {c: _read(vs, c) for c in codes}, key


def test_an_order_that_ended_before_the_window_stays_out_of_a_duration() -> None:
    vs = next(v for v in SHIPPED.values() if _cls(v) == "methotrexate")
    assert _sql(vs, ["L01BA01", "L04AX03"], True, "2020-01-01") == {"L01BA01": False, "L04AX03": False}
    assert _sql(vs, ["L01BA01", "L04AX03"], True) == {"L01BA01": None, "L04AX03": True}


def test_the_cql_duration_reads_the_family_orders_as_unknown() -> None:
    vs = next(v for v in SHIPPED.values() if _cls(v) == "methotrexate")
    want = r'then true else if exists \("OF_[^"]+"\) or exists \("O_[^"]+"\) then null as Boolean else false'
    assert re.search(want, _cql(vs, True))


def test_a_code_outside_every_class_is_false_only_where_its_branch_is_excluded() -> None:
    """C10AA05 is in no class; M04AC01 is no urate-lowering therapy; L04AX03 is named out of the other DMARDs."""
    other = "conventional synthetic dmard other than methotrexate"
    for code, cls in [("C10AA05", None), ("M04AC01", "urate-lowering therapy"), ("L04AX03", other)]:
        for key, vs in SHIPPED.items():
            if cls is None or _cls(vs) == cls:
                assert _sql(vs, [code])[code] is False, (key, code)
                assert any(code.startswith(x) for x in EXCLUDED[_cls(vs)]), (key, code)


def test_a_japanese_sites_ingredient_stems_never_make_a_family_a_member() -> None:
    """A YJ stem (T-610) is a member for a listed code or a member prefix, never for a family that is only unknown."""
    res = Terminology().map("medication", "ra biologic")
    assert (ATC, "L04AB") in res.families and (ATC, "L04AB") not in res.open_families
    assert (ATC, "L04AC") in res.open_families
    stems = {"1111111": {"atc": "L04AB04", "ingredient": "a"}, "2222222": {"atc": "L04AC14", "ingredient": "b"}}
    vs = valueset(
        "X", "VS_X", "x", res.concepts, "1.0.0", families=res.families, ingredients=stems,
        open_families=res.open_families,
    )  # fmt: skip
    got = {c["code"] for inc in vs["compose"]["include"] if inc["system"] == YJ_STEM for c in inc["concept"]}
    assert got == {"1111111"}


NHI = SYSTEMS["nhi_drug"]


@pytest.mark.parametrize("duration", [False, True], ids=["presence", "duration"])
def test_an_order_with_no_atc_is_unknown_for_an_exclusion_only_in_its_window(duration: bool) -> None:
    """The bound: an order with no ATC, not listed by its own code, in the atom's window, for an exclusion. An
    inclusion's compiled answer stays False: D-130's runtime rule holds it (the off-list oracle's ULT-YJ)."""
    vs = next(v for v in SHIPPED.values() if _cls(v) == "methotrexate")
    vs = {**vs, "compose": {"include": [*vs["compose"]["include"], {"system": NHI, "concept": [{"code": "OWN1"}]}]}}
    vsets = ValueSets("INTR", {"VS_X": vs})

    def run(kind: str, start: str) -> dict[str, bool | None]:
        crit = _crit("x", duration).model_copy(update={"kind": kind})
        con = duckdb.connect()
        con.execute(
            "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
        )
        con.execute(
            "CREATE TABLE medication (pid VARCHAR, mid VARCHAR, atc VARCHAR, nhi_code VARCHAR, authored DATE, "
            'start DATE, "end" DATE)'
        )
        orders = {"local": (None, "LOCAL9"), "empty": ("", None), "own": (None, "OWN1"), "other": ("C10AA05", "Z")}
        for pid, (atc, own) in orders.items():
            con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL, NULL)", [pid])
            con.execute(
                "INSERT INTO medication VALUES (?, ?, ?, ?, ?::DATE, ?::DATE, ?::DATE + 120)",
                [pid, pid, atc, own, start, start, start],
            )
        con.execute("INSERT INTO patient VALUES ('noorder', DATE '1960-01-01', 'female', NULL, NULL)")
        sql = SqlGenerator("INTR", "1.0.0", vsets).render([crit])
        rows = con.execute(sql, [["2026-06-01"], [*orders, "noorder"]]).fetchall()
        cols = [d[0] for d in con.description]
        return {r[0]: next(v for k, v in zip(cols, r, strict=True) if k.startswith("C_")) for r in rows}

    still = {"own": True, "other": False, "noorder": False}
    assert run("exclusion", "2026-01-01") == {"local": None, "empty": None, **still}
    assert run("inclusion", "2026-01-01") == {"local": False, "empty": False, **still}
    old = run("exclusion", "2020-01-01")
    assert old == dict.fromkeys(old, False)  # outside the window
    for kind in ("exclusion", "inclusion"):
        cql = CqlGenerator("INTR", "1.0.0", vsets).render([_crit("x", duration).model_copy(update={"kind": kind})])
        assert (f"not exists (((X.medication as FHIR.CodeableConcept).coding) Cd where Cd.system.value = '{ATC}'" in cql
                ) == (kind == "exclusion")  # fmt: skip


def test_no_class_lost_a_japanese_ingredient_stem() -> None:
    """Master gave a class the stems of its listed codes and of its prefix rows. Every one is still a member."""
    from tb_common.refdata_jp import ingredient_atc

    term, stems = Terminology(), ingredient_atc()
    rows = [r for r in term.synonyms if r["domain"] == "medication"]
    given = 0
    for name in sorted({r["name"] for r in rows}):
        res = term.map("medication", name)
        listed = {c.code for c in res.concepts if c.system == ATC}
        prefixes = tuple(r["code"] for r in rows if r["name"] == name and r["match"] == "prefix")
        master = {s for s, r in stems.items() if r["atc"] in listed or (prefixes and r["atc"].startswith(prefixes))}
        vs = valueset("X", "VS_X", "x", res.concepts, "1", families=res.families, ingredients=stems,
                      open_families=res.open_families)  # fmt: skip
        assert set(ValueSets("X", {"V": vs}).yj_stems("V")) == master, name
        given += len(master)
    assert given > 0


def test_the_owners_table_is_the_exclusions() -> None:
    page = ROOT / "docs/handover/intr2-drug-class-gaps-2026-11-25/excluded.md"
    cells = [ln.split("|") for ln in page.read_text(encoding="utf-8").splitlines() if ln.startswith("| ")][2:]
    table = {c[1].strip(): set(c[2].split()) for c in cells}
    assert table == {k: v for k, v in EXCLUDED.items() if k.isascii()}
    assert all(c[3].strip() for c in cells)


def test_the_synthetic_generators_drugs_are_all_placed() -> None:
    """Why the goldens stand: every drug the generator gives is listed or excluded for every class, none unknown. So
    the goldens show no recorded answer moved; they do not exercise the new rule."""
    from tools.synth import catalog

    codes = {d.atc for d in catalog.DRUGS.values()}
    assert len(codes) >= 20
    assert [(k, c) for k, vs in SHIPPED.items() for c in sorted(codes) if _read(vs, c) is None] == []
