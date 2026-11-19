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
import re
import sys
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


def test_the_guard_the_layout_rules_and_the_claims_lint_are_on_everywhere_not_by_country() -> None:
    """P10 (the privacy guard), P16 (the CJK layout rules) and P5's device-claims lint run by the text's characters or
    language at every site: the layer lists them as such and switches nothing of them."""
    lay = _jp()
    for pid, word in (("P10", "guard"), ("P16", "CJK layout"), ("P5", "device-claims")):
        assert lay.parts[pid].everywhere.startswith(country_layer.EVERYWHERE) and word in lay.parts[pid].everywhere
    assert not lay.parts["P10"].values and not lay.parts["P16"].values
    assert "phi_guard" not in str(lay.parts["P5"].readers) and "wording" not in str(lay.parts["P5"].readers)


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
        (lambda d: d["parts"]["P8"]["values"].pop("egfr") and d["parts"]["P8"]["values"].update(x="y"),
         "'egfr' is missing"),
        (lambda d: d["parts"]["P7"]["values"].update(ingredient_stems="yes"), "ingredient_stems: 'yes' is not a bool"),
        (lambda d: d["parts"]["P9"]["values"].update(holiday_list="../holidays_jp.csv"), "holiday_list: '../"),
        (lambda d: d["parts"]["P9"]["values"].update(new_year_break="29 Dec"), "new_year_break: '29 Dec'"),
        (lambda d: d["parts"]["P3"]["values"].update(committees={}), "committees: {} is not a dict"),
    ],
)  # fmt: skip
def test_a_layer_that_cannot_be_used_is_refused_with_its_reason(edit: Callable[[dict[str, Any]], Any],
                                                                says: str) -> None:  # fmt: skip
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    edit(doc)
    with pytest.raises(LayerError, match=says.replace("(", r"\(").replace(")", r"\)")):
        country_layer.parse(json.dumps(doc).encode(), "japan_profile.json")


# ------------------------------------------------------------------------- the values moved, unchanged
# Master's constants before this card (origin/master 0de6b1d0), copied here as they were written there, one per value
# moved into the layer: the layer must give exactly these.
MASTER: dict[str, Any] = {
    "derived.EGFR_BY_COUNTRY['JP']": ("P8", "egfr", "egfr_jsn"),
    "lifecycle.COUNTRY_DEFAULT['JP']": ("P2", "sae_rule_set", "jp_gcp_ii"),
    "workdays.NEW_YEAR_BREAK['JP']": ("P9", "new_year_break", ((12, 29), (1, 3))),
    "workdays.holidays: refdata_src/holidays_<jp>.csv": ("P9", "holiday_list", "holidays_jp.csv"),
    "resolver.jp_ingredients: country == 'JP'": ("P7", "ingredient_stems", True),
    "site_country.TABLE['jp'].locale": ("P5", "report_language", "ja"),
    "site_country.TABLE['jp'].one_zone": ("P14", "one_zone", True),
    "site_country.TABLE['jp'].retention_rules": ("P1", "retention_rules", "jp"),
    "site_country.TABLE['jp'].data_source_type": ("P14", "data_source_type", "ssmix2"),
    "site_country.TABLE['jp'].mapping": ("P14", "mapping", "mapping/jp_core/ssmix2_site.yaml"),
    "site_country.TABLE['jp'].printed_dates": ("P9", "printed_dates", "both"),
    "site_country.TABLE['jp'].year_basis": ("P9", "year_basis", "fiscal"),
    "site_country.TABLE['jp'].consent_proxy": ("P11", "consent_proxy", True),
    # japan_profile.json's "committees" on master: sha256 of its JSON with sorted keys
    "committees: japan_profile.json['committees']": (
        "P3", "committees", "be7e8b4427b94dd95abcd46e6547e55b83f0549d29db23df58f24f7cf6802b96"),
}  # fmt: skip


