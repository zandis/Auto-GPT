# D-702 A command line that cannot be read is refused by its rule, not with what was typed

- **Task:** NEW-TRUST-7 (found by NEW-TRUST-6; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-7-grammar-refusals`), on top of NEW-TRUST-6
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-700 (the mail subject is refused by its rule)

## The problem

The command grammar of the console's request box and the chat channels (`services/channels/grammar.py`) refused a
line with the typed token in its text: `'<token>' must be key=value`, `unknown parameter '<name>'`,
`invalid value for window: '<value>'`, `invalid study code '<token>'`. The console shows the refusal and writes
it to the audit trail (`console.refused`), so a chart number typed in the wrong place was kept there.

## The decision

The four texts name the rule. A parameter's name is said only once it is one of the allowed names; the list of
allowed names stays in the text. The same rule as the mail subject's (D-700).

## What it does not do

- The other refusals of the grammar are usage lines written in the code (`REJECT <alias> <R01-R07> [free text]`)
  and are unchanged.
- `services/channels/` is in no lane's folder; this lane takes it because the pattern and the test are D-700's.

## Review

No reviewer was asked: four texts, by the rule a reviewer judged in D-700, with a test of each.

## Reuse check

D-700's test file holds it; nothing is added.

## Dropped (D-311)

No sign-off step.
