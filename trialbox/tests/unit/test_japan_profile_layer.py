"""The Japan profile as one layer (plan 10 card 10C-25, commitment C-7, D-1250).

* The layer lists P1 to P16 by name, and says by name which are declared but not built.
* Every value of the layer is read by a reader it names, and every reader exists.
* Switching the layer off and on changes no code path: the same calls run for every country and only the data they
  read differs. A JP site with the layer off is a site of a country without one; the same layer under a made-up
  country code gives the same results by the same function calls.
* A setting a person made wins over the layer, and the layer is never a run-time default for an unset setting.
* The site profile's load records the layer's version and digest; a country without a layer records nothing new.
* No Japan behaviour is added outside the layer: a country literal in product code is held to the list below.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import sys
import tokenize
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any

import pytest
from tb_common import committees, country_layer, dates, derived, site_country, workdays
from tb_common.country_layer import DECLARED, LayerError

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / "libs" / "tb_common" / "japan_profile.json"

P1_TO_P16 = {
    "P1": "Legal pack",
    "P2": "Study kinds",
    "P3": "Committees",
    "P4": "Roles",
    "P5": "Words",
    "P6": "Forms",
    "P7": "Masters",
    "P8": "Chart reading",
    "P9": "Dates and calendar",
    "P10": "Privacy guard",
    "P11": "Patient approach",
    "P12": "Money",
    "P13": "Registries",
    "P14": "Interoperability",
    "P15": "Procurement and security",
    "P16": "Accessibility and type",
}
# declared in the layer, not built on master: the card that builds one moves it out of this list
DECLARED_NOT_BUILT = {
    "P4": "Roles",
    "P6": "Forms",
    "P12": "Money",
    "P13": "Registries",
    "P15": "Procurement and security",
}


def _jp() -> country_layer.Layer:
    return country_layer.layer("JP")


# ------------------------------------------------------------------------------------------------ P1 to P16
def test_the_japan_profile_lists_p1_to_p16_by_name() -> None:
    lay = _jp()
    assert lay.on and lay.country == "JP" and lay.version == "1.0.0"
    assert {pid: p.name for pid, p in lay.parts.items()} == P1_TO_P16
    assert tuple(lay.parts) == tuple(P1_TO_P16)  # in order


def test_the_parts_declared_but_not_built_are_named() -> None:
    lay = _jp()
    assert {pid: p.name for pid, p in lay.parts.items() if p.state == DECLARED} == DECLARED_NOT_BUILT
    for pid in DECLARED_NOT_BUILT:
        p = lay.parts[pid]
        assert not p.values and not p.readers and p.not_built  # nothing switched on, and what is missing said


def test_every_part_not_wholly_built_says_what_is_missing_and_the_open_questions_keep_todays_behaviour() -> None:
    lay = _jp()
    for p in lay.parts.values():
        assert p.state == "built" or p.not_built, p.id
    # the owner's open questions are carried, each with today's behaviour (card 10C-25, point 5)
    asked = " ".join(q for p in lay.parts.values() for q in p.open_questions)
    assert "head-of-institution permission" in asked and "running study" in asked and "missing assent" in asked
    assert lay.value("P3", "committees")["study_kinds"]["shishin"]["needs"] == ["approval", "permission"]


def _reader(name: str) -> Any:
    mod, _, attr = name.partition(":")
    return getattr(importlib.import_module(mod), attr)


def test_every_reader_exists_and_reads_its_parts_values() -> None:
    for p in _jp().parts.values():
        for r in p.readers:
            assert _reader(r) is not None, r
        sources = "".join(Path(sys.modules[r.partition(":")[0]].__file__ or "").read_text(encoding="utf-8")
                          for r in p.readers)  # fmt: skip
        for key in p.values:
            assert f'"{p.id}", "{key}"' in sources, f"{p.id}.{key}: no reader asks for it"


def test_the_layer_is_versioned_and_its_digest_is_the_files() -> None:
    import hashlib

    lay = _jp()
    assert lay.digest == hashlib.sha256(LAYER.read_bytes()).hexdigest()
    assert country_layer.stamp("jp") == {"country": "JP", "version": "1.0.0", "digest": lay.digest}
    assert country_layer.stamp("TW") is None and country_layer.stamp("") is None and country_layer.stamp(None) is None


@pytest.mark.parametrize(
    ("edit", "says"),
    [
        (lambda d: d["parts"].pop("P16"), "exactly P1 to P16"),
        (lambda d: d["parts"]["P4"].update(values={"x": 1}, readers=["tb_common.derived:egfr_for_site"]),
         "declared, not built, yet"),
        (lambda d: d["parts"]["P8"].update(name="Chart"), "name 'Chart'"),
        (lambda d: d.update(colour="red"), "unknown key 'colour'"),
        (lambda d: d["parts"]["P7"].pop("readers"), "values and readers go together"),
        (lambda d: d["parts"]["P9"].pop("not_built"), "'not_built' says what is missing"),
        (lambda d: d.update(version="1.0"), "MAJOR.MINOR.PATCH"),
        (lambda d: d.update(country="Japan"), "two capital letters"),
        (lambda d: d.update(format="tb-site-profile/1"), "format is"),
        (lambda d: d["parts"]["P2"].update(cards=["C-4"]), "'C-4' is not one"),
    ],
)  # fmt: skip
def test_a_layer_that_cannot_be_used_is_refused_with_its_reason(edit: Callable[[dict[str, Any]], Any],
                                                                says: str) -> None:  # fmt: skip
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    edit(doc)
    with pytest.raises(LayerError, match=says.replace("(", r"\(").replace(")", r"\)")):
        country_layer.parse(json.dumps(doc).encode(), "japan_profile.json")


def test_two_layers_for_one_country_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(country_layer, "FILES", ("japan_profile.json", "japan_profile.json"))
    country_layer.layers.cache_clear()
    try:
        with pytest.raises(LayerError, match="a second layer for JP"):
            country_layer.layers()
    finally:
        monkeypatch.undo()
        country_layer.layers.cache_clear()


# ------------------------------------------------------------------------------------- on and off, same path
@contextmanager
def _layers(found: dict[str, country_layer.Layer]) -> Iterator[None]:
    """The shipped layers replaced by ``found`` for the block (the readers' caches cleared before and after)."""
    saved = country_layer.layers
    country_layer.layers = lambda: found  # type: ignore[assignment]
    workdays.holidays.cache_clear()
    try:
        yield
    finally:
        country_layer.layers = saved
        workdays.holidays.cache_clear()


def _renamed(code: str) -> country_layer.Layer:
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    doc["country"] = code
    return country_layer.parse(json.dumps(doc, ensure_ascii=False).encode(), f"{code.lower()}_profile.json")


def _calls(country: str) -> dict[str, Any]:
    """Every reader of the layer, called for a site of ``country``: what each gives."""
    from datacore import lifecycle

    cal = workdays.for_country(country, {})
    defaults = dataclasses.asdict(site_country.from_layer(country.lower()))
    defaults.pop("country")
    return {
        "egfr": derived.egfr_for_site(country),
        "sae_rule_set": lifecycle.country_default(country),
        "committees_on": committees.on(country),
        "defaults": defaults,
        "holidays": None if cal.holidays is None else sorted(cal.holidays.days.items())[:5],
        "new_year": cal.new_year,
        "new_year_from": cal.new_year_from,
        "working_2027_01_04": cal.is_working_day(__import__("datetime").date(2027, 1, 4)),
        "working_2026_12_30": cal.is_working_day(__import__("datetime").date(2026, 12, 30)),
        "stems": bool(country_layer.value(country, "P7", "ingredient_stems")),
    }


def _traced(country: str) -> tuple[dict[str, Any], list[str]]:
    """:func:`_calls` and the product functions it ran, in order (``module.function``; tests' own frames left out)."""
    ran: list[str] = []
    product = (str(ROOT / "libs"), str(ROOT / "services"))

    def prof(frame: FrameType, event: str, _arg: Any) -> None:
        if event == "call" and frame.f_code.co_filename.startswith(product):
            ran.append(f"{Path(frame.f_code.co_filename).stem}.{frame.f_code.co_name}")

    # warm the imports and caches so both runs see the same work
    _calls(country)
    sys.setprofile(prof)
    try:
        got = _calls(country)
    finally:
        sys.setprofile(None)
    return got, ran


def test_switching_the_layer_off_makes_a_japanese_site_a_site_of_a_country_without_one() -> None:
    with _layers({}):
        off, off_ran = _traced("JP")
        us, us_ran = _traced("US")
    assert off == us and off_ran == us_ran
    assert off["egfr"] == "egfr_ckd_epi" and off["sae_rule_set"] == "" and not off["committees_on"]
    assert off["holidays"] is None and off["new_year"] is None and not off["stems"]
    assert off["defaults"]["printed_dates"] == "western" and not off["defaults"]["consent_proxy"]


def test_switching_it_on_turns_on_p1_to_p16_from_data() -> None:
    on, _ran = _traced("JP")
    assert on["egfr"] == "egfr_jsn" and on["sae_rule_set"] == "jp_gcp_ii" and on["committees_on"]
    assert on["holidays"] and on["new_year"] == ((12, 29), (1, 3)) and on["new_year_from"] == "layer"
    assert not on["working_2026_12_30"] and on["working_2027_01_04"] and on["stems"]
    d = on["defaults"]
    assert (d["locale"], d["retention_rules"], d["data_source_type"], d["printed_dates"], d["year_basis"]) == (
        "ja", "jp", "ssmix2", "both", "fiscal")  # fmt: skip
    assert d["consent_proxy"] and d["mapping"] == "mapping/jp_core/ssmix2_site.yaml" and d["one_zone"]


def test_the_same_layer_under_another_country_code_runs_the_same_calls_with_the_same_results() -> None:
    """No code tests the string JP: the layer's data, under a made-up code, does exactly what it does for Japan."""
    jp, jp_ran = _traced("JP")
    with _layers({"XQ": _renamed("XQ")}):
        xq, xq_ran = _traced("XQ")
        assert not committees.on("JP")  # and Japan, without its layer, is off
    assert xq == jp and xq_ran == jp_ran


def test_the_same_functions_run_with_the_layer_on_and_off() -> None:
    """The readers are the same functions on and off; only what the layer gives them differs. The functions that run
    only with the layer on are the ones that read the data it turned on (the holiday file, the break, the site's
    changes to them), never a branch on a country."""
    _on, on_ran = _traced("JP")
    with _layers({}):
        _off, off_ran = _traced("JP")
    assert set(off_ran) <= set(on_ran)
    assert set(on_ran) - set(off_ran) == {
        "workdays.country_break", "workdays.parse_break", "workdays.settings_problems", "workdays._days",
        "workdays._per_year", "workdays.<genexpr>", "workdays._in_break",
    }  # fmt: skip


# ------------------------------------------------------------------------------------------ who wins
def test_a_new_year_break_the_site_set_wins_over_the_layers() -> None:
    cal = workdays.for_country("JP", {"TB_NEW_YEAR_BREAK": "12-28/01-04"})
    assert cal.new_year == ((12, 28), (1, 4)) and cal.new_year_from == "site"
    assert workdays.for_country("JP", {"TB_NEW_YEAR_BREAK": "none"}).new_year_from == "site"
    # a setting that cannot be read is not used: the layer's break stands, and the setting is a problem
    bad = workdays.for_country("JP", {"TB_NEW_YEAR_BREAK": "29 Dec"})
    assert bad.new_year == ((12, 29), (1, 3)) and bad.new_year_from == "layer" and bad.problems


def test_the_layer_is_never_a_run_time_default_for_a_setting_left_unset() -> None:
    """D-1229: an installed box whose settings do not name the printed dates prints as before, even in Japan; the
    layer's values are what the set-up offers and writes, and a value written wins."""
    from datacore import proxy_consent

    assert _jp().value("P9", "printed_dates") == "both" and _jp().value("P11", "consent_proxy") is True
    unset = type("Site", (), {"tz": "Asia/Tokyo"})()
    assert dates.site_dates(unset) == ("western", "calendar")
    chosen = type("Site", (), {"tz": "Asia/Tokyo", "printed_dates": "era", "year_basis": "calendar"})()
    assert dates.site_dates(chosen) == ("era", "calendar")  # the site's own answer, not the layer's "both"
    assert not proxy_consent.is_on({}) and proxy_consent.is_on({"TB_CONSENT_PROXY": "on"})
    assert not proxy_consent.is_on({"TB_CONSENT_PROXY": "off"})


def test_the_ingredient_stems_switch_and_the_sites_own_file_are_read_as_before(monkeypatch: pytest.MonkeyPatch,
                                                                                tmp_path: Path) -> None:  # fmt: skip
    from criteria_compiler.terminology import resolver

    class Cfg:
        class env:  # noqa: N801
            tz = "Asia/Tokyo"

        class settings:  # noqa: N801
            class site:  # noqa: N801
                locale = "ja"

    monkeypatch.setattr("tb_common.config.get_config", lambda: Cfg)
    term = type("T", (), {"ingredients": None})()
    assert resolver.jp_ingredients(term).ingredients
    with _layers({}):
        term = type("T", (), {"ingredients": None})()
        assert resolver.jp_ingredients(term).ingredients is None


# ---------------------------------------------------------------------------------- versions and audit
def _profile(tmp_path: Path, country: str) -> Any:
    from tb_common import site_profile

    src = ROOT / "services" / "adapter" / "mapping" / "profile" / ("synthetic-jp-ss" if country == "jp" else
                                                                   "synthetic-tw-a")  # fmt: skip
    return site_profile.load(src)


def test_the_site_profiles_load_records_the_layers_version(tmp_path: Path) -> None:
    from adapter import site_profile as asp

    p = _profile(tmp_path, "jp")
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    ch = asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit)
    assert ch is not None and ch["layer"] == country_layer.stamp("JP") and ch["old_layer"] is None
    assert asp.read_record(lake)["active"]["layer"] == country_layer.stamp("JP")
    assert asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit) is None  # nothing new
    # the same profile under another layer version is a change of its own, recorded with both
    newer = dataclasses.replace(_jp(), version="1.1.0", digest="f" * 64)
    with _layers({"JP": newer}):
        again = asp.activate(p, lake, site_id=p.site_id, by="steward-b", audit_dir=audit)
    assert again is not None and again["old_layer"]["version"] == "1.0.0" and again["layer"]["version"] == "1.1.0"
    assert again["old_digest"] == again["new_digest"] == p.digest


