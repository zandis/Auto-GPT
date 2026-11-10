"""A lab row's own unit against the lookup's (R-31, T-118, D-215): :func:`tb_common.labvalue.read`.

The safety rules under test: no path returns a value converted across units; a unit the UCUM table lacks is unknown on
either side, never converted and never taken as equal; a mismatch is no value with ``unit_mismatch``, which the
engines read as unknown, never as an exclusion (D-130).
"""

from __future__ import annotations

import itertools
import random
import unicodedata
from pathlib import Path

import pytest
from adapter.mapping.engine import DATA_ABSENT, Mapper, ResourceSpec
from lake.flatten import Flattener
from tb_common import labvalue
from tb_common.labvalue import UCUM, UNIT_MISMATCH, UNKNOWN_VALUE, Reading, read, ucum
from tb_common.reasons import CODES, LABELS, code_of, label

from tests.unit.test_mapping_engine import KEY, _mapping


# ------------------------------------------------------------------------------------------------ read
@pytest.mark.parametrize(
    ("text", "row", "lookup", "expected"),
    [
        ("5", "mg/dL", "mg/dL", Reading(5.0, None, None)),
        ("5", "mg/dl", "mg/dL", Reading(5.0, None, None)),  # a spelling of the same unit
        ("5", "MG/DL", "mg/dL", Reading(5.0, None, None)),  # hospital exports change the case of quotients
        ("５．０", "ｍｇ／ｄＬ", "mg/dL", Reading(5.0, None, None)),  # full width
        ("480", "µmol/L", "umol/L", Reading(480.0, None, None)),
        ("480", "μmol/l", "umol/L", Reading(480.0, None, None)),  # Greek mu
        ("12", "ug/mL", "mg/L", Reading(12.0, None, None)),  # equal by definition, no factor
        ("<0.3", "mg/dL", "mg/dL", Reading(0.3, "<", None)),  # censored stays censored
        ("75 H", "U/L", "U/L", Reading(75.0, None, None)),
        ("5", "", "mg/dL", Reading(5.0, None, None)),  # the row says nothing: the site's declared unit
        ("5", None, "mg/dL", Reading(5.0, None, None)),
        ("5", "　", None, Reading(5.0, None, None)),
        # acceptance (1): a CRP in mg/L against an mg/dL lookup is unknown, not divided by 10
        ("5", "mg/L", "mg/dL", Reading(None, None, UNIT_MISMATCH)),
        ("1.0", "mg/dL", "mg/L", Reading(None, None, UNIT_MISMATCH)),
        ("88", "umol/L", "mg/dL", Reading(None, None, UNIT_MISMATCH)),  # creatinine: convertible, but not here
        ("6.5", "mmol/mol", "%", Reading(None, None, UNIT_MISMATCH)),  # HbA1c IFCC against NGSP
        ("75", "IU/L", "U/L", Reading(None, None, UNIT_MISMATCH)),  # [IU] and U are not equated by the table
        # a unit the table lacks: unknown on either side, even spelled the same
        ("5", "furlong/fortnight", "mg/dL", Reading(None, None, UNIT_MISMATCH)),
        ("5", "mg/dL", "furlong/fortnight", Reading(None, None, UNIT_MISMATCH)),
        ("5", "x10^3/mm3", "x10^3/mm3", Reading(None, None, UNIT_MISMATCH)),
        ("5", "mg/dL", None, Reading(None, None, UNIT_MISMATCH)),  # a row unit and a lookup without one
        ("5", "mg/dL", "", Reading(None, None, UNIT_MISMATCH)),
        ("5", "M", "m", Reading(None, None, UNIT_MISMATCH)),  # molar is not metre: bare symbols are not case-folded
        # text that is no number
        ("陰性", "mg/dL", "mg/dL", Reading(None, None, UNKNOWN_VALUE)),
        ("see note", "mg/L", "mg/dL", Reading(None, None, UNIT_MISMATCH)),  # the units are judged first
        ("", None, "mg/dL", Reading(None, None, UNKNOWN_VALUE)),
        ("1.5E1", "mg/dL", "mg/dL", Reading(None, None, UNKNOWN_VALUE)),  # no exponent forms
        ("NaN", "mg/dL", "mg/dL", Reading(None, None, UNKNOWN_VALUE)),
        (float("nan"), "mg/dL", "mg/dL", Reading(None, None, UNKNOWN_VALUE)),
        (float("inf"), None, "mg/dL", Reading(None, None, UNKNOWN_VALUE)),
    ],
)
def test_read(text: object, row: str | None, lookup: str | None, expected: Reading) -> None:
    assert read(text, row, lookup) == expected


