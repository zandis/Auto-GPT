"""TERM-2 follow-up (lane H's #936, through the integrator): a ruleset's terminology stamp names each table loaded
at install that its compile read, so two boxes whose loaded tables differ never compile one protocol under one stamp.

* the terminology records each loaded table it read: its name, the code system it serves (a site list: the systems
  of its rows), its version and the sha256 of its manifest line; a box that loads none reads none;
* a compile writes them to the manifest (``terminology_tables``, beside ``terminology_release``) and to the
  equivalence report it stores; a compile that read none writes neither (every committed ruleset stays as it is);
* approval is blocked, with the tables named, while the box's loaded tables (or its release) differ from the
  draft's: a draft compiled on another box, or before the site's IT loaded or replaced a table, is compiled again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
import yaml
from criteria_compiler.service import stamp_differs
from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import LOADED_SYSTEMS, Terminology

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 (the fixture)

ROOT = Path(__file__).resolve().parents[2]
SITE_CSV = """local_code,local_name,system,code,display
ZZ-DX-0001,hypertension,icd10cm,I10,SYNTHETIC site row: essential hypertension only
ZZ-LAB-0001,SYNTHETIC glucose fasting,loinc,99990-1,
"""


def _loaded(tmp: Path, site_csv: str = SITE_CSV) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    where = tmp / "terminology"
    src = tmp / "dx.csv"
    src.write_text(site_csv, encoding="utf-8")
    installed.install_site_list(src, where, "dx", version="2099-01")
    installed.install_nhi_drugs(ROOT / "tests/fixtures/refdata/nhi_drugs_sample.csv", where, version="2099-02")
    return where


def _manifest(stamp: list[dict[str, str]] | None, release: str | None = None) -> c.RulesetManifest:
    base = c.RulesetManifest.model_validate(yaml.safe_load((ROOT / "rulesets/GZQO/manifest.yaml").read_text("utf-8")))
    return base.model_copy(update={"terminology_tables": [c.TerminologyTable(**t) for t in stamp or []] or None,
                                   "terminology_release": release})  # fmt: skip


def test_the_terminology_names_each_loaded_table_it_read(tmp_path: Path) -> None:
    where = _loaded(tmp_path)
    lines = installed.manifest(where)["tables"]
    stamp = Terminology(installed=where).installed_stamp()
    assert stamp == [
        {"table": "nhi_drug_list", "system": LOADED_SYSTEMS["nhi_drug"], "version": "2099-02", "sha256": lines["nhi_drug_list"]["sha256"]},
        {"table": "site_dx", "system": "site", "version": "2099-01", "sha256": lines["site_dx"]["sha256"]},
    ]  # fmt: skip
    assert Terminology(installed=tmp_path / "nothing").installed_stamp() == []


def test_a_table_added_gone_or_changed_is_named_and_no_change_is_silent(tmp_path: Path) -> None:
    then = Terminology(installed=_loaded(tmp_path / "a")).installed_stamp()
    m = _manifest(then)
    assert stamp_differs(m, Terminology(installed=_loaded(tmp_path / "b"))) == ""  # same bytes on another box
    changed = Terminology(installed=_loaded(tmp_path / "c", SITE_CSV + "ZZ-DX-0002,gout,icd10cm,M10,\n"))
    why = stamp_differs(m, changed)
    assert why.startswith("terminology differs from the compile (site_dx 2099-01 (") and "compile again" in why
    assert "nhi_drug_list" not in why
    assert "site_dx gone" in stamp_differs(m, Terminology(installed=tmp_path / "nothing"))
    assert "site_dx added" in stamp_differs(_manifest(None), Terminology(installed=_loaded(tmp_path / "d")))


def test_a_release_other_than_the_drafts_is_named() -> None:
    term = Terminology(installed=Path("/nonexistent-terminology"))
    assert stamp_differs(_manifest(None, term.release), term) == ""
    assert stamp_differs(_manifest(None, "TR-000000000000"), term).startswith(
        f"terminology differs from the compile (release TR-000000000000 -> {term.release})"
    )


def test_the_compile_stamps_the_manifest_and_the_report_and_approval_waits_for_the_same_tables(
    env: dict[str, Any],  # noqa: F811 (the fixture)
    tmp_path: Path,
) -> None:
    where = _loaded(tmp_path / "box")
    comp = env["comp"]
    comp.d.term = Terminology(installed=where)
    res = _compile(env)
    stamp = [t.table for t in res.manifest.terminology_tables or []]
    assert stamp == ["nhi_drug_list", "site_dx"]
    report = json.loads(comp.d.repo.read(res.branch, "GZQO/tests/equivalence.json"))
    assert [t["table"] for t in report["terminology_tables"]] == stamp
    decisions = _decisions(env["store"], res.review_xlsx_key)
    comp.d.term = Terminology(installed=tmp_path / "nothing")  # the box's IT removed its loaded tables
    out = _approve(env, decisions)
    assert out.status != "approved" and any("nhi_drug_list gone" in b for b in out.blocking or [])
    comp.d.term = Terminology(installed=where)  # the tables the draft was compiled against
    assert _approve(env, decisions).status == "approved"


def test_a_compile_that_read_no_loaded_table_writes_no_stamp(env: dict[str, Any]) -> None:  # noqa: F811
    env["comp"].d.term = Terminology(installed=Path("/nonexistent-terminology"))
    res = _compile(env)
    assert res.manifest.terminology_tables is None
    assert "terminology_tables" not in json.loads(env["comp"].d.repo.read(res.branch, "GZQO/tests/equivalence.json"))


@pytest.mark.parametrize("table", ["icd10cm_blocks", "loinc_table"])
def test_every_table_the_mapper_can_read_names_its_system(table: str) -> None:
    from criteria_compiler.terminology.mapper import TABLE_SYSTEMS

    assert LOADED_SYSTEMS[TABLE_SYSTEMS[table]].startswith("http")
