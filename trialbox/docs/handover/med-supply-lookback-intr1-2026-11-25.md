# INT-R1: a medication look-back counts an order whose supply reaches into the window

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Ordered by the owner through the integrator, 2026-11-25 (High, a ring-0 condition). The deep check on master
6c73db64, row R1 ("confirmed, run on synthetic data"). The files are lane J's and lane A2's (decisions register).
Synthetic data only. The decision is D-1073.

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
start falls back to `authoredOn`; with no end, the end is the last covered day, the start plus
`dispenseRequest.expectedSupplyDuration` less one day (ruling 2; a supply of 0 days ends on its start), in whole days (unit `d`/`day`/`days`, or `wk`/`week`/`weeks` times 7; anything else: no end). The OMOP source keeps the
same end (`verbatim_end_date`). The demonstration mapping (`demo_his.yaml`) writes `boundsPeriod` and
`validityPeriod` from the start and end dates; no other mapping was read.

## The decision (both engines)

* In a look-back with a first day (`window.from_days` set), a **dated** order counts when its order date is in the
  window, **or** when its supply period `[start, end]` overlaps the window `[index + from_days, index + to_days]`.
  The start is the therapy start, else the order date; the end is the lake's end as above.
* **Boundary: both ends inclusive**, as the window itself (`BETWEEN`, `Interval[...]`). A supply ending on the
  window's first day counts; one ending the day before does not.
* **No end** (ruling 1): an order written before the window, with no end, may have run into it, so it makes the answer
  unknown where nothing else settles it, never a silent no. An order in the window counts by its date, as before.
  The lake fills `start` from the order date, so an order with a start and no end and an order with only its date are
  the same row: both read unknown. It replaces the card's first rule (the order date
  alone, so "not met"), as the integrator ruled; there is no bound on its age for ring 0 (a later owner parameter).
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
ONC-OSI, RA-BIO, RA-COH and RA-JAK (`--check` is equal afterwards). NEUR-COH's only change is the mark line. **All eight need the
owner's re-approval**, as with D-656; no lane approves a ruleset.

## What moves in the goldens