def test_ucum_spellings() -> None:
    assert ucum("mg/dl") == ucum("MG/DL") == ucum("mg / dL") == "mg/dL"
    assert ucum("10^9/L") == ucum("x10^3/µL") == "10*3/uL"
    assert ucum("万/µL") == "10*4/uL"
    assert ucum("mL/min/1.73m2") == "mL/min/{1.73_m2}"
    for bare in ("M", "S", "MM", "G", "KG", "CM"):  # bare symbols are never case-folded
        assert ucum(bare) is None, bare
    assert ucum("Mg/dL") == "mg/dL"  # a quotient: hospital exports upper-case the first letter
    assert ucum(None) is None and ucum("") is None and ucum("furlong") is None


def test_no_two_units_share_a_spelling() -> None:
    """Every spelling, as written and case-folded, names one code: a fold can never turn one unit into another."""
    seen: dict[str, str] = {}
    for code, spellings in UCUM.items():
        for s in (code, *spellings):
            key = unicodedata.normalize("NFKC", s).replace(" ", "")
            assert seen.setdefault(key, code) == code, (s, seen[key], code)
            if "/" in key:
                assert seen.setdefault("fold:" + key.lower(), code) == code, (s, code)


ALL_SPELLINGS = sorted({s for code, sp in UCUM.items() for s in (code, *sp)})
ODD_UNITS = [
    "",
    " ",
    "furlong",
    "mg/dL ",
    "MG/DL",
    "mmhg",
    "mm",
    "M",
    "S",
    "1",
    "x",
    "mg/d L",
    "IU",
    "/HPF",
    "ｍｇ／ｄＬ",
]


def test_no_path_converts_exhaustively() -> None:
    """Every pair of units the table knows (and some it does not), on a censored and an exact value: the value that
    comes back is the parsed number itself or nothing. Nothing is ever scaled."""
    texts = ["5", "<0.3", "1,000", "12.5 H"]
    for row, lookup in itertools.product(ALL_SPELLINGS + ODD_UNITS, ALL_SPELLINGS + ODD_UNITS):
        for t in texts:
            got = read(t, row, lookup)
            parsed = labvalue.parse(t)
            assert parsed is not None
            if got.value is None:
                assert got.reason in (UNIT_MISMATCH, UNKNOWN_VALUE) and got.comparator is None
            else:
                assert (got.value, got.comparator) == parsed and got.reason is None
                same = ucum(row) is not None and ucum(row) == ucum(lookup)
                assert same or not str(row).strip(), (row, lookup)


