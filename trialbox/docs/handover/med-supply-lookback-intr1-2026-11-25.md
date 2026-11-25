# INT-R1: a medication look-back counts an order whose supply reaches into the window

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Ordered by the owner through the integrator, 2026-11-25 (High, a ring-0 condition). The deep check on master
6c73db64, row R1 ("confirmed, run on synthetic data"). The files are lane J's and lane A2's (decisions register).
Synthetic data only. Decision number needed (the decision is stated here and in the pull request).

## The fault

A medication criterion "within N days" read the order date only. The SQL placed a medication row by `authored`
(`services/criteria_compiler/compile_sql/generator.py:187-190`, the `PRESENCE` entry) and joined it to the window by
that date alone (`:223-229`, the `cte` join); the CQL did the same with `date from X.authoredOn`
(`services/criteria_compiler/compile_cql/generator.py:222`). A patient whose order was written before the window,
with a supply running into it, was read as not on the medicine: an exclusion ("no anticoagulant within 90 days")
let the patient through, an inclusion ("methotrexate within a year") left the patient out.

## Where the supply is carried

The lake's `medication` table has `authored`, `start` and `end`. `lake.flatten` `therapy` (STD-012, T-616) fills
`start` and `end` from `dosageInstruction[0].timing.repeat.boundsPeriod`, else `dispenseRequest.validityPeriod`; the
start falls back to `authoredOn`; with no end, the end is the start plus `dispenseRequest.expectedSupplyDuration` in
whole days (unit `d`/`day`/`days`, or `wk`/`week`/`weeks` times 7; anything else: no end). The OMOP source keeps the
same end (`verbatim_end_date`). The demonstration mapping (`demo_his.yaml`) writes `boundsPeriod` and
`validityPeriod` from the start and end dates; no other mapping was read.

## The decision (both engines)

* In a look-back with a first day (`window.from_days` set), a **dated** order counts when its order date is in the
  window, **or** when its supply period `[start, end]` overlaps the window `[index + from_days, index + to_days]`.
  The start is the therapy start, else the order date; the end is the lake's end as above.
* **Boundary: both ends inclusive**, as the window itself (`BETWEEN`, `Interval[...]`). A supply ending on the
  window's first day counts; one ending the day before does not.
* **No supply information** (no end): the order counts by its order date, exactly as before. A missing value never
  turns a met criterion into not met: the old test is one side of an `OR`.
* **An undated order** (no order date) stays unknown, as before (DUMP-01), whatever its period: it is not placed by
  its period here.
* A window with no first day ("ever", "any time before the index date") is not changed: its SQL and CQL are byte for
  byte what they were.
* The same placement is used for a grouper's off-list family codes (D-113), in the SQL and the CQL alike.
* The CQL reads the period as the lake does, in per-atom functions `TP_`, `SD_`, `TS_`, `TE_`.

Direction: an exclusion with `any` excludes more patients (correctly); an inclusion with `none` includes fewer; an
inclusion with `any` includes more.

## The criteria it changes

Eleven shipped criteria carry a medication presence look-back: AD-MAB-EXC-01, GOUT-COH-INC-03, GZQO-EXC-04,
GZQO-EXC-11, GZQO-INC-04, ONC-OSI-EXC-01, RA-BIO-EXC-02, RA-BIO-EXC-03, RA-COH-INC-02, RA-COH-INC-06, RA-JAK-EXC-04.
GZQO-EXC-11 is a `note` criterion: its medication logic is a structured proxy shown to a person and is run by
neither engine, so ten compiled criteria change. RA-JAK-EXC-01 has a medication atom with no window and does not
change.

The shipped rulesets' SQL carries the D-275 mark and is run as stored, so the fix reaches them only through a
recompile: `python -m tools.build_rulesets --recompile` rewrote the SQL, CQL and ELM of AD-MAB, GOUT-COH, GZQO,
ONC-OSI, RA-BIO, RA-COH and RA-JAK (`--check` is equal afterwards). NEUR-COH does not change. **These seven need the
owner's re-approval**, as with D-656; no lane approves a ruleset.

## What moves in the goldens

`make goldens-check` (profile ci) differed in 7 of 23 goldens, with the same values on both lake sources (legacy and
omop). The criteria whose own verdicts or counts moved are GOUT-COH-INC-03, GZQO-EXC-04 and RA-COH-INC-02, all
look-backs of this card; the other numbers are funnel steps, variants and candidate counts that follow from them.

