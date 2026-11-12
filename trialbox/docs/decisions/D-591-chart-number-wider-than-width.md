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
3. **The pid map refuses what must not happen.** One pseudonym for two different chart numbers (as written the
   site's way) in one batch raises; before, the first was kept and the second dropped without a word. With
   point 1 this cannot come from the normaliser; the check stays so that a later change cannot bring it back
   silently.
4. No pseudonym the box has made changes: no rule was set anywhere before #387.

## Not in this card

- Whether a chart number wider than the declared width should hold the patient table as a wrong column
  (`column_refusal`): not done. One odd row would stop a night; the row is kept apart, which is the safe side.
