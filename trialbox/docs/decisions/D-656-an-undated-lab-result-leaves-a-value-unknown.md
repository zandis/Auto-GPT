# D-656 An undated lab result leaves a value criterion unknown where it could change the dated results' answer

- **Task:** SCR-03 (lane G's deep review of 2026-11-13, Critical), routed by the owner through the integrator
- **PR:** this branch (`agent/SCR-03-undated-lab-values`), stacked on SCR-01 (`agent/SCR-01-malignancy-c44-c4a`,
  D-655), with the review's failing test taken from #501 (`fb2deff5`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on a green train). **GOUT-COH, GZQO, ONC-OSI, RA-BIO, RA-COH and RA-JAK need the
  owner's re-approval**: their SQL and CQL change; no lane approves a ruleset. AD-MAB and NEUR-COH do not change.
- **Builds on:** DUMP-01 / D-142 (an undated diagnosis leaves its criterion unknown), D-142 review B-01 (a row with
  no readable number never counts as a failed test), D-275 (a row whose unit cannot be used), T-613a / D-322 (the
  offline recompile)

## Context

A value criterion ("HbA1c above 10 %", "the latest urate at least 7.0", "the latest HBsAg positive") compares the
lab rows inside its window. A row with no date (a chart line with no date, kept undated by D-470; a sheet row
without a day; an old system's import) was dropped by the window test in both generators, the SQL
(`_obs_source`) and the CQL (`_obs_value`), so the equivalence gate agreed with the wrong answer. A dated normal
value then decided alone: a dated HbA1c of 6.1 % with an undated 11.2 % read as "clear" (a wrong inclusion); a
dated urate of 6.5 with an undated 8.8 as "not met" (a wrong exclusion). The presence atom has had its undated
branch since DUMP-01; the value atom never had one.

Confirmed by running before the change: `tests/unit/test_undated_lab_values.py` (#501's strict expected failure)
and `tests/unit/test_undated_lab_quantifiers.py` (5 of 7 patients wrong).

## Decision

An undated row cannot be placed in the window, nor, for `latest`, before or after the dated rows. **The dated
rows' answer stands only when every undated row, inside the window or not, newest or not, leaves it the same;
otherwise the answer is unknown** (NULL), and the undated rows are its evidence (`<id>|`, no date, as the presence
atom's). Per quantifier:

| Quantifier | The dated rows say | Unknown when an undated row |
| --- | --- | --- |
| `latest` | the newest dated row's answer | gives another answer, or none (no readable number) |
| `any` | not met | may meet the comparison (meets it, or has no readable number) |
| `none` | met | may meet the comparison |
| `all` | met | may fail it |
| `count>=` n | not met | the met rows, the unreadable ones and the undated ones that may meet it reach n |

"Undated" is what the lake reads as undated (`lake.flatten` `effective`: no dateTime, no instant, no period start),
in the CQL too: a result dated by an instant or a period only is dated in both engines. The evidence of an unknown
lists only the undated rows that could change the answer (one that may meet the comparison; for `all`, one that may
fail it).

A met `any`, a failed `all`, a reached `count>=` stand whatever the undated rows say. With no dated row in the
window the answer is unknown, as it was. Both generators say the same (the equivalence gate holds them equal).

Recompiled offline with the CQL translator (`tools.build_rulesets --recompile`); every shipped ruleset translates.

## Which decisions change

Only for a patient who has an undated result of the criterion's test; for every other patient nothing changes.
Every value criterion of the shipped rulesets uses `latest`, so: **the newest dated result's answer stands only
when every undated result gives the same answer; otherwise the criterion is unknown and kept for review.**

| Ruleset | Criteria |
| --- | --- |
| GOUT-COH | GOUT-COH-INC-02 (latest serum urate ≥ 6.0) |
| GZQO | GZQO-EXC-06 (latest HbA1c > 10 %), GZQO-EXC-08 (latest pregnancy test positive), GZQO-EXC-09 (latest systolic ≥ 160), GZQO-EXC-13 (latest ALT > 120), GZQO-INC-04 (latest serum urate ≥ 6.8 / ≥ 6.0) |
| ONC-OSI | ONC-OSI-INC-03 (latest EGFR mutation detected) |
| RA-BIO | RA-BIO-EXC-02 (latest IGRA positive), RA-BIO-EXC-03 (latest HBsAg positive) |
| RA-COH | RA-COH-INC-05 (latest HBsAg positive) |
| RA-JAK | RA-JAK-EXC-02 (latest HBsAg positive), RA-JAK-EXC-04 (latest IGRA positive) |

So an exclusion such as RA-JAK-EXC-02 no longer reads "not met" from a dated negative HBsAg when an undated
positive is on file (unknown: a person looks), and an inclusion such as GOUT-COH-INC-02 no longer reads "not met"
from a dated urate of 5.5 when an undated 8.8 is on file. The recorded test sets of the rulesets hold no undated
lab result: no expected verdict changes.

## Not changed

Derived scores (BMI, DAS28, eGFR; 13 criteria of the shipped rulesets) read the newest dated row of each input
the same way, and an undated input is dropped there too. Making such a score unknown needs a reason the console,
the PDFs and the mails can translate (`tb_common.reasons` is a closed set with catalogue keys), so it is a card of
its own, with lane C2. Until then an undated input of a score is ignored, as before.

What is not tested here: the CQL is translated to ELM (every shipped ruleset) and read against the SQL, but not
evaluated (no local CQL engine; HAPI runs in the integration stack). The equivalence gate's cases and the
synthetic sites' lab rows hold no undated lab result, so the gate does not yet compare the two engines on one. The
CQL's evidence lists the dated rows only (the gate compares answers, not evidence). A `latest` with undated rows
only stays unknown with no evidence, as before.

## Test

`tests/unit/test_undated_lab_values.py` (its marker removed: it passes) and
`tests/unit/test_undated_lab_quantifiers.py`: seven synthetic patients, five quantifiers, both directions (an
undated result that could change the answer makes it unknown; one that cannot leaves it standing; dated-only
answers unchanged), and the CQL of each quantifier consults the undated records.
