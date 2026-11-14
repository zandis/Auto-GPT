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
  several alternatives, which made required would exclude every patient of the other group, silently. A lead-in
  whose last words say its lines are all required ("… must be met by all participants:", "… must agree to the
  following:") opens no group; only the last words count, because the parser glues a heading to the line before it;
- a line holding alternatives itself (`alternatives_in_line`): one of, any of, either … or, いずれか, 任一, 之一;
- a line with a capitalised section heading after text of its own, or a ja / zh-TW heading after a space at its end
  (`heading_in_line`): two lines glued together; "meets all inclusion criteria" and an NHI rule's "…之納入條件" are not;
- a line, or a section title, naming another study phase, part, period, stage or cohort (`other_phase`): an
  extension, a rollover, a study already completed; "Part B of the questionnaire" and "week 4 of the run-in" are not;
- a line of a second inclusion or exclusion section (`second_section`): another phase or population. Not for a
  cohort compile, whose two sections are its population and its counts (D-71). The parser keys a line's section by
  its text, so a text found in two sections decides nothing.

A criterion reused from the approved version keeps the reviewer's decision. The question says what to do (reject a
heading, rewrite a group as one criterion, reject another phase's line). The protocol-level warnings say there are
two sections, or that lines may be alternatives. A plain list is left alone; GZQO, AD-MAB, NEUR-COH, ONC-OSI, RA-BIO,
RA-JAK and the cohort documents compile as before. On the public early-AD protocol NCT03887455 the MCI and mild-AD
groups and the extension phases go to a person, and the lines every participant must meet compile.

## Not changed

The IR has no "any of" group yet (step 2, with the contracts owner); the parser still flattens a section and keys a
line's section by its text (its half of LIFE-002 is asked for on #593); the review sheet shows the flags as for any
criterion needing review.

## Test

`tests/unit/test_protocol_structure.py`.