def test_a_country_without_a_layer_records_exactly_what_it_did_before(tmp_path: Path) -> None:
    from adapter import site_profile as asp

    p = _profile(tmp_path, "tw")
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    ch = asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit)
    assert ch is not None and "layer" not in ch and "old_layer" not in ch
    assert set(ch) == {"profile", "site", "old_version", "new_version", "old_digest", "new_digest", "old_profile",
                       "direction", "synthetic", "rows_changed", "row_changes", "copy_sha", "at", "by"}  # fmt: skip
    assert "layer" not in asp.read_record(lake)["active"]


# ------------------------------------------------------------------- no Japan behaviour outside the layer
# Every string literal in product code (libs/, services/, and the box's set-up in tools/box/ and
# tools/settings_wizard.py) that names Japan: the file, the literal, how many, and why it is not a behaviour of its
# own. A new one fails here: put the behaviour's data in the layer (libs/tb_common/japan_profile.json) and read it
# through tb_common.country_layer.value, or, if it is not a behaviour, add it here with the reason.
ALLOWED: dict[tuple[str, str], tuple[int, str]] = {
    ("libs/tb_common/derived.py", "Asia/Tokyo"): (1, "country_of: the one reading of a zone as a country"),
    ("libs/tb_common/derived.py", "Japan"): (1, "country_of: the zone's legacy alias"),
    ("libs/tb_common/derived.py", "JP"): (2, "country_of's answers (the docstring names them)"),
    ("libs/tb_common/refdata_jp.py", "JP"): (8, "P7 masters: the Japanese reference data's own source labels"),
    ("libs/tb_common/refdata_jp.py", "Japan"): (1, "P7 masters: a source's name"),
    ("libs/tb_common/retention.py", "jp"): (1, "P1: the retention rules the layer names (retention_rules: jp)"),
    ("libs/tb_common/site_country.py", "jp"): (
        3,
        "the country answers (COUNTRIES, TABLE's key) and the layer TABLE reads",
    ),
    ("services/console/i18n_firstrun.py", "Japan"): (1, "the country question's words"),
    ("services/datacore/lifecycle.py", "JP"): (4, "P2: the SAE rule sets' own country labels (data)"),
    ("services/datacore/lifecycle.py", "jp"): (1, "P2: the rule sets' legacy box-wide alias (D-277)"),
    ("services/orchestrator/scenarios/consent.py", "jp"): (
        1,
        "a language word: jp read as ja in a scenario's language list",
    ),
    ("services/sitesetup/ocr.py", "jpn"): (1, "the OCR engine's language name"),
    ("tools/box/plan.py", "Asia/Tokyo"): (
        1,
        "an answers file without a country: retention rules from the zone, as before 10K-1",
    ),
    ("tools/box/plan.py", "jp"): (1, "the same line: the retention rules' key"),
    ("tools/settings_wizard.py", "jp"): (1, "an answers file without a country: retention from the language (LEGACY)"),
}
JAPAN = ("jp", "jpn", "japan", "asia/tokyo")


