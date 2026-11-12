# 8. Derived scores

A derived score is computed from other rows: eGFR (CKD-EPI 2021 or JSN 2009), BMI, DAS28, BASDAI, ASDAS, CDAI and
SDAI. Code: `libs/tb_common/derived.py` (formulas, units, same visit), `libs/tb_common/scores.py` (definitions),
`libs/tb_common/derived_store.py` (stored rows), `services/matching/stored_scores.py` (the screening read) (D-149,
D-189, D-190, D-442).

**Definitions come from the catalogue.** Each score is a YAML file in `catalogue/scores/`: inputs, units, windows,
coefficients, edge cases and published worked examples. `python tools/gen_score_defs.py` writes them to
`libs/tb_common/score_defs.json`; the box reads only that file. A definition is named `<score_id>@<version>` (for
example `rheum.cdai@1`) and carries the sha256 of its YAML. A YAML that changed but kept its version is refused:
bump the version. The same-visit windows of CDAI, SDAI, DAS28-ESR and DAS28-CRP are read from the definitions.

**Units.** Every input is converted to the unit its formula expects (CRP mg/dL x 10 = mg/L; creatinine µmol/L /
88.4 = mg/dL). The CDAI and SDAI globals are on a 0-10 scale (LOINC 75844-1 and 75846-6); a 0-100 mm VAS recorded
under them is divided by 10, a 10 cm VAS is already 0-10, and a value outside 0-10 gives no value. SDAI takes the
CRP in mg/dL.

**No value is unknown.** A missing input, or a unit or scale that does not fit, gives no value and a reason
(`derived_missing_input:<input>`, `derived_unit:<input>`). Screening reads this as unknown, never as "no". A proposed
fact (read from a chart, not yet confirmed) never counts as an input; nor does a rejected or preliminary row. An
impossible value gives no value and `derived_unit:<input>` too: a negative CRP or ESR, a joint count outside 0-28, a
creatinine of 0 or less. An age of 0 or less gives `derived_missing_input:age`.