`make goldens` (profile ci, both lake sources) changes 7 of 23 goldens. No golden row moves to unknown (0 of the screen's set and criterion rows, 0 verdicts), so the goldens do not exercise
the no-end rule: `tests/unit/test_med_supply_lookback_intr1.py` does. The count at a site is not known from this.

| Golden | What moves |
| --- | --- |
| `feas/basis@ci.json` | GOUT-COH-INC-03 coded, and RA-COH-INC-03 coded on one set (see the funnel) |
| `funnels/GOUT-COH@ci.json` | remaining at GOUT-COH-INC-03, and one `unknown_as_pass` variant |
| `funnels/GZQO@ci.json` | one patient of one set excluded by GZQO-EXC-04: later steps, variants, prevalence 8 to 7 |
| `funnels/RA-COH@ci.json` | remaining and unknown at RA-COH-INC-03 on one set |
| `screen/GOUT-COH@ci.candidates.json` | the outcomes hashes only |
| `screen/GZQO@ci.candidates.json` | GZQO-EXC-04 met +1, +4, +2, +2 over the four sets; candidates 13 to 12 on one set |
| `screen/RA-COH@ci.candidates.json` | RA-COH-INC-02 met +1, +2, +6, +3 over the four sets |

RA-COH-INC-03 (a DAS28) reads no medication. The funnel asks whether a patient passes every step so far at any one
month-end (`feas_compute.funnel_query`, `bool_or`), so a patient already counted at INC-02 can now pass INC-02 at the
same month-end as the DAS28. That is a reading of the code; the single patient was not traced.

## Existing tests changed, each ruled by the integrator

| Test | Change |
| --- | --- |
| `test_cql_sql_generators.py::test_atoms_cql_snapshot_and_determinism`, `::test_atoms_sql_snapshot_and_determinism` | `ATOMS.cql` and `ATOMS.sql` rewritten with the test's own `UPDATE_SNAPSHOTS=1` |
| `test_fhir_inbound_contract.py::test_medication_reference_is_resolved_and_statements_are_read` | 4 weeks end on 2026-03-28, the last covered day; was 2026-03-29 |
| `test_criteria_safety.py::test_cql_carries_the_same_rules_and_translates` | the new CQL text of the no-end rule; its other assertions stand |

## Duration criteria ("on drug X for at least N days", ruling 3)

The SQL built each order's period from the lake's `start` and `end`; the CQL read only the validity period and the
order date. Shown before the ruling: an order of 100 days given by its supply or its bounds alone was met in the SQL
and unknown in the CQL; bounds of 10 days beside a validity period of 100 was not met in the SQL and met in the CQL.
Now the CQL duration reads the period through the same functions as the look-back, and the engines agree on every
case of `test_a_duration_reads_the_same_period_in_both_engines`. An order with no end is unknown in both (D-275).
It changes GZQO-INC-06, RA-BIO-INC-03, RA-BIO-INC-04 and RA-JAK-INC-03: a supply of exactly the days short by one
(ruling 2) no longer reaches the minimum.

## Found, not fixed

* INTR1-03: the CQL retrieves `MedicationRequest` only; the lake's table also holds `MedicationStatement` rows.
* INTR1-04 (open, Medium): `services/matching/coverage.py` (the uncoded medication rows that make an inclusion unknown)
  still places an order by `authored` alone. The change is small, but the fixture table of
  `test_code_coverage.py::test_a_diagnosis_with_an_empty_code_is_unreadable` has no `start` and `end` columns, so that
  test's set-up (not its assertions) must change, which is not ruled.
* INTR1-05 (fixed here): the mark names D-1073, so SQL approved before it is guarded by the overlay, never run alone.
* INTR1-06: the SQL reads a date and time in the site's zone, the CQL in its own offset; a UTC evening differs by a
  day (shown on master with an order date; the supply's end follows it).
* INTR1-07: the lake keeps an order of status `unknown` undated, the CQL places it (shown on master).
* INTR1-08 (a separate card): a partial FHIR date stops the lake's rebuild. Reproduction: one `MedicationRequest` with
  `dispenseRequest.validityPeriod.end` = `2026-07`, then `Lake(...).rebuild(...)`: `flatten.ts`
  raises `ValueError: Invalid isoformat string: '2026-07'`.
* INTR1-09: the CQL duration atom does not match a listed ingredient stem (T-610), the SQL's does.
* An order written after the index date whose supply began before it now counts, as the overlap rule says.

## Tests

The supply cases' edges are the last covered day (ruling 2); the window's last day and the day after it are cases too.

`tests/unit/test_med_supply_lookback_intr1.py`:

* `test_the_sql_counts_a_supply_that_reaches_into_the_look_back` and `test_the_cql_says_the_same`: fifteen synthetic
  patients against "an anticoagulant within 90 days" (`any`, exclusion) and "none within 90 days" (`none`,
  inclusion): ordered inside (met); before, with a 30-day or 4-week supply reaching in (met; not met on master);
  before, with a validity period or a bounds period reaching in (met; not met on master); a supply ended before the
  window (not met); no end, or a unit the lake does not read (unknown, ruling 1); a unit
  given as padded text (met); a supply whose last covered day is the first day (met) or the
  day before (not met); an undated order, with a period or without (unknown, unchanged); no order (not met).
* `test_an_unbounded_medication_atom_compiles_as_before`.
* `test_every_shipped_medication_look_back_answers_the_same_in_both_engines` (the invariant): every shipped criterion
  with a medication look-back, through the SQL and the CQL on the same synthetic patients (dated from each
  criterion's own window), gives the same answers; for the six single-atom ones the supply case is met, the
  no-end case unknown and the ended case not met.