def _japan_literals() -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()
    files = [*sorted((ROOT / "libs").rglob("*.py")), *sorted((ROOT / "services").rglob("*.py")),
             *sorted((ROOT / "tools" / "box").rglob("*.py")), ROOT / "tools" / "settings_wizard.py"]  # fmt: skip
    for f in files:
        if "generated" in f.parts or "tests" in f.parts or not f.is_file():
            continue
        with f.open(encoding="utf-8") as fh:
            for tok in tokenize.generate_tokens(fh.readline):
                if tok.type != tokenize.STRING:
                    continue
                try:
                    v = ast.literal_eval(tok.string)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(v, str) and v.strip().lower() in JAPAN:
                    found[(f.relative_to(ROOT).as_posix(), v)] += 1
    return found


def test_no_japan_behaviour_is_added_outside_the_layer() -> None:
    found = _japan_literals()
    new = {k: n for k, n in found.items() if n > ALLOWED.get(k, (0, ""))[0]}
    assert not new, (
        f"a Japan literal outside the layer: {new}. Put the behaviour's data in libs/tb_common/japan_profile.json "
        "(its part P1 to P16) and read it with tb_common.country_layer.value; if it is not a behaviour, list it in "
        "ALLOWED with the reason."
    )
    gone = {k for k, (n, _why) in ALLOWED.items() if found.get(k, 0) < n}
    assert not gone, f"ALLOWED lists more than the code holds (tighten it): {gone}"


def test_the_guard_sees_a_seventeenth_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new `if country == "JP":` in product code is caught by the scan."""
    src = tmp_path / "libs" / "tb_common"
    src.mkdir(parents=True)
    (src / "new_switch.py").write_text('def f(country):\n    return country == "JP"\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _japan_literals() == Counter({("libs/tb_common/new_switch.py", "JP"): 1})
