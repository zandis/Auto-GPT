"""NEW-LIFE-2, the parser's half (deep review 2026-11-12, LIFE-002; placed with lane A2 on #593, 2026-11-15).

The parser flattened a section: a group's lead-in written as its own line ("Mild Alzheimer's disease dementia:",
no bullet) was glued to the end of the bullet before it, a bullet kept no parent, and a line's section was keyed by
its text, so a text in two sections carried the later one. Now a line that ends with a colon and has no bullet
starts an item of its own; the bullets after it name it as their parent; and ``IEBlock.item_refs`` gives, per kind
and in the items' order, each item's section, number and parent (positional, so a repeated text keeps its own
section). The compiler reads the groups from it (D-785's ``group_member``) instead of guessing from colons.
Public protocol text (ClinicalTrials.gov), no model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doc_parser.parser import ie_block, items_with_parents, parse, sections

ROOT = Path(__file__).resolve().parents[2]


def _eligibility(nct: str) -> str:
    data = json.loads((ROOT / f"tests/fixtures/public_protocols/{nct}.json").read_text("utf-8"))

    def find(o: Any) -> Any:
        if isinstance(o, dict):
            for k, v in o.items():
                got = v if k == "eligibilityCriteria" else find(v)
                if got:
                    return got
        return None

    return str(find(data))


TEXT = """Lead-in group:
* first alternative
* second alternative
Other group:
* third alternative
Required for all participants:
* age 50 to 90
"""


def test_a_lead_in_line_is_its_own_item_and_bullets_name_it_as_parent() -> None:
    got = items_with_parents(TEXT)
    texts = [t for t, _ in got]
    assert texts == [
        "Lead-in group:",
        "first alternative",
        "second alternative",
        "Other group:",
        "third alternative",
        "Required for all participants:",
        "age 50 to 90",
    ]
    assert [p for _, p in got] == [None, 0, 0, None, 3, None, 5]


def test_a_continuation_line_without_a_colon_still_continues_its_item() -> None:
    got = items_with_parents("* first line of an item\n  wrapped onto a second line\n* next item\n")
    assert [t for t, _ in got] == ["first line of an item wrapped onto a second line", "next item"]


def test_item_refs_are_positional_and_give_each_items_own_section() -> None:
    lines = ["# Inclusion Criteria (Part A)", "* Pregnancy test negative", "# Inclusion Criteria (Part B)",
             "* Pregnancy test negative", "* Completed Part A"]  # fmt: skip
    block = ie_block(sections(lines))
    refs = block.item_refs or {}
    assert [r.section for r in refs["inclusion"]] == [
        "Inclusion Criteria (Part A)",
        "Inclusion Criteria (Part B)",
        "Inclusion Criteria (Part B)",
    ]
    assert [r.n for r in refs["inclusion"]] == [1, 1, 2] and len(refs["inclusion"]) == len(block.inclusion)


def test_the_public_early_ad_protocols_groups_reach_the_parser_output() -> None:
    block = parse(_eligibility("NCT03887455").encode(), "x.txt").ie_block
    inc = block.inclusion
    refs = (block.item_refs or {})["inclusion"]
    lead = inc.index("Mild Alzheimer's disease dementia:")
    members = [inc[i] for i, r in enumerate(refs) if r.parent == lead]
    assert members and all("probable Alzheimer" in m or "CDR" in m for m in members)
    # the lead-in is no longer glued to the bullet before it
    assert not any(t.endswith("Mild Alzheimer's disease dementia:") and t != inc[lead] for t in inc)


def test_the_compiler_takes_groups_from_the_parser() -> None:
    """With the parser's parents, a group is exactly its bullets: a required line after the group is not a member,
    even with no new lead-in before it."""
    from criteria_compiler.structure import check

    lines: list[dict[str, Any]] = [
        {"text": "MCI due to AD:", "kind": "inclusion", "source_ref": "Inclusion #1", "parent": None},
        {"text": "Global CDR 0.5", "kind": "inclusion", "source_ref": "Inclusion #2", "parent": 0},
        {"text": "Age 50 to 90", "kind": "inclusion", "source_ref": "Inclusion #3", "parent": None},
    ]
    flags = {(f.index, f.flag) for f in check(lines).findings}
    assert (1, "group_member") in flags and not any(i == 2 for i, _ in flags)


# ------------------------------------------------------------------------------------------------- review fixes
def _check_parsed(text: str) -> dict[str, set[str]]:
    from criteria_compiler.structure import check

    block = ie_block(sections(["# Inclusion Criteria", *text.splitlines()]))
    pos = (block.item_refs or {})["inclusion"]
    lines = [
        {"text": t, "kind": "inclusion", "source_ref": f"{r.section} #{r.n}", "parent": r.parent}
        for t, r in zip(block.inclusion, pos, strict=True)
    ]
    out: dict[str, set[str]] = {}
    for f in check(lines).findings:
        out.setdefault(block.inclusion[f.index], set()).add(f.flag)
    return out


def test_bullets_under_a_bulleted_lead_in_are_still_members() -> None:
    """Review: with the parser's parents only an unbulleted lead-in had members; a bulleted one ("1. … 且符合下列條件：")
    lost the flag D-785 gave its bullets."""
    got = _check_parsed("* Diagnosis confirmed by:\n* biopsy\n* PET imaging\n")
    assert "group_member" in got["biopsy"] and "group_member" in got["PET imaging"]
    zh = _check_parsed("1. 類風濕性關節炎且符合下列條件：\n2. 經DMARDs治療六個月以上\n3. DAS28大於5.1\n")
    assert "group_member" in zh["經DMARDs治療六個月以上"] and "group_member" in zh["DAS28大於5.1"]


def test_a_wrapped_bullet_ending_with_a_colon_is_not_cut_in_two() -> None:
    """Review: "1. … with at least" / "two of the following:" was split, and the first half went on unflagged."""
    got = items_with_parents(
        "1. Documented history of treatment failure with at least\ntwo of the following:\n2. methotrexate\n"
    )
    assert got[0][0] == "Documented history of treatment failure with at least two of the following:"
    zh = items_with_parents("1. 類風濕性關節炎病患\n且符合下列條件：\n2. DAS28大於5.1\n")
    assert zh[0][0] == "類風濕性關節炎病患且符合下列條件："


def test_a_lead_in_ending_with_a_colon_and_a_stop_is_a_lead_in_for_both() -> None:
    got = items_with_parents("Patients with either condition:.\n* asthma\n* COPD\n")
    assert [p for _, p in got] == [None, 0, 0]


def test_the_parsed_doc_schema_says_its_version_moved() -> None:
    text = (ROOT / "schemas" / "parsed_doc.schema.json").read_text("utf-8")
    assert "1.1.0" in text and "item_refs" in text