def test_random_units_never_convert() -> None:
    rnd = random.Random(31)
    alphabet = "mgdLlµuμ/%0123456789*^xIU[]{}. kKMSsﾐｸﾛ万"
    for _ in range(20000):
        row = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 8)))
        lookup = rnd.choice([*ALL_SPELLINGS, row, "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 8)))])
        got = read("7.5", row, lookup)
        assert got.value in (None, 7.5)
        if got.value is not None and row.strip():
            assert ucum(row) is not None and ucum(row) == ucum(lookup)


def test_never_converts_property() -> None:
    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is not a dev dependency yet (T-118 remains)")
    st = pytest.importorskip("hypothesis.strategies")
    units = st.one_of(st.sampled_from(ALL_SPELLINGS + ODD_UNITS), st.text(max_size=10), st.none())

    def prop(v: float, row: str | None, lookup: str | None) -> None:
        text = f"{v:.4f}"  # a lab value as written (no exponent)
        got = read(text, row, lookup)
        assert got.value in (None, float(text))
        if got.value is None:
            assert got.reason == UNIT_MISMATCH
        elif row is not None and unicodedata.normalize("NFKC", row).strip():
            assert ucum(row) is not None and ucum(row) == ucum(lookup)

    hypothesis.settings(max_examples=1000, deadline=None)(
        hypothesis.given(st.floats(min_value=0, max_value=1e6, allow_nan=False), units, units)(prop)
    )()


# ------------------------------------------------------------------------------------------------ reason codes
def test_the_two_codes_have_words_in_three_languages() -> None:
    for code in (UNIT_MISMATCH, UNKNOWN_VALUE):
        assert code in CODES and set(LABELS[code]) == {"en", "ja", "zh-TW"}
        assert all(LABELS[code][lang].strip() for lang in ("en", "ja", "zh-TW"))
        assert label(code, "ja") == LABELS[code]["ja"] and label(code, "zh-TW") == LABELS[code]["zh-TW"]
        assert code_of(code, "unknown") == code
    assert code_of("unit mismatch: CRP mg/L vs mg/dL", "unknown") == UNIT_MISMATCH


def test_the_page_renderers_have_words_for_the_codes() -> None:
    """The two renderers (``reason_label``, i.e. :func:`tb_common.reasons.label`, and the site set-up page's
    ``t_reason``) would show the codes in the page language. This does **not** show them on a page: the SQL engine
    does not yet put ``unit_mismatch`` into an unknown value atom's evidence (D-215 "Not done"), so a mismatched row is
    unknown on the page with the reason ``data_gap`` today."""
    from console.site_pages import t_reason

    for code in (UNIT_MISMATCH, UNKNOWN_VALUE):
        for lang in ("en", "ja", "zh-TW"):
            assert t_reason(lang, code) == label(code, lang) == LABELS[code][lang]


# ------------------------------------------------------------------------------------------------ the adapter
LOOKUPS = (
    "local_code,system,code,display,ucum,factor,category,value_type,answers,profile,verified,source_unit\n"
    "CRP,loinc,1988-5,CRP,mg/dL,1,laboratory,quantity,,,yes,\n"
    "CRP10,loinc,1988-5,CRP,mg/L,10,laboratory,quantity,,,yes,mg/dL\n"
    "CRPX,loinc,1988-5,CRP,mg/L,10,laboratory,quantity,,,yes,\n"
    "HBS,loinc,5196-1,HBsAg,,1,laboratory,coded,POS:LA6576-8|Positive,,yes,\n"
)


def _mapper(tmp_path: Path, unit_column: str | None = "u") -> tuple[Mapper, ResourceSpec]:
    args: dict[str, object] = {"builder": "lab_value", "lookup": "lab", "key": "local_code", "column": "v"}
    if unit_column:
        args["unit_column"] = unit_column
    m = _mapping(
        tmp_path,
        [
            {
                "type": "Observation",
                "table": "t",
                "id": {"hid": "id"},
                "where": [{"lookup": {"name": "lab", "key": "local_code", "field": "code"}, "not_empty": True}],
                "elements": {
                    "code.coding[0].system": {"template": "{sys.loinc}"},
                    "code.coding[0].code": {"lookup": {"name": "lab", "key": "local_code", "field": "code"}},
                    "subject.reference": {"ref": {"type": "Patient", "pid": "mrn"}},
                    "effectiveDateTime": {"const": "2026-03-01"},
                    "$merge": args,
                },
            }
        ],
        LOOKUPS,
    )
    return Mapper(m, KEY, "S"), m.resources[0]


def test_a_crp_in_mg_l_against_an_mg_dl_lookup_has_no_value(tmp_path: Path) -> None:
    """Acceptance (1), the adapter half: no value[x] (the engines read it as unknown), the reason named, the row's
    own text kept for the person who checks."""
    mp, rs = _mapper(tmp_path)
    res = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP", "v": "5", "u": "mg/L"})
    assert res is not None
    assert not any(k.startswith("value") for k in res)
    assert res["dataAbsentReason"] == {"coding": [{"system": DATA_ABSENT, "code": "error"}], "text": UNIT_MISMATCH}
    assert res["note"] == [{"text": "5 mg/L"}]
    row = Flattener().observation(res)
    assert row["value_num"] is None and row["value_cmp"] is None and row["code"] == "1988-5"


def test_the_same_unit_reads_as_before(tmp_path: Path) -> None:
    mp, rs = _mapper(tmp_path)
    same = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP", "v": "<0.3", "u": "mg/dl"})
    assert same is not None and same["valueQuantity"]["value"] == 0.3 and same["valueQuantity"]["comparator"] == "<"
    blank = mp.map_row(rs, {"id": "2", "mrn": "M1", "local_code": "CRP", "v": "1.2", "u": ""})
    assert blank is not None and blank["valueQuantity"]["value"] == 1.2 and "dataAbsentReason" not in blank


def test_a_declared_source_unit_and_factor(tmp_path: Path) -> None:
    """``source_unit`` mg/dL, ``ucum`` mg/L, factor 10 (the site's declared conversion, D-149): an mg/dL row is
    converted by the lookup; an mg/L row is a mismatch. With a factor and no source_unit, a row unit cannot be
    checked: no value."""
    mp, rs = _mapper(tmp_path)
    ok = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP10", "v": "1.25", "u": "mg/dL"})
    assert ok is not None and ok["valueQuantity"]["value"] == 12.5 and ok["valueQuantity"]["unit"] == "mg/L"
    bad = mp.map_row(rs, {"id": "2", "mrn": "M1", "local_code": "CRP10", "v": "12.5", "u": "mg/L"})
    assert bad is not None and "valueQuantity" not in bad and bad["dataAbsentReason"]["text"] == UNIT_MISMATCH
    unk = mp.map_row(rs, {"id": "3", "mrn": "M1", "local_code": "CRPX", "v": "1.25", "u": "mg/dL"})
    assert unk is not None and "valueQuantity" not in unk and unk["dataAbsentReason"]["text"] == UNIT_MISMATCH


def test_without_unit_column_nothing_changes(tmp_path: Path) -> None:
    """A mapping that names no unit column reads exactly as before D-215 (every shipped mapping)."""
    mp, rs = _mapper(tmp_path, unit_column=None)
    res = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP", "v": "5", "u": "mg/L"})
    assert res is not None and res["valueQuantity"]["value"] == 5 and res["valueQuantity"]["unit"] == "mg/dL"


def test_coded_answers_are_not_unit_checked(tmp_path: Path) -> None:
    mp, rs = _mapper(tmp_path)
    res = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "HBS", "v": "pos", "u": "mg/L"})
    assert res is not None and res["valueCodeableConcept"]["coding"][0]["code"] == "LA6576-8"


