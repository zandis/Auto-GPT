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
#: RA-JAK's criteria hash as shipped: 10D-3 must reproduce it byte for byte from the canonical form of D-1366.
#: V-18b (D-1183) recompiled its medication ValueSets (no WHOCC names) and re-pinned its terminology release;
#: INT-R1 (D-1073) recompiled its CQL and SQL for the supply period; this is the recompile of both
RA_JAK_CRITERIA_SHA256 = "e5dd4f891814b5142556e5affaa4aab6cd17372a7d13b348b948d4991c539544"


def test_the_criteria_hash_of_a_shipped_study_is_its_golden() -> None:
    assert sm.split(_files("RA-JAK")).criteria_sha256 == RA_JAK_CRITERIA_SHA256


class _Recorded(bytes):
    """A file's bytes that note their path when the reader decodes them (``json.loads`` of bytes decodes too)."""

    opened: set[str]
    path: str

    def decode(self, *args: Any, **kwargs: Any) -> str:
        self.opened.add(self.path)
        return super().decode(*args, **kwargs)


def _opened_by_from_files(files: dict[str, bytes]) -> set[str]:
    opened: set[str] = set()
    recorded: dict[str, bytes] = {}
    for path, data in files.items():
        b = _Recorded(data)
        b.opened, b.path = opened, path
        recorded[path] = b
    Ruleset.from_files(recorded)
    return opened - {"manifest.yaml"}


def _planted(files: dict[str, bytes]) -> dict[str, bytes]:
    """Files the engine would read that a careless hash would miss, and files nobody reads."""
    lib = next(p for p in files if p.startswith("cql/elm/"))
    stem = lib.removeprefix("cql/elm/").rsplit(".", 1)[0]
    return {
        **files,
        f"cql/elm/{stem}.xml": b"<library>planted</library>",
        "cql/elm/sub/Other.cql": b"library Other",
        "cql/Extra.cql": b"library Extra",
        "notes.txt~": b"a stray editor file",
    }


@pytest.mark.parametrize("ruleset", SHIPPED)
def test_every_file_the_engine_reads_is_in_the_criteria_hash(ruleset: str) -> None:
    for files in (_files(ruleset), _planted(_files(ruleset))):
        opened = _opened_by_from_files(files)
        assert opened, ruleset
        assert opened <= sm.hashed_paths(files)
        assert opened <= set(sm.split(files).protocol["files"])


def test_a_planted_elm_file_changes_the_criteria_hash() -> None:
    files = _files("RA-JAK")
    planted = {**files, "cql/elm/TB_RA_JAK_v1_0.xml": b"<library>planted</library>"}
    assert sm.split(planted).criteria_sha256 != sm.split(files).criteria_sha256
    assert "cql/elm/TB_RA_JAK_v1_0.xml" in sm.split(planted).protocol["files"]


