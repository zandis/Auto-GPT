"""10D-2 (D-1366; review 14 M14-1): the study manifest in a protocol part and a site part.

Proved by: one package (protocol part) on two sites (two site parts) gives the same criteria hash; a site edit of a
threshold is refused with a sentence; every shipped manifest loads unchanged through the split.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import study_manifest as sm
from tb_common.ruleset import SEED_RULESETS, Ruleset
from tb_contracts import RulesetManifest, StudyProtocol, StudySite

SHIPPED = sorted(p.parent.name for p in SEED_RULESETS.glob("*/manifest.yaml"))
SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _files(ruleset: str) -> dict[str, bytes]:
    d = SEED_RULESETS / ruleset
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def _second_site(files: dict[str, bytes]) -> dict[str, bytes]:
    """The same package at another hospital: its own people, routing, models, approval, IRB record, equivalence run
    and criterion review records; nothing of the protocol touched."""
    out = dict(files)
    m = yaml.safe_load(files["manifest.yaml"])
    m["status"] = "draft"
    m["scopes"] = {"screen": {"practitioners": ["D0001"], "departments": ["RHEUM-B"], "appointment_window_days": 90}}
    m["routing"] = {"list_to": ["pi@siteb.test"], "aggregate_to": ["crc@siteb.test"]}
    m["models"] = {"judge": "another-local-model", "judge_prompt": "judge_v4"}
    m["review"] = {"approved_by": "pi@siteb.test", "approved_via": "web console", "rounds": 2}
    m["equivalence"] = {"overall_pct": 99.0, "sample_size": 12}
    m["irb_reference"] = "B-2026-17"
    m["effective_from"] = "2026-12-01"
    m.pop("terminology_tables", None)
    out["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode("utf-8")
    for path in [p for p in files if p.startswith("ir/")]:
        ir = json.loads(files[path])
        if (ir.get("review") or {}).get("status") != "rejected":
            ir["review"] = {"status": "draft", "by": "pi@siteb.test", "at": "2026-11-30T09:00:00+09:00"}
        out[path] = json.dumps(ir, ensure_ascii=False, indent=2).encode("utf-8")
    out["tests/equivalence.json"] = b'{"overall_pct": 99.0, "per_criterion": {}, "failing": []}'
    return out


def _with_manifest(files: dict[str, bytes], **changes: Any) -> dict[str, bytes]:
    m = yaml.safe_load(files["manifest.yaml"])
    m.update(changes)
    return {**files, "manifest.yaml": yaml.safe_dump(m, allow_unicode=True).encode("utf-8")}


# ---------------------------------------------------------------------------------------------- the line
def test_every_manifest_field_is_in_exactly_one_part() -> None:
    protocol, site = set(sm.PROTOCOL_FIELDS), set(sm.SITE_FIELDS)
    assert not protocol & site
    assert protocol | site == set(RulesetManifest.model_fields)


def test_the_schemas_list_the_same_fields() -> None:
    for name, fields in (("study_protocol", sm.PROTOCOL_FIELDS), ("study_site", sm.SITE_FIELDS)):
        doc = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert doc["properties"]["manifest"]["propertyNames"]["enum"] == list(fields)


def test_thresholds_pins_and_criteria_are_the_protocols_people_and_routing_the_sites() -> None:
    for f in ("thresholds", "criteria", "version", "prompt_pins", "derived_pins", "terminology_release"):
        assert f in sm.PROTOCOL_FIELDS
    for f in ("scopes", "routing", "models", "review", "status"):
        assert f in sm.SITE_FIELDS


# ---------------------------------------------------------------------------------------------- existing studies
@pytest.mark.parametrize("ruleset", SHIPPED)
def test_a_shipped_manifest_loads_unchanged_through_the_split(ruleset: str) -> None:
    parts = sm.split(_files(ruleset))
    StudyProtocol.model_validate(parts.protocol)
    StudySite.model_validate(parts.site)
    assert sm.protocol_refusal(parts.protocol) is None
    merged = RulesetManifest.model_validate(sm.merge(parts.protocol, parts.site))
    loaded = Ruleset.load(SEED_RULESETS / ruleset).manifest
    assert merged == loaded
    assert merged.model_dump() == loaded.model_dump()


@pytest.mark.parametrize("ruleset", SHIPPED)
def test_the_split_of_a_folder_on_disk_is_the_split_of_its_files(ruleset: str) -> None:
    assert sm.split_dir(SEED_RULESETS / ruleset) == sm.split(_files(ruleset))


def test_the_criteria_hash_is_stable_and_differs_between_studies() -> None:
    hashes = {r: sm.split(_files(r)).criteria_sha256 for r in SHIPPED}
    assert len(set(hashes.values())) == len(SHIPPED)
    assert sm.split(_files("RA-JAK")).criteria_sha256 == hashes["RA-JAK"]


# ---------------------------------------------------------------------------------------------- two sites
def test_one_package_on_two_sites_gives_the_same_criteria_hash() -> None:
    site_a = sm.split(_files("RA-JAK"))
    site_b = sm.split(_second_site(_files("RA-JAK")))
    assert site_a.criteria_sha256 == site_b.criteria_sha256
    assert site_a.protocol == site_b.protocol
    assert site_a.site != site_b.site
    assert site_b.site["criteria_sha256"] == site_a.criteria_sha256
    assert site_b.site["criterion_reviews"]["RA-JAK-INC-01"]["by"] == "pi@siteb.test"
    # the package's protocol part with site B's own part is a valid manifest for site B
    b = RulesetManifest.model_validate(sm.merge(site_a.protocol, site_b.site))
    assert b.routing is not None and b.routing.list_to == ["pi@siteb.test"]
    assert b.thresholds is not None and b.thresholds.small_cell == 5


def test_dropping_a_criterion_at_a_site_is_a_protocol_change() -> None:
    files = _files("RA-JAK")
    ir = json.loads(files["ir/RA-JAK-EXC-03.json"])
    ir["review"] = {"status": "rejected", "by": "pi@siteb.test"}
    dropped = {**files, "ir/RA-JAK-EXC-03.json": json.dumps(ir).encode("utf-8")}
    adopted = sm.split(files).protocol
    assert sm.split(dropped).criteria_sha256 != adopted["criteria_sha256"]
    assert any("ir/RA-JAK-EXC-03.json" in s for s in sm.differences(adopted, sm.split(dropped)))


# ---------------------------------------------------------------------------------------------- site edits
def test_a_site_edit_of_a_threshold_is_refused_with_a_sentence() -> None:
    parts = sm.split(_second_site(_files("RA-JAK")))
    got = sm.site_edit(parts.protocol, parts.site, {"thresholds": {"tier_high_confidence": 0.75, "small_cell": 3}})
    assert isinstance(got, str)
    assert "the threshold thresholds.small_cell from 5 to 3 cannot be changed at a site" in got
    assert parts.criteria_sha256[:12] in got
    assert "new protocol version" in got
    with pytest.raises(sm.SiteEditRefused, match="thresholds.small_cell"):
        sm.apply_site_edit(parts.protocol, parts.site, {"thresholds": {"small_cell": 3}})
    got = sm.site_edit(parts.protocol, parts.site, {"thresholds": {"tier_high_confidence": 0.5, "small_cell": 5}})
    assert isinstance(got, str) and "thresholds.tier_high_confidence from 0.75 to 0.5" in got


@pytest.mark.parametrize(
    "changes",
    [
        {"criteria": ["RA-JAK-INC-01"]},
        {"version": "1.0.1"},
        {"terminology_release": "TR-000000000000"},
        {"thresholds": None},
        {"title": "another title"},
    ],
)
def test_a_site_edit_of_any_protocol_field_is_refused(changes: dict[str, Any]) -> None:
    parts = sm.split(_files("RA-JAK"))
    got = sm.site_edit(parts.protocol, parts.site, changes)
    assert isinstance(got, str) and "cannot be changed at a site" in got


def test_the_site_part_edits_freely() -> None:
    parts = sm.split(_files("RA-JAK"))
    new = sm.apply_site_edit(
        parts.protocol,
        parts.site,
        {
            "routing": {"list_to": ["pi@siteb.test"]},
            "scopes": {"screen": {"practitioners": ["D0002"], "departments": ["RHEUM-B"]}},
            "models": None,
            "status": "draft",
            # a protocol field sent back unchanged is no edit
            "thresholds": {"tier_high_confidence": 0.75, "small_cell": 5},
        },
    )
    StudySite.model_validate(new)
    assert new["criteria_sha256"] == parts.criteria_sha256
    assert new["manifest"]["routing"] == {"list_to": ["pi@siteb.test"]}
    assert "models" not in new["manifest"]
    m = RulesetManifest.model_validate(sm.merge(parts.protocol, new))
    assert m.status == "draft" and m.thresholds is not None and m.thresholds.small_cell == 5


def test_an_unknown_field_and_a_bad_site_value_are_refused() -> None:
    parts = sm.split(_files("RA-JAK"))
    got = sm.site_edit(parts.protocol, parts.site, {"recruitment_colour": "red"})
    assert got == "recruitment_colour is not a field of a study manifest"
    got = sm.site_edit(parts.protocol, parts.site, {"scopes": {"screen": {"appointment_window_days": "soon"}}})
    assert isinstance(got, str) and got.startswith("the site's change to scopes.screen.appointment_window_days")


def test_a_changed_protocol_part_or_a_foreign_site_part_is_refused() -> None:
    parts = sm.split(_files("RA-JAK"))
    tampered = {**parts.protocol, "manifest": {**parts.protocol["manifest"], "thresholds": {"small_cell": 1}}}
    assert sm.protocol_refusal(tampered) == "the study's protocol part was changed after its criteria hash was taken"
    with pytest.raises(ValueError, match="changed after its criteria hash"):
        sm.merge(tampered, parts.site)
    other = sm.split(_files("AD-MAB"))
    with pytest.raises(ValueError, match="another protocol part"):
        sm.merge(parts.protocol, other.site)
    assert isinstance(sm.site_edit(parts.protocol, other.site, {"status": "draft"}), str)


# ---------------------------------------------------------------------------------------------- a folder written at a site
def test_a_threshold_written_into_the_folder_at_a_site_is_named() -> None:
    files = _files("RA-JAK")
    adopted = sm.split(files).protocol
    edited = _with_manifest(_second_site(files), thresholds={"tier_high_confidence": 0.75, "small_cell": 2})
    got = sm.differences(adopted, sm.split(edited))
    assert len(got) == 1 and "thresholds.small_cell from 5 to 2" in got[0]
    assert sm.differences(adopted, sm.split(_second_site(files))) == []


def test_a_changed_criterion_file_at_a_site_is_named() -> None:
    files = _files("RA-JAK")
    adopted = sm.split(files).protocol
    ir = json.loads(files["ir/RA-JAK-INC-01.json"])
    ir["logic"]["age"]["min"] = 16.0
    changed = {**files, "ir/RA-JAK-INC-01.json": json.dumps(ir).encode("utf-8"), "ir/EXTRA.json": b"{}"}
    del changed["sql/RA-JAK.sql"]
    got = sm.differences(adopted, sm.split(changed))
    assert any("ir/RA-JAK-INC-01.json was changed at this site" in s for s in got)
    assert any("ir/EXTRA.json is not in the study's protocol" in s for s in got)
    assert any("sql/RA-JAK.sql is missing" in s for s in got)


def test_a_path_outside_the_folder_is_refused() -> None:
    with pytest.raises(ValueError, match="relative to its folder"):
        sm.split({**_files("RA-JAK"), "../manifest.yaml": b""})
