"""The site set-up's code tables come from the country layer (card 10C-25b, D-1255; D-1250).

* The tables :mod:`sitesetup.mapping` maps a site's own codes against (病名 -> ICD-10, JLAC10 / hospital lab code ->
  LOINC, YJ -> ATC) are the value ``code_tables`` of the country layer's part P7 (Masters). The module asks
  ``country_layer.value`` by one call, the same call for every country; a country without a layer gets the tables
  every site mapped against before.
* No behaviour changes: for a site of Japan, Taiwan, the United States and one with no country, and for every source
  type the set-up offers, what the module resolves is what master resolved. Master's answers were captured from
  master's tree by :func:`answers` (``python tests/unit/test_sitesetup_code_tables_layer.py --capture``, run in a
  worktree of master) into ``tests/fixtures/sitesetup_code_tables/master.json``; the test compares, it does not
  restate.
* A Japanese layer whose ``code_tables`` is missing, of another type or shape, or whose file names another country is
  refused whole: a Japanese site's set-up then gets no table (``LayerBroken``), never another country's; Taiwan, the
  United States and a box with no country answer exactly as before.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "sitesetup_code_tables" / "master.json"
LAYER = ROOT / "libs" / "tb_common" / "japan_profile.json"
# the source types the set-up offers (tools/settings_wizard.py DATA_SOURCES; schemas/settings.schema.json)
SOURCES = ("csv", "cgrd_sql", "fhir_bulk", "ssmix2")
# a site of each country as its settings say it (tb_common.derived.country_of: the zone, else the page's language)
SITES = {
    "JP": ("Asia/Tokyo", "ja"),
    "TW": ("Asia/Taipei", "zh-TW"),
    "US": ("America/New_York", "en"),
    "unset": ("", ""),
}


def _config(tz: str, locale: str, source: str) -> Any:
    class Cfg:
        class env:  # noqa: N801
            pass

        class settings:  # noqa: N801
            class site:  # noqa: N801
                pass

            class data_source:  # noqa: N801
                pass

    Cfg.env.tz = tz  # type: ignore[attr-defined]
    Cfg.settings.site.locale = locale  # type: ignore[attr-defined]
    Cfg.settings.site.tz = tz  # type: ignore[attr-defined]
    Cfg.settings.data_source.type = source  # type: ignore[attr-defined]
    return Cfg


def _clear(mapping: Any) -> None:
    for obj in vars(mapping).values():
        if callable(getattr(obj, "cache_clear", None)):
            obj.cache_clear()


def answers(site: str, source: str) -> dict[str, Any]:
    """What :mod:`sitesetup.mapping` resolves for a site of ``site`` reading ``source``: the rows of every table it
    maps against, the rows it marks not verified, the diagnosis names it takes from them, and its suggestion for
    every code of those tables. Run with the configuration replaced (no database, no licensed release)."""
    from sitesetup import mapping
    from tb_common import config

    tz, locale = SITES[site]
    saved = config.get_config
    config.get_config = lambda: _config(tz, locale, source)  # type: ignore[assignment]
    _clear(mapping)
    try:
        lk = mapping._lookups()
        terms = sorted(
            [name, conf, code, display]
            for name, hits in mapping._dx_index().items()
            for conf, code, display, method in hits
            if method == "term" and conf == 0.95
        )
        system = {"dx": "dx-code", "lab": "lab-code", "drug": "drug-code"}
        domain = {"dx": "condition", "lab": "observation", "drug": "medication"}
        suggested = {
            f"{kind}:{code}": mapping.suggest(domain[kind], mapping.local_system(system[kind]), code)
            for kind in ("dx", "lab", "drug")
            for code in sorted(lk[kind])
        }
        return {
            "country": mapping.site_country(),
            "lookups": {k: sorted([c, *v] for c, v in rows.items()) for k, rows in sorted(lk.items())},
            "unverified": sorted(list(x) for x in mapping._unverified()),
            "dx_terms": terms,
            "jlac10_known": sorted([c, *v] for c, v in mapping._jlac10_known().items()),
            "suggested": suggested,
        }
    finally:
        config.get_config = saved
        _clear(mapping)


def capture() -> dict[str, Any]:
    return {f"{site}/{source}": answers(site, source) for site in SITES for source in SOURCES}


# ------------------------------------------------------------------------------------------ no behaviour change
@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)


MASTER: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))["answers"] if FIXTURE.exists() else {}


def test_masters_answers_were_captured_for_every_country_and_source_type() -> None:
    assert sorted(MASTER) == sorted(f"{s}/{t}" for s in SITES for t in SOURCES)
    assert all(MASTER[k]["lookups"]["dx"] and MASTER[k]["lookups"]["lab"] and MASTER[k]["lookups"]["drug"]
               for k in MASTER)  # fmt: skip


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("site", list(SITES))
def test_the_tables_resolved_are_masters(site: str, source: str) -> None:
    assert answers(site, source) == MASTER[f"{site}/{source}"]


# ----------------------------------------------------------------------------------------------- one path
def test_the_tables_are_the_layers_value_asked_by_one_call() -> None:
    from sitesetup import mapping
    from tb_common import country_layer

    names = country_layer.value("JP", "P7", "code_tables")
    assert list(names) == [p.relative_to(mapping.MAPPING_DIR).as_posix() for _k, p, *_c in mapping.code_tables("JP")]
    for country in ("TW", "US", "", None):
        assert country_layer.value(country, "P7", "code_tables") is None
        assert [p.relative_to(mapping.MAPPING_DIR).as_posix() for _k, p, *_c in mapping.code_tables(country)] == list(
            mapping.OTHER_COUNTRY_TABLES
        )
    assert "sitesetup.mapping:code_tables" in country_layer.layer("JP").parts["P7"].readers


def test_the_same_layer_under_another_country_code_gives_the_same_tables() -> None:
    from sitesetup import mapping
    from tb_common import country_layer

    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    doc["country"] = "XQ"
    doc["parts"]["P7"]["values"]["code_tables"] = doc["parts"]["P7"]["values"]["code_tables"][:2]
    xq = country_layer.parse(json.dumps(doc, ensure_ascii=False).encode(), "xq_profile.json")
    with _layers({"XQ": xq}):
        got = [p.relative_to(mapping.MAPPING_DIR).as_posix() for _k, p, *_c in mapping.code_tables("XQ")]
        assert got == doc["parts"]["P7"]["values"]["code_tables"]  # the layer's data, whatever its country code
        assert [p.relative_to(mapping.MAPPING_DIR).as_posix() for _k, p, *_c in mapping.code_tables("JP")] == list(
            mapping.OTHER_COUNTRY_TABLES
        )  # and Japan, without its layer, is a country without one


@contextmanager
def _layers(found: dict[str, Any]) -> Iterator[None]:
    from tb_common import country_layer

    saved = country_layer._shipped, country_layer.FILES
    country_layer._shipped = lambda code: found.get(code, country_layer.NONE)  # type: ignore[assignment]
    country_layer.FILES = {code: lay.file for code, lay in found.items()}
    try:
        yield
    finally:
        country_layer._shipped, country_layer.FILES = saved


# ------------------------------------------------------------------------------------- a layer that cannot be used
def _with(edit: Callable[[dict[str, Any]], Any]) -> bytes:
    doc = json.loads(LAYER.read_text(encoding="utf-8"))
    edit(doc)
    return json.dumps(doc, ensure_ascii=False).encode()


def _p7(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["parts"]["P7"]["values"]  # type: ignore[no-any-return]


TAMPERED: dict[str, tuple[bytes, str]] = {
    "missing": (_with(lambda d: _p7(d).pop("code_tables", None)), "'code_tables' is missing"),
    "wrong type": (_with(lambda d: _p7(d).update(code_tables="tw_core/lab_local_to_loinc.csv")),
                   "code_tables: 'tw_core/lab_local_to_loinc.csv' is not a list"),
    "empty": (_with(lambda d: _p7(d).update(code_tables=[])), "code_tables: [] is not a list"),
    "an item not a text": (_with(lambda d: _p7(d).update(code_tables=["tw_core/lab_local_to_loinc.csv", 3])),
                           "code_tables: 3 is not a str"),
    "wrong shape: outside the folder": (_with(lambda d: _p7(d).update(code_tables=["../lab_local_to_loinc.csv"])),
                                        "code_tables: '../lab_local_to_loinc.csv' is not"),
    "wrong shape: a table of no known format": (
        _with(lambda d: _p7(d).update(code_tables=["tw_core/demo_his.yaml"])), "code_tables: 'tw_core/demo_his.yaml'"),
    "wrong shape: twice": (
        _with(lambda d: _p7(d).update(code_tables=["tw_core/lab_local_to_loinc.csv"] * 2)), "is listed twice"),
    "country TW": (_with(lambda d: d.update(country="TW")), "country 'TW': the file is the layer of JP"),
    "country US": (_with(lambda d: d.update(country="US")), "country 'US': the file is the layer of JP"),
}  # fmt: skip


@contextmanager
def _tampered(tmp_path: Path, raw: bytes) -> Iterator[None]:
    from tb_common import country_layer

    folder = tmp_path / "layer"
    folder.mkdir(exist_ok=True)
    (folder / "japan_profile.json").write_bytes(raw)
    saved = country_layer.ROOT
    country_layer.ROOT = folder
    country_layer._shipped.cache_clear()
    try:
        yield
    finally:
        country_layer.ROOT = saved
        country_layer._shipped.cache_clear()


def _ask(f: Callable[[], Any]) -> Any:
    try:
        return f()
    except Exception as exc:
        return f"raised {type(exc).__name__}: {exc}"


@pytest.mark.parametrize("case", list(TAMPERED))
def test_a_layer_whose_code_tables_cannot_be_used_is_refused_whole(case: str) -> None:
    from tb_common import country_layer

    raw, says = TAMPERED[case]
    if case.startswith("country"):
        assert country_layer.parse(raw, "japan_profile.json").country == case[-2:]  # refused by FILES, below
        return
    with pytest.raises(country_layer.LayerError, match=says.replace("[", r"\[").replace("(", r"\(")):
        country_layer.parse(raw, "japan_profile.json")


@pytest.mark.parametrize("case", list(TAMPERED))
@pytest.mark.parametrize("site", list(SITES))
def test_a_bad_layer_reaches_japanese_sites_only_and_never_gives_another_countrys_tables(
    site: str, case: str, tmp_path: Path
) -> None:
    from sitesetup import mapping
    from tb_common import country_layer

    raw, says = TAMPERED[case]
    with _tampered(tmp_path, raw):
        assert country_layer.layer("JP").broken and says in country_layer.layer("JP").problem
        if site != "JP":
            for source in SOURCES:
                assert answers(site, source) == MASTER[f"{site}/{source}"], (site, source)
            return
        code = "JP"
        with pytest.raises(country_layer.LayerBroken, match="japan_profile.json"):
            mapping.code_tables(code)
        for source in SOURCES:
            got = _ask(lambda s=source: answers(site, s))  # type: ignore[misc]
            assert isinstance(got, str) and got.startswith("raised LayerBroken: japan_profile.json"), got
    assert not country_layer.layer("JP").broken  # the shipped file again


if __name__ == "__main__":  # run in a worktree of master: writes master's answers
    sys.path[:0] = [str(ROOT), str(ROOT / "libs"), str(ROOT / "services")]
    import os
    import subprocess

    os.environ.pop("TB_DB_URL", None)
    if sys.argv[1:] != ["--capture"]:
        raise SystemExit("usage: python tests/unit/test_sitesetup_code_tables_layer.py --capture")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = {"captured_from": head.stdout.strip(), "answers": capture()}
    FIXTURE.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