def test_the_canonical_form_sorts_keys_at_every_depth() -> None:
    assert sm.dumps({"b": {"y": 1, "x": 2}, "a": [3, {"d": 4, "c": 5}]}) == b'{"a":[3,{"c":5,"d":4}],"b":{"x":2,"y":1}}'
    # RFC 8785: by UTF-16 code units, so U+1F600 (a surrogate pair) sorts before U+FB01
    assert sm.dumps({"ﬁ": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"ﬁ":1}'.encode()
    parts = sm.split(_files("RA-JAK")).protocol
    shuffled = {k: parts[k] for k in reversed(list(parts))}
    shuffled["manifest"] = {k: parts["manifest"][k] for k in reversed(list(parts["manifest"]))}
    assert sm.canonical(shuffled) == sm.canonical(parts)
    assert sm.protocol_refusal(shuffled) is None


@pytest.mark.parametrize(
    ("value", "written"),
    [
        (5.0, "5"),
        (0.75, "0.75"),
        (-0.5, "-0.5"),
        (1e-06, "0.000001"),
        (1e-07, "1e-7"),
        (1.5e-10, "1.5e-10"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1.23e22, "1.23e+22"),
        (2.0**60, "1152921504606847000"),  # the shortest digits, padded with zeros (ECMAScript)
        (123.456, "123.456"),
        (2**53, "9007199254740992"),
        (-0.0, "0"),
    ],
)
def test_numbers_are_written_as_rfc_8785_writes_them(value: float, written: str) -> None:
    assert sm.dumps(value) == written.encode()


def test_what_json_cannot_say_exactly_is_refused() -> None:
    for bad in (2**53 + 2, float("nan"), float("inf"), "\ud800"):
        with pytest.raises(ValueError):
            sm.dumps(bad)
    with pytest.raises(ValueError, match="twice"):
        sm.load_json(b'{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="NaN"):
        sm.load_json(b'{"a": NaN}')


def test_strings_keep_their_exact_code_points() -> None:
    assert sm.dumps('a bé\x01\n"\\') == '"a bé\\u0001\\n\\"\\\\"'.encode()
    assert sm.dumps("é") != sm.dumps("é")
    assert sm.dumps({"é": 1, "é": 2}) == '{"é":1,"é":2}'.encode()


def test_text_files_lose_only_a_byte_order_mark_and_cr() -> None:
    assert sm.text(b"\xef\xbb\xbfa\r\nb\rc\n\n") == b"a\nb\nc\n\n"
    assert sm.text("é".encode()) == "é".encode()
    assert sm.load_json(b'\xef\xbb\xbf{"a": 1}') == {"a": 1}


def _same_hash(changed: dict[str, bytes]) -> bool:
    return sm.split(changed).criteria_sha256 == sm.split(_files("RA-JAK")).criteria_sha256


def test_what_the_engine_reads_alike_hashes_alike() -> None:
    files = _files("RA-JAK")
    vs = json.loads(files["valuesets/VS_METHOTREXATE.json"])
    assert _same_hash(
        {**files, "valuesets/VS_METHOTREXATE.json": json.dumps(dict(reversed(list(vs.items())))).encode()}
    )
    assert _same_hash(
        {**files, "valuesets/VS_METHOTREXATE.json": b"\xef\xbb\xbf" + files["valuesets/VS_METHOTREXATE.json"]}
    )
    assert _same_hash({**files, "notes.txt~": b"a stray editor file", "sql/.RA-JAK.sql.swp": b"x"})
    assert _same_hash({**files, "sql/RA-JAK.sql": files["sql/RA-JAK.sql"].replace(b"\n", b"\r\n")})
    ir = json.loads(files["ir/RA-JAK-INC-01.json"])
    ir["logic"]["age"] = {"min": 18, "max": 75}
    assert _same_hash({**files, "ir/RA-JAK-INC-01.json": json.dumps(ir, indent=4).encode()})


def test_what_the_engine_reads_differently_hashes_differently() -> None:
    files = _files("RA-JAK")
    title = yaml.safe_load(files["manifest.yaml"])["title"] + " é"
    nfd, nfc = (
        sm.split(_with_manifest(files, title=unicodedata.normalize(form, title))).criteria_sha256
        for form in ("NFD", "NFC")
    )
    assert nfd != nfc  # different code points: the hash covers exact text, no normalisation
    sql = files["sql/RA-JAK.sql"]
    assert not _same_hash({**files, "sql/RA-JAK.sql": sql + "-- é\n".encode()})
    # the hash covers what the manifest writes: an omitted default is not the same text as a written one
    assert not _same_hash(_with_manifest(files, thresholds={"tier_high_confidence": 0.75}))


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
    got = sm.site_edit(parts.protocol, parts.site, {"models": {"judge": "m", "judge_prompt": None}})
    assert isinstance(got, str) and "models.judge_prompt" in got
    before = RulesetManifest.model_validate(sm.merge(parts.protocol, parts.site))
    for edit in ({"judge": "m"}, {"judge": "m", "judge_prompt": "judge_v4"}):
        new = sm.apply_site_edit(parts.protocol, parts.site, {"models": edit})
        assert new["manifest"]["models"] == {"judge": "m"}
        after = RulesetManifest.model_validate(sm.merge(parts.protocol, new))
        assert after.models is not None and after.models.judge == "m" and after.models.judge_prompt == "judge_v4"
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
