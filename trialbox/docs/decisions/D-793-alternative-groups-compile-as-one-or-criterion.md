# D-793 Alternative groups compile as one OR criterion

- **Task:** NEW-LIFE-2, the "any of" step (deep review 2026-11-12, LIFE-002; the design approved by the integrator on
  #639, 2026-11-15, under D-504)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-785 (a protocol's structure goes to a person), D-789 (the parser keeps lead-ins and parents)

## Decision

The compiler makes a set of alternative groups one criterion whose logic is `or(and(group 1), and(group 2), …)`,
built from the members' own extracted IR (no new model call): the first lead-in's id, its text the lead-ins with
their lines, flag `any_of`, class `structured`. The set's other lines are dropped and carry no structure finding; a
warning names the lines. It compiles and is checked like any other criterion.

A set of alternatives (`criteria_compiler.structure.alternatives`) is:

- two or more adjacent lead-in groups the parser gave (each line's `parent`, D-789), in one section and kind, each
  lead-in short (at most 8 words, or 20 CJK characters) or naming a diagnosis, and none saying its lines are all
  required; or
- one lead-in that says "one of / any of / either … or / いずれか / 任一 / 之一" over two or more bullets, each bullet an
  alternative.

It is combined only when every member is `structured` and none was reused from the approved version; otherwise its
lines go to a person, as D-785 says. Lines without the parser's parents give no set. An OR excludes a patient only
when every alternative fails, so it never excludes more than the AND of before.

The test case: the public early-AD protocol NCT03887455's MCI group (three lines) and mild AD dementia group (two
lines) are one set; "Key Inclusion Criteria that must be met by all participants:" opens none.

## Not changed

The engines: the IR's `or` and `and` were already compiled to SQL and CQL. A set with a note, mixed or human member
(an OR across the coded and the note stages) stays with a person; that is a later step. An approved combined
criterion is matched by its text on an incremental compile like any other; its members are combined again when
re-extracted.

## Test

`tests/unit/test_any_of_groups.py`.