@pytest.mark.parametrize("raw", ["1.5E1", "2.0E+03", "5.", "1_5", "5e0", "NaN", "nan", "Infinity", "-inf", "sNaN"])
def test_a_unit_checked_row_never_takes_a_number_labvalue_cannot_read(tmp_path: Path, raw: str) -> None:
    """Fable B1: with ``unit_column`` the value is labvalue's reading only; ``Decimal`` forms (exponents, ``5.``,
    ``1_5``, ``NaN``) stay text, so the engines read them as unknown, in the right unit or not."""
    mp, rs = _mapper(tmp_path)
    for code, unit in (("CRP", "mg/dL"), ("CRP10", "mg/dL"), ("CRP", "mg/L")):
        res = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": code, "v": raw, "u": unit})
        assert res is not None and "valueQuantity" not in res, (raw, code, unit)
        assert Flattener().observation(res)["value_num"] is None


def test_the_factor_applies_only_to_a_checked_reading(tmp_path: Path) -> None:
    """CRP10 (source mg/dL, factor 10 to mg/L): 1.25 mg/dL is 12.5 mg/L; 1.25E0 is text; 1.25 mg/L is a mismatch."""
    mp, rs = _mapper(tmp_path)
    ok = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP10", "v": "1.25", "u": "mg/dL"})
    assert ok is not None and ok["valueQuantity"]["value"] == 12.5
    exp = mp.map_row(rs, {"id": "2", "mrn": "M1", "local_code": "CRP10", "v": "1.25E0", "u": "mg/dL"})
    assert exp is not None and exp.get("valueString") == "1.25E0" and "valueQuantity" not in exp
    bad = mp.map_row(rs, {"id": "3", "mrn": "M1", "local_code": "CRP10", "v": "1.25E0", "u": "mg/L"})
    assert bad is not None and bad["dataAbsentReason"]["text"] == UNIT_MISMATCH


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_without_unit_column_nan_is_text_not_a_value(tmp_path: Path, raw: str) -> None:
    mp, rs = _mapper(tmp_path, unit_column=None)
    res = mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP", "v": raw})
    assert res is not None and res.get("valueString") == raw and "valueQuantity" not in res


def test_a_declared_unit_column_the_source_lacks_stops_the_mapping(tmp_path: Path) -> None:
    """Fable L3: never a silent skip of the unit check."""
    from adapter.mapping.engine import MappingError

    mp, rs = _mapper(tmp_path)
    with pytest.raises(MappingError, match="unit_column 'u'"):
        mp.map_row(rs, {"id": "1", "mrn": "M1", "local_code": "CRP", "v": "5"})


def test_the_shipped_mapping_checks_the_row_unit() -> None:
    """Fable H2: the TW Core demo mapping (which the JP SS-MIX2 and the CSV / CGRD templates extend) names the lab
    table's ``unit`` column; its lookup declares CRP's source unit (mg/dL, factor 10 to mg/L)."""
    from adapter.mapping.engine import Mapping

    root = Path(__file__).resolve().parents[2] / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"
    m = Mapping.load(root)
    rs = next(r for r in m.resources if r.type == "Observation" and r.table == "lab")
    mp = Mapper(m, KEY, "S")
    row = {"lab_no": "L1", "mrn": "M1", "local_code": "CRP", "item_name": "CRP", "sample_datetime": "2026-03-01 09:00"}
    ok = mp.map_row(rs, row | {"result_value": "1.25", "unit": "mg/dL"})
    assert ok is not None and ok["valueQuantity"]["value"] == 12.5 and ok["valueQuantity"]["unit"] == "mg/L"
    bad = mp.map_row(rs, row | {"result_value": "12.5", "unit": "mg/L"})
    assert bad is not None and "valueQuantity" not in bad and bad["dataAbsentReason"]["text"] == UNIT_MISMATCH
    tjc = mp.map_row(rs, row | {"local_code": "TJC28", "result_value": "4", "unit": "{count}"})
    assert tjc is not None and tjc["valueQuantity"]["value"] == 4
