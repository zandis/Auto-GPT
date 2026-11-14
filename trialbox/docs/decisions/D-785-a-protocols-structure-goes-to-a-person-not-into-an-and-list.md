# D-785 A protocol's structure goes to a person, not into an AND list

- **Task:** NEW-LIFE-2, compiler half (deep review 2026-11-12, LIFE-002)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-14
- **Status:** reserved
- **Builds on:** D-98 (an uncompilable criterion goes to a person), D-782 (an undefined value set goes to a person)

## Decision

The compiler reads the structure of the lines the parser gives it (`criteria_compiler.structure.check`). Each of the
following is sent to a person (class `human`, flags `needs_review`, `structure` and what was found), with one warning
per criterion that says why:

- a line ending with a colon (`group_heading`): a heading, or the lead-in of a group;
- each line under such a lead-in, up to the next lead-in or the end of its section (`group_member`): perhaps one of
  several alternatives, which made required would exclude every patient of the other group, silently;
- a line with a section heading inside it, after text of its own (`heading_in_line`): two lines glued together;
- a line naming another study phase (`other_phase`): an extension, a later part, a study already completed;
- a line of a second inclusion or exclusion section (`second_section`): another phase or population.

The protocol-level warnings say there are two sections, or that lines under a lead-in may be alternatives. English,
Japanese and Traditional Chinese forms are read. A plain list is left alone; the shipped GZQO compile is unchanged.

## Not changed

The IR has no "any of" group yet (step 2, with the contracts owner); the parser still flattens a section (its half
of LIFE-002 is asked for on #593); the review sheet shows the flags as for any criterion needing review.

## Test

`tests/unit/test_protocol_structure.py`.
