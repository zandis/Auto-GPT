"""E-TERM-3 (D-1048): a site list that stops being read is never silent, and it blocks approval.

D-1028 makes the site's own code lists the primary source (D-1113). Before this card a site list refused at read time
(its bytes no longer match its manifest line, its file gone, a damaged manifest) went into the mapper's
``installed_problems``, which only ``trialbox doctor`` and ``tools.terminology_coverage`` read; the compile answered
from the shipped tables and nobody in the console learned it. The integrator's ruling (#639): fail closed. The
compile records each refused table; while a site list is refused, approval is refused and says which list and why; it
opens again when the box's IT loads the list again or removes it on purpose (an audited removal is no refusal). A
refused shipped or licensed table (not a site list) is recorded and stays a warning.

The site list is SYNTHETIC (local codes ``ZZ...``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import Terminology
from tb_common.audit import verify

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 - env is a fixture
from tools import terminology_install

SITE_CSV = """local_code,local_name,system,code,display
ZZ-DX-0001,hypertension,icd10cm,I10,SYNTHETIC site row: essential hypertension only
"""


def _load(where: Path, tmp: Path) -> None:
    src = tmp / "dx.csv"
    src.write_text(SITE_CSV, encoding="utf-8")
    assert installed.install_site_list(src, where, "dx") == {"site_dx": 1}


def _tamper(where: Path) -> None:
    p = where / "site_dx.parquet"
    p.write_bytes(p.read_bytes() + b"\0")  # other bytes than its manifest line vouches for


def test_a_changed_site_list_is_refused_by_name_and_every_mapping_says_so(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    _tamper(where)
    term = Terminology(installed=where)
    assert [(r["table"], r["system"]) for r in term.terminology_refused] == [("site_dx", "site")]
    assert "sha256 differs" in term.terminology_refused[0]["reason"]
    assert term.refused_site_lists() == term.terminology_refused
    res = term.map("condition", "hypertension")
    assert res.method != "site"  # the list is not read
    assert any("site list site_dx was not read" in n for n in res.notes), res.notes


def test_a_site_list_whose_file_is_gone_is_refused_not_skipped(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    (where / "site_dx.parquet").unlink()  # its manifest line stays: nobody removed it on purpose
    term = Terminology(installed=where)
    assert [r["table"] for r in term.refused_site_lists()] == ["site_dx"]
    assert "file is missing" in term.refused_site_lists()[0]["reason"]


def test_a_refused_table_that_is_not_a_site_list_is_recorded_but_is_no_site_refusal(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    (where / f"{installed.ICD_BLOCKS}.parquet").write_bytes(b"not a table")  # no manifest line
    term = Terminology(installed=where)
    assert [r["table"] for r in term.terminology_refused] == [installed.ICD_BLOCKS]
    assert term.terminology_refused[0]["system"] == "http://hl7.org/fhir/sid/icd-10-cm"  # the stamp's URI
    assert term.refused_site_lists() == []


def test_a_list_loaded_again_is_read_without_a_restart(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    _tamper(where)
    term = Terminology(installed=where)
    assert term.refused_site_lists()
    _load(where, tmp_path)  # the box's IT loads it again
    term.refresh_installed()
    assert term.refused_site_lists() == [] and term.map("condition", "hypertension").method == "site"


def test_removal_is_audited_and_is_no_refusal(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    _tamper(where)
    audit = tmp_path / "audit"
    args = ["remove-site-list", "--name", "dx", "--by", "it-admin", "--dir", str(where)]
    assert terminology_install.main(args) == 2  # no audit folder: a removal that leaves no trace is refused
    assert (where / "site_dx.parquet").exists()
    assert terminology_install.main([*args, "--audit-dir", str(audit)]) == 0
    assert not (where / "site_dx.parquet").exists() and "site_dx" not in installed.manifest(where)["tables"]
    lines = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x.strip()]
    events = [e for e in lines if e.get("event") == "terminology.remove"]
    assert verify(audit).ok
    assert len(events) == 1 and events[0]["actor"] == "it-admin" and events[0]["detail"]["table"] == "site_dx"
    assert Terminology(installed=where).terminology_refused == []
    assert terminology_install.main([*args, "--audit-dir", str(audit)]) == 2  # nothing left to remove


def test_only_a_site_list_can_be_removed_this_way(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _load(where, tmp_path)
    (tmp_path / "x.parquet").write_bytes(b"outside")
    for name in ("../x", "dx/../../x", "DX"):
        args = [
            "remove-site-list",
            "--name",
            name,
            "--by",
            "it",
            "--dir",
            str(where),
            "--audit-dir",
            str(tmp_path / "a"),
        ]
        assert terminology_install.main(args) == 2, name
    assert (tmp_path / "x.parquet").exists() and (where / "site_dx.parquet").exists()


# ------------------------------------------------------------------------------------- the compile and the approval
def _with_site_list(env: dict[str, Any]) -> Path:  # noqa: F811
    where = env["tmp"] / "terminology"
    _load(where, env["tmp"])
    env["deps"].term = Terminology(installed=where)
    return Path(where)


def test_the_compile_records_the_refusal_and_approval_is_refused(env: dict[str, Any]) -> None:  # noqa: F811
    where = _with_site_list(env)
    _tamper(where)
    env["deps"].term.refresh_installed()
    res = _compile(env)
    assert [(r.table, r.system) for r in res.manifest.terminology_refused or []] == [("site_dx", "site")]
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "needs_review"
    assert any("site list site_dx was not read at the compile" in b for b in out.blocking or []), out.blocking
    _load(where, env["tmp"])  # loaded again: the next compile reads it, and approval opens
    res = _compile(env)
    assert not res.manifest.terminology_refused
    assert _approve(env, _decisions(env["store"], res.review_xlsx_key)).status == "approved"


def test_a_list_refused_after_the_compile_still_blocks_approval(env: dict[str, Any]) -> None:  # noqa: F811
    where = _with_site_list(env)
    res = _compile(env)
    assert not res.manifest.terminology_refused
    _tamper(where)
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "needs_review" and any("site_dx" in b for b in out.blocking or [])


def test_a_refused_shipped_table_is_recorded_and_approval_goes_on(env: dict[str, Any]) -> None:  # noqa: F811
    where = env["tmp"] / "terminology"
    where.mkdir()
    (where / f"{installed.ICD_INDEX}.parquet").write_bytes(b"not a table")
    env["deps"].term = Terminology(installed=where)
    res = _compile(env)
    assert [r.table for r in res.manifest.terminology_refused or []] == [installed.ICD_INDEX]
    assert _approve(env, _decisions(env["store"], res.review_xlsx_key)).status == "approved"


def test_the_review_workbook_lists_the_refused_tables(env: dict[str, Any]) -> None:  # noqa: F811
    import io

    from openpyxl import load_workbook

    where = _with_site_list(env)
    _tamper(where)
    env["deps"].term.refresh_installed()
    res = _compile(env)
    wb = load_workbook(io.BytesIO(env["store"].get(res.review_xlsx_key)), read_only=True)
    rows = list(wb["terminology"].iter_rows(values_only=True))
    assert rows[0][:2] == ("table", "reason") and rows[1][0] == "site_dx"
    assert json.dumps(rows).count("ZZ-DX") == 0  # the reason names the table, never a row of it