| Golden | Why |
| --- | --- |
| `feas/basis@ci.json` | GOUT-COH-INC-03 coded +2, +2, +1 on three sets; RA-COH-INC-03 coded +1 on one set (see the funnel) |
| `funnels/GOUT-COH@ci.json` | remaining at GOUT-COH-INC-03 +2, +2, +1; one `unknown_as_pass` variant +1 |
| `funnels/GZQO@ci.json` | one patient of one set excluded by GZQO-EXC-04: every later step one fewer, and the variants and prevalence |
| `funnels/RA-COH@ci.json` | remaining at RA-COH-INC-03 +1 on one set, its unknown -1; RA-COH-INC-02's count there is the same |
| `screen/GOUT-COH@ci.candidates.json` | the outcomes hashes only |
| `screen/GZQO@ci.candidates.json` | GZQO-EXC-04 met +1, +4, +2, +2 over the four sets; one candidate fewer on one set |
| `screen/RA-COH@ci.candidates.json` | RA-COH-INC-02 met +1, +2, +6, +3 over the four sets |

RA-COH-INC-03 (a DAS28) reads no medication. The funnel asks whether a patient passes every step so far at any one
month-end (`feas_compute.funnel_query`, `bool_or`), so a patient already counted at INC-02 can now pass INC-02 at the
same month-end as the DAS28. That is a reading of the code; the single patient was not traced.

Written with `make goldens REASON=...`.

## The ATOMS snapshots: not changed here, a ruling is asked

`test_atoms_cql_snapshot_and_determinism` and `test_atoms_sql_snapshot_and_determinism`
(`tests/unit/test_cql_sql_generators.py`) hold the old text of the fixture's three medication look-backs and fail on
this branch. Proposed: rewrite `tests/fixtures/ir/snapshots/ATOMS.sql` and `ATOMS.cql` with the test's own
`UPDATE_SNAPSHOTS=1`. Only ATOMS-INC-18, ATOMS-EXC-23 and ATOMS-EXC-25 change, and the CQL library's content version.

## Duration criteria ("on drug X for at least N days")

Checked, not changed. The SQL (`_med_duration`) builds each order's period from the lake's `start` and `end`, so it
reads the supply. The CQL (`_med_duration`) reads only `dispenseRequest.validityPeriod` and `authoredOn`. Run on
synthetic orders through both engines ("at least 90 days"): an order of 100 days given only by its supply, or only by
its bounds period, is met in the SQL and unknown in the CQL; bounds of 10 days beside a validity period of 100 is not
met in the SQL and met in the CQL; a validity period alone is met in both. The shipped duration criteria are GZQO-INC-06, RA-BIO-INC-03,
RA-BIO-INC-04 and RA-JAK-INC-03. Those are other lines; reported as INTR1-02.

## Found, not fixed

* INTR1-03: the CQL retrieves `MedicationRequest` only; the lake's table also holds `MedicationStatement` rows.
* INTR1-04: `services/matching/coverage.py` (the uncoded medication rows that make an inclusion unknown) still places
  an order by `authored` alone: an uncoded order whose supply reaches into the window does not make it unknown.
* INTR1-05: SQL that a site approved before this change carries the D-275 mark, so `compile_sql.overlay` runs it
  alone, with the old fault, until it is recompiled. The mark is not raised here.
* INTR1-06: the SQL reads a date and time in the site's zone, the CQL in its own offset; a UTC evening differs by a
  day (shown on master with an order date; the supply's end follows it).
* INTR1-07: the lake keeps an order of status `unknown` undated, the CQL places it (shown on master).
* INTR1-08: a partial FHIR date (`2026-07`) as a validity period's end stops the lake's rebuild with a ValueError.
* An order with a start and no end (an open-ended order) has no supply information, so it counts by its order date.
* An order written after the index date whose supply began before it now counts, as the overlap rule says.

## Tests

`tests/unit/test_med_supply_lookback_intr1.py`:

* `test_the_sql_counts_a_supply_that_reaches_into_the_look_back` and `test_the_cql_says_the_same`: fifteen synthetic
  patients against "an anticoagulant within 90 days" (`any`, exclusion) and "none within 90 days" (`none`,
  inclusion): ordered inside (met); before, with a 30-day or 4-week supply reaching in (met; not met on master);
  before, with a validity period or a bounds period reaching in (met; not met on master); a supply ended before the
  window (not met); no supply information, or a unit the lake does not read (not met, unchanged); a unit
  given as padded text (met); a supply ending on the first day (met) and on the
  day before (not met); an undated order, with a period or without (unknown, unchanged); no order (not met).
* `test_an_unbounded_medication_atom_compiles_as_before`.
* `test_every_shipped_medication_look_back_answers_the_same_in_both_engines` (the invariant): every shipped criterion
  with a medication look-back, through the SQL and the CQL on the same synthetic patients (dated from each
  criterion's own window), gives the same answers; for the six single-atom ones the supply case is met and the
  no-supply case not.