**No eGFR under 18** (D-442). Both eGFR equations are for adults (the catalogue's edge case "age < 18: do not
compute"). A patient under 18 gets no eGFR and the reason `derived_adult_only:age`, in the Python reference, the SQL
and the CQL. Screening uses the age at the index date; a stored row uses the age at its anchor (the creatinine's date).

**Status in the lake.** The status rule needs the row's status. The lake's `observation` table has no status column
yet, so the `derive` batch records each lake row's status as `not_recorded`, and such a row counts. Proposed facts
still never reach a stored score: the lake keeps them out of `observation` by their basis tag. But an
entered-in-error or preliminary row from the hospital feed is not filtered out until the lake carries
`Observation.status`.

**Screening.** The SQL and CQL engines compute the score per patient at the index date, from one visit: the newest
anchor input in the window (the joint count; the creatinine for eGFR) and the other inputs near it. CDAI and SDAI are
in both engines and in the Python reference, and a test checks that all three give the published worked examples
(`tests/unit/test_derived_definitions.py`). A criterion names its score (`cdai`, `sdai`, `egfr_jsn`, ...).

**Stored rows.** The `derive` batch (`derived_store.run_batch`, one patient at a time with
`DerivedStore.recompute`) writes CDAI, SDAI, DAS28-ESR, DAS28-CRP and both eGFRs to schema `derived` of the trial
database, one row per patient, score and anchor row:

| Table | What it holds |
| --- | --- |
| `definition` | the definitions in use: version, sha256, the full text |
| `score_row` | value (or no value and the reason), unit, anchor date, definition version and sha, the site mapping version, and every input: source table, row id, date, value and unit as recorded, status, and the value and unit the formula used |
| `input_link` | one row per input ("derived from") |
| `conflict` | a documented score that does not match the computed one |

A row is written only when something it depends on changed: an input added, corrected, confirmed or deleted, a new
mapping version, or a new definition version. Otherwise the batch writes nothing. A new row supersedes the old one;
rows are never changed in place or deleted. An anchor deleted at the source retires its row. A definition that
changed under the same version stops the store from opening. One patient whose recompute fails is counted in the
batch report, and the batch goes on with the next patient.

**Documented scores.** A score written in a note (a proposed fact) or signed by a physician is compared with the
computed row within 7 days of it. When they differ by more than the score's tolerance (CDAI and SDAI 0.5, DAS28 0.2,
eGFR 5), a `derived_vs_documented` conflict opens. Neither value is overwritten. The score reads as unknown until a
person chooses `keep_derived`, `keep_documented` or `both_at_dates`. A documented score with no computed row near it
stands alone, as what it is. When a row is recomputed, its conflicts move to the new row and are checked again
against the stored documented value, even if the batch was not given the documented scores. A conflict that still
differs stays open. A person's decision stays, unless the new value differs from the value they decided on by more
than the tolerance; then the conflict opens again.

**The batch after every ingest** (D-442). When an ingest passes, the job runner runs the `derive` batch over the new
snapshot, every patient, before the follow-up micro-batch screens (`orchestrator.derive.after_ingest`). Each batch
over a named snapshot is recorded in `batch_run` (snapshot, mapping version, the definitions it ran under, counts and
the patients that failed) and audited (`derive.batch`; a failed batch `derive.failed`, which never fails the ingest).

**Screening reads the stored rows, behind a flag** (D-442). The audited flag `derived.stored_read` (`/ops/flags`,
default `off`) decides for every path alike. Off, no path reads the store. It stays off until the age rule, the
pinned reads and the missing-batch warnings are proven on a real run. On, SCREEN (cascade and v1), MICROBATCH (new
patients and the re-check), NAV, CASE and COHORT all pass the approved SQL's rows through one function
(`matching.stored_scores.apply_rows`): the SQL still computes the score, and the stored row of the snapshot's batch
must stand behind every decided answer on CDAI, SDAI, DAS28 and eGFR. When it does not, the answer is "needs
information", never a new decided answer:

| What is found | Reason |
| --- | --- |
| no finished batch of the snapshot, a batch under other definitions than pinned, or a batch that failed for the patient | `derived_not_stored` |
| no row in the window, a row of another definition, a row of another visit than the engine's | `derived_not_stored` |
| a row computed under 18 at the creatinine's date for a patient who is 18 at the index date (one age rule) | `derived_not_stored` |
| a row with no value | its own reason (`derived_unit`, ...) |
| an open derived-vs-documented conflict | `derived_vs_documented` |
| the criterion's logic, in three values with the stored score values, cannot give the SQL's answer | `derived_vs_documented` (a kept documented value) or `derived_not_stored` |

The rows are read as they stood when the snapshot's first batch finished, so a re-run of a job reads what the job
read; a conflict opened or resolved later is read from the next snapshot on. A snapshot whose batch has not
finished is named on the readiness page, on the health line (`derive_batch`) and in the header of a screening list
that reads stored scores. BMI, BASDAI and ASDAS have no stored rows. FEAS counts read the SQL alone. Without a trial
database screening reads the SQL alone; the goldens are the SQL alone.

**One age.** The SQL, the CQL and the Python reference count complete years at the index date the same way: the day
before the birthday is still the younger age, so a 29 February birth turns 18 on 1 March of a common year.

**Rulesets pin the definitions** (D-442). An approval writes `derived_pins` in the manifest: for every score the
criteria use, the definition version and sha256 (`egfr` pins CKD-EPI 2021; `das28` pins both variants). A definition
of another version or text on the box puts the study in "approval needed" (`tb_common.ruleset.approval_state`, the
approval page names the score), and while the flag is on its criteria read "needs information" until the
investigator approves again. A study approved before D-442 pins nothing until its next approval (the approval page
says so); the committed rulesets are not back-filled.

Not yet: the console has no page for derived conflicts; the stored rows are not written to the OMOP `measurement`
table with `FACT_RELATIONSHIP`; FEAS counts still read the SQL alone; DAS28, BASDAI, ASDAS and MELD 3.0 still need
clinician worked examples before approval. For the lake owner: the lake's `observation` table should carry
`Observation.status` so that the batch can leave out entered-in-error and preliminary rows.
