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
