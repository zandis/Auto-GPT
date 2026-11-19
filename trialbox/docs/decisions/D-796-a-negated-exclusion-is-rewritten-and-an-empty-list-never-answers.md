# D-796 A negated exclusion is rewritten, and a list with no code never answers

- **Task:** red of lane G's accuracy run on the real pair (#639, 2026-11-15, jmed); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the compiler's post-process rewrites an exclusion whose whole logic is negated (an atom with quantifier `none`, or `not(x)`) to the positive form and flags it `negated_logic_rewritten` and `needs_review`; the review page shows the negated form beside it. A negation inside the logic and every inclusion are left alone. (2) A value set with no code and no code family (a concept the terminology could not map) cannot answer: the runtime reads the answer it would give as unknown, reason `code_system_not_carried` (D-795), on the cascade and the SQL engine.
- **Why:** jmed's "history of diabetes" compiled as "none of diabetes" over an empty list: TRUE for every patient, so every patient was excluded.
- **Test:** `tests/unit/test_negated_exclusion_and_empty_lists.py`.

## A negated inclusion with presence logic goes to a person (card 10A-1, 2026-11-18)

Review 15 (finding 2.3.1): "PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", an inclusion, compiled
to "any of chemotherapy", which the patients it should exclude meet; item (1) leaves inclusions alone and nothing else
compared a coded inclusion with its line. An inclusion (structured or mixed) whose logic asks the presence of a
concept is flagged `negated_inclusion_presence` and `needs_review` and goes to a person (not rewritten: a rewrite
could be wrong too) when its line carries any negation cue that is not explained. The rule fails safe: a cue is
explained only when it is shown to be about something else (a bound such as "no more than 2", "超えない", "無…大於";
a word the cue negates instead, "not responded", "増悪が認められない"; another concept the line names). The scope
reading (ConText's) only lets a line run; it never decides that a negated line is safe. An atom that compares a
value, counts or takes the latest result asks a measure, not a presence, and is never held.

An approved inclusion an incremental compile reuses gets the same check and flag, with a warning. An approved line
on `main` keeps running until a person recompiles and approves: `make negated-inclusion-scan`
(`criteria_compiler.negated_inclusions`) and the doctor's `negated_inclusions` (a WARN) list such lines by ruleset,
version and criterion, and change nothing; the offline install of a ruleset reports its hits. Cue lists:
`services/criteria_compiler/ir_extract/negation_scope.py` (English adapted from medspaCy's ConText rules, MIT).
Test: `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over `tests/fixtures/negated_inclusion/`.

## Fewer unnecessary holds, and a list under one cue is held (card 10A-1b, 2026-11-19)

The `negated_inclusion_presence` flag now holds fewer lines that should run, and no fewer that should not. (1) The
line's other concepts: on the first compile, every concept candidate and its synonyms (as before); on the reused
approved path, the titles of the ruleset's ValueSets (each a candidate's name), where it passed none. Another concept
explains a cue only when it is not listed with this one under that cue: "No prior chemotherapy or radiotherapy" with
radiotherapy coded and chemotherapy a candidate ran on master as presence (12 of card 10A-1b's 40 new negated lines
did); it is held now. (2) A cue whose negated thing is no concept the line names is about something else only when
the cue and every mention of the coded concept are in different clauses split by a coordinating boundary (";", a
sentence end, "but", が、, て、, 但, 且), no mention's clause carries a cue, and the cue's clause has an object of its
own; with the cue's clause first, the boundary must be adversative. "Cannot tell" is held. (3) "No. 17" is a number.
Measured, missed and held unnecessarily, before and after: card 10A-1's table 0/116 and 8/69 to 0/116 and 6/69; the
lines unseen at design 0/21 and 20/23 to 0/21 and 12/23; card 10A-1b's 80 lines 12/40 and 18/40 to 0/40 and 1/40;
P2b's stored `ir_extract` replies (377 coded inclusions) 14 held, 6 unnecessarily, to 13 and 5. Exclusions are byte
for byte the same with the rule on and off. Lines: `tests/fixtures/negated_inclusion/card_10a1b.json`.