@pytest.mark.parametrize("moved", sorted(MASTER))
def test_each_value_moved_into_the_layer_is_masters(moved: str) -> None:
    import hashlib

    part, key, was = MASTER[moved]
    got = _jp().value(part, key)
    if key == "new_year_break":
        got = workdays.parse_break(got)
    if key == "committees":
        got = hashlib.sha256(json.dumps(got, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert got == was, moved


def test_the_set_up_row_for_japan_is_masters_whole() -> None:
    assert site_country.TABLE["jp"] == site_country.CountryDefaults(
        "jp", "ja", True, "jp", "ssmix2", "mapping/jp_core/ssmix2_site.yaml", (), "both", "fiscal", consent_proxy=True
    )  # master's literal row
    assert site_country.TABLE["tw"].printed_dates == "western" and not site_country.TABLE["tw"].consent_proxy


# ------------------------------------------------------------------------------------- on and off, same path
@contextmanager
def _layers(found: dict[str, country_layer.Layer]) -> Iterator[None]:
    """The shipped layers replaced by ``found`` for the block (the readers' caches cleared before and after)."""
    saved = country_layer._shipped, country_layer.FILES
    country_layer._shipped = lambda code: found.get(code, country_layer.NONE)  # type: ignore[assignment]
    country_layer.FILES = {code: lay.file for code, lay in found.items()}
    workdays.holidays.cache_clear()
    try:
        yield
    finally:
        country_layer._shipped, country_layer.FILES = saved
        workdays.holidays.cache_clear()


@contextmanager
def _tampered(tmp_path: Path, raw: bytes | None) -> Iterator[None]:
    """The shipped Japan layer's file replaced by ``raw`` (None: no file at all) for the block."""
    folder = tmp_path / "layer"
    folder.mkdir(exist_ok=True)
    if raw is not None:
        (folder / "japan_profile.json").write_bytes(raw)
    saved = country_layer.ROOT
    country_layer.ROOT = folder
    country_layer._shipped.cache_clear()
    workdays.holidays.cache_clear()
    try:
        yield
    finally:
        country_layer.ROOT = saved
        country_layer._shipped.cache_clear()
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


def _site(**keys: Any) -> Any:
    return type("Site", (), {"tz": "Asia/Tokyo", "locale": "ja", **keys})()


def _box(site: Any, env: dict[str, str]) -> dict[str, Any]:
    """What a box gives at run time from its settings and environment: the readers of every setting the layer offers."""
    from datacore import proxy_consent

    cal = workdays.for_zone(site.tz, env)
    return {"dates": dates.site_dates(site), "consent_proxy": proxy_consent.is_on(env),
            "break": cal.new_year, "break_from": cal.new_year_from, "egfr": derived.egfr_for_site("JP"),
            "committees": committees.on("JP")}  # fmt: skip


def test_a_japanese_box_with_nothing_set_runs_as_on_master() -> None:
    """Nothing in its settings: printed dates western, the calendar year, no representative consent (D-1229, D-1232),
    and the national calendar, eGFR and committees it had on master by its zone."""
    assert _box(_site(), {}) == {"dates": ("western", "calendar"), "consent_proxy": False, "break": ((12, 29), (1, 3)),
                                 "break_from": "layer", "egfr": "egfr_jsn", "committees": True}  # fmt: skip


def test_a_japanese_box_set_up_before_this_card_runs_as_on_master() -> None:
    """Its settings as master's wizard and box plan wrote them (site.printed_dates both, site.year_basis fiscal,
    TB_CONSENT_PROXY=on): read as written; the layer adds nothing and takes nothing away."""
    written = _site(printed_dates="both", year_basis="fiscal")
    env = {"TB_TZ": "Asia/Tokyo", "TB_CONSENT_PROXY": "on"}
    assert _box(written, env) == {"dates": ("both", "fiscal"), "consent_proxy": True, "break": ((12, 29), (1, 3)),
                                  "break_from": "layer", "egfr": "egfr_jsn", "committees": True}  # fmt: skip
    # and one whose steward chose otherwise at set-up keeps the choice
    chosen = _site(printed_dates="western", year_basis="calendar")
    got = _box(chosen, {"TB_TZ": "Asia/Tokyo", "TB_CONSENT_PROXY": "off", "TB_NEW_YEAR_BREAK": "none"})
    assert got["dates"] == ("western", "calendar") and not got["consent_proxy"]
    assert got["break"] is None and got["break_from"] == "site"


def test_the_wizard_still_writes_what_masters_wrote_for_a_japanese_site() -> None:
    """Master's wizard wrote these for a Japanese site (compared across the two trees for #1187: identical but for
    the secrets it draws); the layer's set-up values are what it writes now."""
    from tools import settings_wizard

    site = {"site_id": "DEMO-K", "site_name": "Demo K (synthetic)", "internal_domains": ["hospk.test"],
            "senders": ["crc@hospk.test"], "physicians": ["pi@hospk.test"], "reviewers": ["crc@hospk.test"],
            "llm_mode": "stub", "chartno_rule": "digits:8", "mrn_regex": r"^\d{8}$",
            "mta_authserv_id": "mx.hospk.test", "console_url": "https://trialbox.hospk.test",
            "tls_hostname": "trialbox.hospk.test", "tls_mode": "internal",
            "sae_office_mailbox": "trial-office@hospk.test", "country": "jp", "data_source_host_dir": "/mnt/ssmix2"}  # fmt: skip
    s, env, _w = settings_wizard.build(site)
    assert {k: s["site"].get(k) for k in ("tz", "locale", "printed_dates", "year_basis")} == {
        "tz": "Asia/Tokyo", "locale": "ja", "printed_dates": "both", "year_basis": "fiscal"}  # fmt: skip
    assert s["data_source"]["type"] == "ssmix2" and "TB_NEW_YEAR_BREAK" not in env and env["TB_TZ"] == "Asia/Tokyo"


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


# ------------------------------------------------------------------------------- a layer that cannot be used
def _without(part: str) -> bytes:
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    doc["parts"][part].pop("values")
    return json.dumps(doc, ensure_ascii=False).encode()


def _with(edit: Callable[[dict[str, Any]], Any]) -> bytes:
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    edit(doc)
    return json.dumps(doc, ensure_ascii=False).encode()


GOOD = LAYER.read_bytes()
# what is done to the shipped file, and what the red line then says of it
TAMPERED: dict[str, tuple[bytes | None, str]] = {
    "missing": (None, "cannot be read (FileNotFoundError"),
    "empty": (b"", "not UTF-8 JSON"),
    "truncated": (GOOD[: len(GOOD) // 2], "not UTF-8 JSON"),
    "bad JSON": (b"{", "not UTF-8 JSON"),
    "BOM": (b"\xef\xbb\xbf" + GOOD, "not UTF-8 JSON"),
    "extra key": (_with(lambda d: d.update(colour="red")), "unknown key 'colour'"),
    "country TW": (_with(lambda d: d.update(country="TW")), "country 'TW': the file is the layer of JP"),
    "country US": (_with(lambda d: d.update(country="US")), "country 'US': the file is the layer of JP"),
    **{f"{part} values removed": (_without(part), "values and readers go together")
       for part in sorted({pid for pid, _key in country_layer.READ}, key=lambda x: int(x[1:]))},
    "bad holiday list": (_with(lambda d: d["parts"]["P9"]["values"].update(holiday_list="holidays_jp.txt")),
                         "holiday_list: 'holidays_jp.txt'"),
}  # fmt: skip


def _everything(country: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every reader of the layer for a site of ``country``, as it answers (or the error it raises)."""
    from criteria_compiler.terminology import resolver
    from datacore import lifecycle

    def ask(f: Callable[[], Any]) -> Any:
        try:
            return f()
        except Exception as exc:
            return f"raised {type(exc).__name__}: {exc}"

    tz = {"JP": "Asia/Tokyo", "TW": "Asia/Taipei", "US": "America/New_York", "": "UTC"}[country]

    class Cfg:
        class env:  # noqa: N801
            pass

        class settings:  # noqa: N801
            class site:  # noqa: N801
                locale = "en"

    Cfg.env.tz = tz  # type: ignore[attr-defined]
    monkeypatch.setattr("tb_common.config.get_config", lambda: Cfg)
    cal = workdays.for_country(country, {})
    term = type("T", (), {"ingredients": None})()
    return {
        "calls": ask(lambda: _calls(country) if country else None),
        "health": workdays.health(cal, __import__("datetime").date(2026, 11, 19)),
        "clock": ask(lambda: lifecycle.clock_rules(tz=tz)),
        "defaults": ask(lambda: site_country.defaults(country.lower())),
        "ssmix2": site_country.reads_ssmix2(country.lower()),
        "stems": ask(lambda: resolver.jp_ingredients(term).ingredients is not None),
        "stamp": country_layer.stamp(country),
        "committees_on": committees.on(country),
        "layer_on": country_layer.layer(country).on,
    }


@pytest.mark.parametrize("case", list(TAMPERED))
def test_a_bad_japan_layer_reaches_japanese_sites_only_and_says_so(case: str, tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """D-1250: Taiwan, the United States and a box with no country answer exactly as with the shipped file. Japan is
    not quietly another country: one red health line names the file and what is wrong, and each value is not
    available in its own safe way."""
    raw, says = TAMPERED[case]
    good = {c: _everything(c, monkeypatch) for c in ("TW", "US", "")}
    with _tampered(tmp_path, raw):
        for c in ("TW", "US", ""):
            assert _everything(c, monkeypatch) == good[c], c
        lay = country_layer.layer("JP")
        assert lay.broken and not lay.on and says in lay.problem, lay.problem
        jp = _everything("JP", monkeypatch)
        # one red line on the box's health, naming the file and the reason; Monday to Friday, said there
        level, line = jp["health"]
        assert level == "red" and "JP country layer japan_profile.json cannot be used" in line and says in line
        # eGFR: none, never CKD-EPI; the drug lists: the compiler does not start; the SAE clock: no regulator, the study
        # names its set; the committees: on, and their record cannot be read (a move into open is refused, lists held)
        with pytest.raises(country_layer.LayerBroken, match="japan_profile.json"):
            derived.egfr_for_site("JP")
        assert jp["stems"].startswith("raised LayerBroken: japan_profile.json")
        assert jp["clock"]["problems"] == ["unconfirmed"] and jp["clock"]["regulator"] == ""
        assert jp["committees_on"]
        with pytest.raises(country_layer.LayerBroken):
            committees.profile()
        # the set-up: no defaults to offer (the wizard says why), no SS-MIX2 offered; the profile's record: no layer
        assert jp["defaults"].startswith("raised LayerBroken: japan_profile.json") and not jp["ssmix2"]
        assert jp["stamp"] is None and jp["layer_on"] is False
    assert not country_layer.layer("JP").broken  # the shipped file again


def test_nothing_reads_a_layer_at_import(tmp_path: Path) -> None:
    """The console, the compiler and the orchestrator import with no Japan layer file at all, and import reads none."""
    import subprocess

    code = (
        "import sys, pathlib\n"
        "from tb_common import country_layer\n"
        f"country_layer.ROOT = pathlib.Path({str(tmp_path)!r})\n"
        "import console.app, criteria_compiler.app, orchestrator.scheduler, tools.settings_wizard\n"
        "from tb_common import site_country\n"
        "assert site_country.TABLE['tw'].locale == 'zh-TW'\n"
        "assert country_layer._shipped.cache_info().currsize == 0, country_layer._shipped.cache_info()\n"
        "print('ok')\n"
    )
    env = {**__import__("os").environ, "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT / 'services'}:{ROOT}"}
    got = subprocess.run([sys.executable, "-c", code], check=False, cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=300)  # fmt: skip
    assert got.returncode == 0 and got.stdout.strip().endswith("ok"), got.stderr[-3000:]


# ---------------------------------------------------------------------------------- versions and audit
def _profile(tmp_path: Path, country: str) -> Any:
    from tb_common import site_profile

    src = ROOT / "services" / "adapter" / "mapping" / "profile" / ("synthetic-jp-ss" if country == "jp" else
                                                                   "synthetic-tw-a")  # fmt: skip
    return site_profile.load(src)


# the load event's detail as master writes it, for every country (the audit's shape is lane C2's; D-1250)
EVENT_DETAIL = {"profile", "site", "old_version", "new_version", "old_digest", "new_digest", "old_profile",
                "direction", "synthetic", "rows_changed", "row_changes", "copy_sha"}  # fmt: skip


def _load_events(audit: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(x for x in audit.rglob("*") if x.is_file()):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("event") == "terminology.site_profile_load":
                out.append(ev)
    return out


def test_the_layers_version_is_in_the_site_profiles_record_and_not_in_the_audit_event(tmp_path: Path) -> None:
    from adapter import site_profile as asp

    p = _profile(tmp_path, "jp")
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    ch = asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit)
    assert ch is not None and set(ch) == EVENT_DETAIL | {"at", "by"}  # what master returned, key for key
    assert asp.read_record(lake)["active"]["layer"] == country_layer.stamp("JP")
    events = _load_events(audit)
    assert len(events) == 1 and set(events[0]["detail"]) == EVENT_DETAIL  # the event exactly as master's shape
    assert asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit) is None  # nothing new
    # the same profile under the release's next layer: nothing is written, as on master (the record keeps the layer
    # read at the load; no event, no write without one)
    before = (lake / asp.RECORD).read_bytes()
    newer = dataclasses.replace(_jp(), version="1.1.0", digest="f" * 64)
    with _layers({"JP": newer}):
        assert asp.activate(p, lake, site_id=p.site_id, by="steward-b", audit_dir=audit) is None
    assert (lake / asp.RECORD).read_bytes() == before and len(_load_events(audit)) == 1


def test_a_country_without_a_layer_records_exactly_what_it_did_before(tmp_path: Path) -> None:
    from adapter import site_profile as asp

    p = _profile(tmp_path, "tw")
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    ch = asp.activate(p, lake, site_id=p.site_id, by="steward-a", audit_dir=audit)
    assert ch is not None and set(ch) == EVENT_DETAIL | {"at", "by"}
    assert set(_load_events(audit)[0]["detail"]) == EVENT_DETAIL
    assert "layer" not in asp.read_record(lake)["active"]


# ------------------------------------------------------------------- no Japan behaviour outside the layer
# A tripwire, not a proof (D-1250 point 7). It scans the code that ships: Python under libs/ and services/, the box's
# set-up (tools/box/, tools/settings_wizard.py), and the templates, YAML and JS under libs/ and services/ (their
# comments left out: a comment is not behaviour). Not the rest of tools/ (dev, bench and synthetic-data tools, which
# do not ship). It looks for the country's words, whole and in any case: "jp", "jpn", "japan", "日本", "asia/tokyo",
# "tokyo", "jst", and any string starting "jp_" (a rule set or file named for Japan). In Python a string counts when it
# is written whole, implicitly concatenated or added from two pieces; a string built otherwise (a join, chr, a slice)
# is not seen. Language words ("ja", "ja-JP", "Japanese") are not country words: the one place a language decides a
# country (derived.country_of and the legacy wizard line) is pinned below. Each word found is pinned by its file and
# the exact text of its line (not its line number, so an edit elsewhere does not move it), with its category. A new
# one, or a pinned line changed, fails with its file and line and what to do.
DATA_LABEL = "a data label or file name: a reference table's, rule set's or code system's own name for Japan"
SOURCE_TYPE = "JP Core and SS-MIX2: switched by the source type a site reads (ssmix2), not by its country"
QUESTION = "the words of the country question and its answers (jp = Japan)"
SHIPPED_DATA = "shipped mapping data and the synthetic Japanese hospital's profile (data, read as data)"
READING = "the one reading of a zone or a language as a country, and the answers file written before 10K-1 (LEGACY)"
LAYER_INDEX = "the layer's own index: which country each shipped layer file is"
NOT_YET = "not yet a layer reader (D-1250, what remains): the follow-up card moves it into the layer"
ALLOWED: dict[tuple[str, str], tuple[int, str]] = {
    **{(f, line): (n, READING) for f, line, n in (
        ('libs/tb_common/derived.py', 'if tz in ("Asia/Tokyo", "Japan"):', 2),
        ('libs/tb_common/derived.py', 'return "JP"', 1),
        ('libs/tb_common/derived.py', 'return "JP" if loc.startswith("ja") else "TW" if loc in ("zh-tw", "zh_tw", "zh-hant") else None', 1),
        ('tools/box/plan.py', 'return "jp" if tz == "Asia/Tokyo" else "tw"', 2),
        ('tools/settings_wizard.py', '"jp" if str(a.get("locale", "zh-TW")).startswith("ja") else "tw"', 1),
    )},
    **{(f, line): (n, LAYER_INDEX) for f, line, n in (
        ('libs/tb_common/country_layer.py', 'FILES = {"JP": "japan_profile.json"}  # the layers shipped: a country and its file (the file must name that country)', 1),
    )},
    **{(f, line): (n, DATA_LABEL) for f, line, n in (
        ('libs/tb_common/refdata_jp.py', '"countries": ["Japan"], "inclusion": _cell(row, idx, "inclusion"),', 1),
        ('libs/tb_common/refdata_jp.py', '"ctcae-v5.0.xlsx", country="JP", decision="D-174", parse=parse_ctcae_v5_en, version_of=ctcae_en_version,', 1),
        ('libs/tb_common/refdata_jp.py', '"ja_clinical_synonyms.csv", country="JP", decision="D-175", parse=parse_ja_synonyms,', 1),
        ('libs/tb_common/refdata_jp.py', '"jp_yj_atc", "YJ code (7-character stem) -> ATC (TrialBox, stems from the MHLW 薬価基準収載品目リスト)",', 1),
        ('libs/tb_common/refdata_jp.py', '"jp_yj_atc.csv", country="JP", decision="D-174", parse=parse_jp_yj_atc, version_of=yj_version,', 2),
        ('libs/tb_common/refdata_jp.py', 'REPO_YJ_ATC = SRC / "jp_yj_atc.csv"', 1),
        ('libs/tb_common/refdata_jp.py', 'country="JP", decision="D-173", derived_from="icd10cm", parse=parse_icd10_who_cm_bridge,', 1),
        ('libs/tb_common/refdata_jp.py', 'country="JP", decision="D-173", fetch=False, parse=parse_medis_byomei,', 1),
        ('libs/tb_common/refdata_jp.py', 'country="JP", decision="D-174", fetch=False, parse=parse_ctcae_v5_ja, version_of=ctcae_ja_version,', 1),
        ('libs/tb_common/refdata_jp.py', 'country="JP", decision="D-174", fetch=False, parse=parse_jlac10_loinc,', 1),
        ('libs/tb_common/refdata_jp.py', 'country="JP", decision="D-317", fetch=False, parse=parse_jrct,', 1),
        ('libs/tb_common/retention.py', '"jp": {**_COMMON, "mail_log_days": 5 * 365},', 1),
        ('services/console/i18n_demoja.py', '"jp_yj_atc": "YJ code (7-character stem) -> ATC (TrialBox, stems from the MHLW 薬価基準収載品目リスト)",', 1),
        ('services/console/i18n_demoja.py', '"jp_yj_atc": "YJ コード（先頭7桁）→ ATC（TrialBox、厚生労働省 薬価基準収載品目リストから作成）",', 1),
        ('services/console/i18n_demoja.py', '"jp_yj_atc": "YJ 代碼（前7碼）→ ATC（TrialBox，取自日本厚生勞動省 薬価基準収載品目リスト）",', 1),
        ('services/datacore/lifecycle.py', '"jp_crb": RuleSet("jp_crb", "JP", "MHLW", {"sponsor": (0, 0), "irb": (7, 15), "regulator": (7, 15)}),', 3),
        ('services/datacore/lifecycle.py', '"jp_gcp": RuleSet("jp_gcp", "JP", "PMDA", {"sponsor": (1, 1), "irb": (1, 1), "regulator": (0, 0)}),', 3),
        ('services/datacore/lifecycle.py', '"jp_gcp_ii", "JP", "PMDA", {"sponsor": (1, 1), "irb": (1, 1), "regulator": (7, 15), EXPECTED_REGULATOR: (15, 0)}', 2),
        ('services/datacore/lifecycle.py', '"jp_gcp_ii": RuleSet(', 1),
        ('services/datacore/lifecycle.py', '"jp_guideline": RuleSet("jp_guideline", "JP", "MHLW", {"sponsor": (0, 0), "irb": (1, 1), "regulator": (0, 0)}),', 3),
        ('services/datacore/lifecycle.py', 'RULE_ALIASES = {"jp": "jp_gcp_ii", "tw": "tw_trial"}  # the box-wide names before D-277 (TB_SAE_RULES)', 2),
        ('services/guard/recognisers.py', 'yield Finding("JP_MY_NUMBER" if ok else "ID_NUMBER", m.start(), m.end(), ok)', 1),
        ('services/orchestrator/scenarios/consent.py', 'code = {"en": "en", "ja": "ja", "jp": "ja", "zh": "zh-TW", "zh-tw": "zh-TW", "tw": "zh-TW"}.get(tok.lower())', 1),
        ('services/sitesetup/ocr.py', 'LANGS = ("jpn", "chi_tra", "eng")', 1),
    )},
    **{(f, line): (n, SOURCE_TYPE) for f, line, n in (
        ('services/adapter/pipeline.py', '"jp_core": {"sampled": psum.sampled, "failed": psum.errors} if psum is not None else None,', 1),
        ('services/adapter/pipeline.py', '(out_dir / "jp_core_validation.json").write_text(', 1),
        ('services/adapter/sources/ssmix2/source.py', 'JP_CORE = Path(__file__).resolve().parents[2] / "mapping" / "jp_core"', 1),
        ('services/adapter/validate/jpcore.py', 'RULES = Path(__file__).resolve().parent / "jp_core_rules.json"', 1),
    )},
    **{(f, line): (n, QUESTION) for f, line, n in (
        ('libs/tb_common/site_country.py', 'COUNTRIES = ("jp", "tw", "us", "other")', 1),
        ('services/console/i18n_firstrun.py', '"firstrun.country.jp": "Japan",', 1),
        ('services/console/i18n_firstrun.py', '"firstrun.country.jp": "日本",', 2),
    )},
    **{(f, line): (n, SHIPPED_DATA) for f, line, n in (
        ('services/adapter/mapping/jp_core/ssmix2_site.yaml', 'tz: Asia/Tokyo', 1),
        ('services/adapter/mapping/profile/synthetic-jp-ss/profile.yaml', 'country: jp', 1),
        ('services/adapter/mapping/profile/synthetic-jp-ss/profile.yaml', 'jp_core: 1.1.0       # the profiles the mapping puts on the resources (mapping/jp_core/ssmix2_site.yaml)', 1),
    )},
    **{(f, line): (n, NOT_YET) for f, line, n in (
        ('services/sitesetup/mapping.py', '("drug", MAPPING_DIR / "jp_core" / "yj_to_atc.csv", "yj_code"),', 1),
        ('services/sitesetup/mapping.py', '("drug", MAPPING_DIR / "jp_core" / "yj_to_atc.csv", "yj_code", "atc", "name"),', 1),
        ('services/sitesetup/mapping.py', '("dx", MAPPING_DIR / "jp_core" / "byomei_to_icd10.csv", "code"),', 1),
        ('services/sitesetup/mapping.py', '("dx", MAPPING_DIR / "jp_core" / "byomei_to_icd10.csv", "code", "icd10", "name"),', 1),
        ('services/sitesetup/mapping.py', '("lab", MAPPING_DIR / "jp_core" / "jlac10_to_loinc.csv", "local_code"),', 1),
        ('services/sitesetup/mapping.py', '("lab", MAPPING_DIR / "jp_core" / "jlac10_to_loinc.csv", "local_code", "code", "display"),', 1),
        ('services/sitesetup/mapping.py', 'path = MAPPING_DIR / "jp_core" / "byomei_to_icd10.csv"', 1),
    )},
}  # fmt: skip
JAPAN = ("jp", "jpn", "japan", "日本", "asia/tokyo", "tokyo", "jst")
_WORD = re.compile(r"(?<![\w/-])(?:jp|jpn|japan|asia/tokyo|tokyo|jst|jp_[a-z0-9_]+)(?![\w/-])|日本", re.I)
_COMMENTS = {
    ".html": re.compile(r"\{#.*?#\}|<!--.*?-->", re.S),
    ".js": re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S),
    ".yaml": re.compile(r"(?:^|(?<=\s))#[^\n]*", re.M),
}
_COMMENTS[".yml"] = _COMMENTS[".yaml"]
HOW = (
    "A Japan behaviour belongs in the country layer: put its value in libs/tb_common/japan_profile.json under its "
    "part (P1 to P16, 'values'), name the function that reads it in that part's 'readers' ('module:function'), and "
    "read it there with tb_common.country_layer.value(country, part, key, default). If the line is not a behaviour "
    "(a data label, a language word), pin it in ALLOWED in tests/unit/test_japan_profile_layer.py with the reason."
)


def _shipped_files() -> list[Path]:
    py = [*sorted((ROOT / "libs").rglob("*.py")), *sorted((ROOT / "services").rglob("*.py")),
          *sorted((ROOT / "tools" / "box").rglob("*.py")), ROOT / "tools" / "settings_wizard.py"]  # fmt: skip
    text = [f for base in ("libs", "services") for f in sorted((ROOT / base).rglob("*")) if f.suffix in _COMMENTS]
    return [f for f in (*py, *text) if f.is_file() and "generated" not in f.parts and "tests" not in f.parts]


def _text(node: ast.AST) -> str | None:
    """A string the node always is: a constant (implicit concatenation included) or two such added."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _text(node.left), _text(node.right)
        return a + b if a is not None and b is not None else None
    return None


def _japan_lines() -> list[tuple[str, int, str]]:
    """Every (file, line number, whole line) where shipped code writes a word naming Japan (one entry per word)."""
    out: list[tuple[str, int, str]] = []
    for f in _shipped_files():
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        rel = f.relative_to(ROOT).as_posix()
        if f.suffix == ".py":
            for node in ast.walk(ast.parse(src)):
                v = _text(node)
                if v is not None and isinstance(node, ast.expr):
                    t = v.strip().lower()
                    if t in JAPAN or t.startswith("jp_"):
                        out.append((rel, node.lineno, lines[node.lineno - 1].strip()))
            continue
        # comments blanked to spaces (newlines kept), so a word's line number is its line in the file
        bare = _COMMENTS[f.suffix].sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
        for n, line in enumerate(bare.splitlines(), 1):
            out += [(rel, n, lines[n - 1].strip())] * len(_WORD.findall(line))
    return out


def _unpinned() -> list[str]:
    found = Counter((f, line) for f, _n, line in _japan_lines())
    where = {(f, line): n for f, n, line in _japan_lines()}
    return [f"{f}:{where[(f, line)]}: {line}" for (f, line), k in sorted(found.items())
            if k > ALLOWED.get((f, line), (0, ""))[0]]  # fmt: skip


def test_no_japan_behaviour_is_added_outside_the_layer() -> None:
    new = _unpinned()
    assert not new, "a string naming Japan outside the layer:\n  " + "\n  ".join(new) + "\n" + HOW
    found = Counter((f, line) for f, _n, line in _japan_lines())
    gone = sorted(f"{f}: {line}" for (f, line), (n, _why) in ALLOWED.items() if found.get((f, line), 0) < n)
    assert not gone, "ALLOWED pins a line the code no longer holds (take it out):\n  " + "\n  ".join(gone)


@pytest.mark.parametrize(
    "code",
    [
        'def f(country):\n    return country == "JP"\n',
        "def f(country):\n    return country.upper() == 'jp'\n",
        'def f(country):\n    return country == "J" "P"\n',
        'def f(country):\n    return country == "J" + "P"\n',
        'JAPAN = {"Asia/Tokyo": 1}\n',
        'def f(country):\n    return country == "日本"\n',
        'def f(tz):\n    return tz == "JST"\n',
        'def f(rules):\n    return rules == "jp_new_rules"\n',
    ],
)
def test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line(code: str, tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    src = tmp_path / "libs" / "tb_common"
    src.mkdir(parents=True)
    (src / "new_switch.py").write_text("# a new behaviour\n" + code, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    got = _unpinned()
    assert len(got) == 1 and got[0].startswith("libs/tb_common/new_switch.py:") and got[0].split(":")[1] in "23"


@pytest.mark.parametrize(
    ("name", "text", "found"),
    [
        ("services/console/templates/new.html", "{# the Japan profile #}\n{% if country == 'JP' %}x{% endif %}\n", 2),
        ("services/console/templates/new.html", "<!-- for Japan -->\n{# JP only #}\n<p>x</p>\n", 0),
        ("services/adapter/mapping/new/site.yaml", "# Japan's mapping\nsource: x\ntz: Asia/Tokyo\n", 3),
        ("services/adapter/mapping/new/site.yaml", "# tz: Asia/Tokyo\nsource: x   # jp\n", 0),
        ("services/console/static/new.js", "// JP\nif (c === 'jp') { go(); }\n", 2),
        ("services/console/static/new.js", "/* jp */\nlet lang = 'ja';\n", 0),
    ],
)  # fmt: skip
def test_the_guard_reads_templates_yaml_and_js_but_not_their_comments(name: str, text: str, found: int,
                                                                       tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """A country word in a template, a YAML file or a script is seen with its file and line; a comment, and a language
    word ("ja"), are not."""
    f = tmp_path / name
    f.parent.mkdir(parents=True)
    f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    got = _unpinned()
    assert len(got) == min(found, 1) and all(g.startswith(f"{name}:{found}:") for g in got)


def test_the_rest_of_tools_and_language_words_are_not_scanned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev, bench and synthetic-data tools do not ship; "ja" is a language, not a country."""
    for name, code in (("tools/synth/new_gen.py", 'STYLE = "JP"\n'), ("libs/tb_common/new_lang.py", 'LANG = "ja"\n')):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(code, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _unpinned() == []


def test_renaming_a_pinned_literal_in_place_is_not_enough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pinned line's slot cannot be reused: the same file with one rule-set label turned into a country test, the
    count of "JP" unchanged, still fails."""
    real = (ROOT / "services" / "datacore" / "lifecycle.py").read_text(encoding="utf-8")
    label = '"jp_crb": RuleSet("jp_crb", "JP", "MHLW",'
    assert label in real
    swapped = real.replace(label, '"jp_crb": RuleSet("jp_crb", "XX", "MHLW",') + (
        '\n\ndef switch(country: str) -> bool:\n    return country == "JP"\n'
    )
    dst = tmp_path / "services" / "datacore"
    dst.mkdir(parents=True)
    (dst / "lifecycle.py").write_text(swapped, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    got = _unpinned()
    at = swapped.splitlines().index('    return country == "JP"') + 1
    assert f'services/datacore/lifecycle.py:{at}: return country == "JP"' in got  # the new switch is seen
    assert len(got) == 2  # and the label's changed line too (its rule-set names still name Japan)
