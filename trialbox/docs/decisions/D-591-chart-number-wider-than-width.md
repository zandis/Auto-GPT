# D-591 A chart number wider than the site's width keeps its leading zeros: two numbers never become one

- **Task:** a patient-identity finding of the review of PR #387 (the installer asks the chart-number rule), passed to
  lane E by the integrator on 2026-11-12; it lands with #387
- **PR:** this branch (`agent/DIN-chartno-wider-than-width`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-301 and R-48 (`tb_common/chartno.py`, the one chart-number normaliser), D-09 (the pseudonym is the
  keyed hash of the chart number)

## Context

Under a rule with a width (`digits:8`, `hex:8`), `normalise` removed the leading zeros of every value and padded
back only when the rest was shorter than the width. A value wider than the width lost its zeros and stayed
short: `012345678` (nine digits) became `12345678`, which is another patient's chart number. Two patients, one
pseudonym: one's facts screened, contacted and opted out as the other's. The module's own text says a number
longer than the width is never cut. Nothing set a rule until #387, so the fault was dormant.

## Decision

1. **A value wider than the rule's width is left as written** (full-width folded, blanks off, hexadecimal case
   made the rule's): its zeros are part of it. `012345678` under `digits:8` stays `012345678` and has its own
   pseudonym. It is never guessed to be `12345678`, and never to be the same as `0012345678`.
2. A rule **without** a width is unchanged: the site declared that leading zeros carry no meaning at any length.
3. **The pid map checks the normaliser, with a second rule.** One pseudonym for two different chart numbers in
   one batch raises `PidCollision` and nothing of the batch is stored; before, the first was kept and the second
   dropped without a word. Whether two spellings are one number is decided by `chartno.same_number`, written
   from the rule's words and not through `normalise`: with the old fault put back (a test does that), the pairs
   the night builds are refused. The check is within one batch; a pseudonym already in the map keeps its first
   chart number, as before.
4. No pseudonym an installed box has made changes: no rule was set anywhere before #387 (one scenario sets
   `digits`, without a width, in its own process).

## What this card does not make safe (said so #387 and DIN-003 are read with it)

- **One patient can now have two pseudonyms** where the old code gave one: the same person exported or typed
  with a zero more than the width (`012345678` on an eight-wide site). The box does not flag it: a fact table
  padded otherwise than the patient table is counted as orphans only; a patient table holding both spellings
  makes two patients; `column_refusal` says nothing. Before, that typing reached the eight-digit patient, which
  was right for a slip and wrong for a true nine-digit number. Two numbers made one is the worse fault.
- **The opt-out desk**: a refusal typed with an extra zero is registered under a pseudonym no feed row has, and
  the patient stays contactable. `/setup/pseudonym` does not check that the box knows the patient: that is
  DIN-003 (lanes C and D), and it must land with #387.
- **Setting a rule on a box that has already loaded patients changes their pseudonyms** (a chart number stored
  as `123456` under `asis` is `00123456` under `digits:8`); the pid map then reports a wrong site key. The rule
  is for installation, before the first night.
- `column_refusal` answers differently only for a pattern that contradicts the rule (pattern
  `^(\d{8}|\d{10})$` with `digits:8` and the value `012345678`: now `lost_zeros`).

## Not in this card

- Whether a chart number wider than the declared width should hold the patient table as a wrong column
  (`column_refusal`): not done. One odd row would stop a night; the row is kept apart, which is the safe side.
