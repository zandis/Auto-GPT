# D-789 The parser keeps lead-ins, parents and each item's own section

- **Task:** NEW-LIFE-2, the parser's half (deep review 2026-11-12, LIFE-002; placed with lane A2 on #593)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-785 (a protocol's structure goes to a person)

## Decision

`doc_parser.parser.items_with_parents` splits a section as before, with one change: a line with no bullet that ends
with a colon (a stop after it allowed, the form `criteria_compiler.structure` reads) starts an item of its own (a
lead-in), and the bullets after it name it as their parent, up to the next lead-in. Before, such a line ("Mild
Alzheimer's disease dementia:" in a ClinicalTrials.gov text) was glued to the end of the bullet above it. Such a line
is a lead-in after a blank line, after a complete item, or when it does not start as a continuation; a wrapped
bullet's last line that starts in lower case or with a joining word ("… with at least" / "two of the following:",
"…病患" / "且符合下列條件：") still ends its item. On every shipped fixture protocol the items are unchanged; only the
public early-AD protocol's lead-ins come apart.

`IEBlock.item_refs` (optional, in `schemas/parsed_doc.schema.json`) gives, per kind and in the items' order, each
item's section title, its number in that section and its parent's index in the same kind's list. It is positional, so
a text found in two sections keeps its own section (`refs`, keyed by text, gave both the later one; it stays for
older readers; the schema's version is 1.1.0). The compiler reads `item_refs` when the parser gave them: a group
under a lead-in the parser recognised is exactly the items that name it, and each line's section is its own. Under a
bulleted lead-in ("1. …且符合下列條件："), which the parser does not take for one, D-785's reading of the colon line
above still makes the lines members.

## Not changed

The IR has no "any of" group yet (the next step, also lane A2's): the members still go to a person.

## Test

`tests/unit/test_parser_keeps_structure.py`.
