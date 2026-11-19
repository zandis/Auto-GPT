"""10D-2 (D-1366; review 14 M14-1): the study manifest in a protocol part and a site part.

Proved by: one package (protocol part) on two sites (two site parts) gives the same criteria hash; a site edit of a
threshold is refused with a sentence; every shipped manifest loads unchanged through the split.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import study_manifest as sm
from tb_common.ruleset import SEED_RULESETS, Ruleset
from tb_contracts import RulesetManifest, StudyProtocol, StudySite
from tb_llm.prompt_registry import manifest_pins

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
    for name, fields in (
        ("study_protocol", (*sm.PROTOCOL_FIELDS, *sm.PROTOCOL_SUBFIELDS)),
        ("study_site", sm.SITE_FIELDS),
    ):
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
            "models": {"judge_prompt": "judge_v4"},
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
    extra = {**json.loads(files["ir/RA-JAK-INC-02.json"]), "id": "RA-JAK-INC-99"}
    changed = {
        **files,
        "ir/RA-JAK-INC-01.json": json.dumps(ir).encode("utf-8"),
        "ir/EXTRA.json": json.dumps(extra).encode("utf-8"),
    }
    del changed["sql/RA-JAK.sql"]
    got = sm.differences(adopted, sm.split(changed))
    assert any("ir/RA-JAK-INC-01.json was changed at this site" in s for s in got)
    assert any("ir/EXTRA.json is not in the study's protocol" in s for s in got)
    assert any("sql/RA-JAK.sql is missing" in s for s in got)


def test_a_path_outside_the_folder_is_refused() -> None:
    with pytest.raises(ValueError, match="relative to its folder"):
        sm.split({**_files("RA-JAK"), "../manifest.yaml": b""})


# ---------------------------------------------------------------------------------------------- the review's cases
#: RA-JAK's criteria hash as shipped: 10D-3 must reproduce it byte for byte from the canonical form of D-1366
RA_JAK_CRITERIA_SHA256 = "16e7b313accd9b1d0c3fa579949823963b1d333b1f925093a1912ab651e04b87"


def test_the_criteria_hash_of_a_shipped_study_is_its_golden() -> None:
    assert sm.split(_files("RA-JAK")).criteria_sha256 == RA_JAK_CRITERIA_SHA256


def test_the_canonical_form_sorts_keys_at_every_depth() -> None:
    assert sm.dumps({"b": {"y": 1, "x": 2}, "a": [3, {"d": 4, "c": 5}]}) == b'{"a":[3,{"c":5,"d":4}],"b":{"x":2,"y":1}}'
    parts = sm.split(_files("RA-JAK")).protocol
    shuffled = {k: parts[k] for k in reversed(list(parts))}
    shuffled["manifest"] = {k: parts["manifest"][k] for k in reversed(list(parts["manifest"]))}
    assert sm.canonical(shuffled) == sm.canonical(parts)
    assert sm.protocol_refusal(shuffled) is None


def test_the_canonical_form_of_numbers_and_text() -> None:
    assert sm.dumps({"a": 5.0, "b": 0.75, "c": 1e-05, "d": 2.0**60, "e": "é"}) == (
        '{"a":5,"b":0.75,"c":1e-05,"d":1.152921504606847e+18,"e":"é"}'.encode()
    )
    assert sm.dumps("é") == sm.dumps("é")
    with pytest.raises(ValueError):
        sm.dumps(float("nan"))
    assert sm.text(b"a\r\nb\rc\n\n\n") == b"a\nb\nc\n" == sm.text(b"a\nb\nc")


def _same_hash(changed: dict[str, bytes]) -> None:
    assert sm.split(changed).criteria_sha256 == sm.split(_files("RA-JAK")).criteria_sha256


def test_what_the_engine_reads_alike_hashes_alike() -> None:
    files = _files("RA-JAK")
    vs = json.loads(files["valuesets/VS_METHOTREXATE.json"])
    _same_hash({**files, "valuesets/VS_METHOTREXATE.json": json.dumps(dict(reversed(list(vs.items())))).encode()})
    _same_hash({**files, "notes.txt~": b"a stray editor file", "sql/.RA-JAK.sql.swp": b"x"})
    _same_hash(_with_manifest(files, thresholds={"tier_high_confidence": 0.75}))  # small_cell 5 is the default
    title = yaml.safe_load(files["manifest.yaml"])["title"]
    nfd = unicodedata.normalize("NFD", title + " é")
    assert nfd != unicodedata.normalize("NFC", nfd)
    assert (
        sm.split(_with_manifest(files, title=nfd)).criteria_sha256
        == sm.split(_with_manifest(files, title=unicodedata.normalize("NFC", nfd))).criteria_sha256
    )
    _same_hash({**files, "sql/RA-JAK.sql": files["sql/RA-JAK.sql"].replace(b"\n", b"\r\n")})
    ir = json.loads(files["ir/RA-JAK-INC-01.json"])
    ir["logic"]["age"] = {"min": 18, "max": 75}
    _same_hash({**files, "ir/RA-JAK-INC-01.json": json.dumps(ir, indent=4).encode()})


def test_a_site_part_carrying_a_protocol_field_is_refused() -> None:
    parts = sm.split(_files("RA-JAK"))
    for smuggled in (
        {"thresholds": {"tier_high_confidence": 0.75, "small_cell": 1}},
        {"criteria": ["RA-JAK-INC-01"]},
        {"models": {"judge": "x", "judge_prompt": "judge_v3"}},
    ):
        site = {**parts.site, "manifest": {**parts.site["manifest"], **smuggled}}
        with pytest.raises(ValueError, match="site part carries"):
            sm.merge(parts.protocol, site)
        assert isinstance(sm.site_edit(parts.protocol, site, {"status": "draft"}), str)
    foreign = {**parts.protocol, "manifest": {**parts.protocol["manifest"], "models": {"judge": "x"}}}
    foreign["criteria_sha256"] = sm.criteria_sha256(foreign)
    assert sm.protocol_refusal(foreign) == "the study's protocol part carries a site's models setting"


def test_the_judge_prompt_is_the_protocols_and_the_serving_model_the_sites() -> None:
    parts = sm.split(_files("RA-BIO"))  # no prompt_pins: models.judge_prompt is the judge's pin
    assert parts.protocol["manifest"]["models"] == {"judge_prompt": "judge_v4"}
    assert "judge_prompt" not in parts.site["manifest"]["models"]
    got = sm.site_edit(parts.protocol, parts.site, {"models": {"judge": "m", "judge_prompt": "judge_v3"}})
    assert isinstance(got, str) and 'the prompt pin models.judge_prompt from "judge_v4" to "judge_v3"' in got
    assert isinstance(sm.site_edit(parts.protocol, parts.site, {"models": {"judge": "m"}}), str)
    new = sm.apply_site_edit(parts.protocol, parts.site, {"models": {"judge": "m", "judge_prompt": "judge_v4"}})
    before = RulesetManifest.model_validate(sm.merge(parts.protocol, parts.site))
    after = RulesetManifest.model_validate(sm.merge(parts.protocol, new))
    assert after.models is not None and after.models.judge == "m"
    assert manifest_pins(after) == manifest_pins(before) == {"judge": {"version": 4}}
    b = sm.split(_with_manifest(_files("RA-BIO"), models={"judge": "other", "judge_prompt": "judge_v4"}))
    assert b.criteria_sha256 == parts.criteria_sha256
    c = sm.split(_with_manifest(_files("RA-BIO"), models={"judge": "other", "judge_prompt": "judge_v3"}))
    assert c.criteria_sha256 != parts.criteria_sha256


def test_differences_refuse_an_adopted_part_that_does_not_hold_its_hash() -> None:
    files = _files("RA-JAK")
    adopted = sm.split(files).protocol
    tampered = {**adopted, "manifest": {**adopted["manifest"], "thresholds": {"small_cell": 1}}}
    got = sm.differences(tampered, sm.split(files))
    assert got == [
        "the adopted protocol part cannot be trusted: the study's protocol part was changed after its criteria hash "
        "was taken"
    ]
