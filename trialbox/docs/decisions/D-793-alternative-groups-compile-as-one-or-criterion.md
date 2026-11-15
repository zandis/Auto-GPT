# D-793 Alternative groups compile as one OR criterion

- **Task:** NEW-LIFE-2, the "any of" step (deep review 2026-11-12, LIFE-002; the design approved by the integrator on
  #639, 2026-11-15, under D-504)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-785 (a protocol's structure goes to a person), D-789 (the parser keeps lead-ins and parents)

## Decision

The compiler makes a set of alternative groups one criterion whose logic is `or(and(group 1), and(group 2), …)`,
built from the extracted IR of its lines (no new model call): the first lead-in's id, its text the lead-ins with their
lines, flags `any_of` and `needs_review` (a person confirms the reading at approval), class `structured`, no human or
note question. A lead-in classed `structured` carries a requirement of its own ("Aged 65 years or older with:"): it
is ANDed into its group. The set's other lines are dropped; a warning names them.

A set of alternatives (`criteria_compiler.structure.alternatives`), inclusion criteria only:

- two or more adjacent lead-in groups the parser gave (each line's `parent`, D-789), in one section, the first
  lead-in naming a diagnosis and each of the others short (at most 8 words, or 20 CJK characters) or naming one,
  none saying its lines are all required; or
- one lead-in that says "one of / any of / either … or / いずれか / 任一 / 之一" over two or more bullets, each
  bullet an alternative.

It is never an exclusion set, and never under a negated lead-in ("No history of any of the following:"). It is
combined only when every member is `structured`, no lead-in is note or mixed, none of its lines was reused from the
approved version, and none carries another structure finding (another phase, a second section, a glued heading);
otherwise its lines go to a person, as D-785 says. An OR excludes a patient only when every alternative fails.

The review of this card made the rule stricter than the design approved on #639: "each lead-in short" alone OR-ed
ordinary sub-headings ("Laboratory values:" / "Prior therapy:"), which are required together, so the first lead-in
must name a diagnosis.

The test case: the public early-AD protocol NCT03887455's MCI group and mild AD dementia group are one set; "Key
Inclusion Criteria that must be met by all participants:" opens none.

## Not changed

The engines: the IR's `or` and `and` were already compiled to SQL and CQL. A set with a note, mixed or human member
(an OR across the coded and the note stages) stays with a person; that is a later step. An approved combined
criterion's text matches no parsed line, so an incremental compile re-extracts its members and combines them again:
a reviewer's edit of the combined criterion is not kept across a new version of the protocol.

## Test

`tests/unit/test_any_of_groups.py`.
