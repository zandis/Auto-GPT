# D-1263 Criterion model v3 runs in the cascade, step 1: anchors, device and allergy, flip dates (10A-5)

- **Task:** lane J, plan 10 row 10A-5 (`docs/plan/47-plan-10-2026-11-18.md`; review 15 card B16-1,
  `docs/reviews/2026-11-root/15-patient-finding.md`). · **Date:** 2026-11-20 · **Status:** proposed with pull
  request #1253 · **Builds on:** plan decision 54 ("Criterion model v3: ruled yes" by the owner), review 15
  decision 1 ("yes, in steps behind an equivalence test"), D-17 (the window convention), D-1360 (the answer store).

## 1. The shape, and where it came from

Nothing here is a new design. Model v3 is the one already written: `libs/tb_contracts/criterion_ir.py`
(`CriterionIRv3`, spec v4 §6.2), which review 15 names as the model to make live (section 7, decision 1).

1. **Added to the model, and nothing else:** the anchor `planned_start` (the study's planned start of treatment for
   this patient) beside `index`, `event`, `screening` and `randomization`; the domains `device` and `allergy` beside
   the existing twelve. Review 15 section 7 lists exactly these. The event anchor (`window.event_atom`,
   `event_pick`), the `screening` anchor and `flip_rule` were in the model already.
2. **`ir_version` stays `3.0.0`.** The version is inside every criterion's canonical hash (§6.2.7). A new number
   would move the hash of every stored criterion, the judged-pair keys and the goldens. The change only adds
   members to two lists, so every document valid before is valid now.
3. **The v1 schema is not changed.** `schemas/criterion_ir.schema.json` takes none of the new members. The compiler
   checks a model's answer against that schema, so a wider v1 schema would change what a compile accepts today.
4. **A ruleset declares version 3 file by file.** A criterion file under `ir/` that says `ir_version` is read as a
   v3 criterion and kept (`Ruleset.v3`). A file that does not say it is read exactly as before; if it uses a v3
   member it is refused exactly as before. No manifest field was added.
5. **A v3 criterion also stands as a v1 criterion** in `Ruleset.criteria` (`criterion_ir.v1_face`), because about
   sixty modules read that list. Where v1 can write the criterion (a washout on the index date) it is that v1
   criterion and runs everywhere as one. Where v1 cannot (a window on a planned start, a device) it is shown the way
   the compiler already shows a line it cannot compile: class `human`, the line as its question, no coded logic. So
   a service that does not evaluate model v3 says "a person decides" and never answers such a criterion.

## 2. The engine

`services/matching/cascade/v3.py`, called from S1 of the cascade (`engine.py`). A ruleset with no v3 file builds no
such stage.

1. **One window convention, the existing one.** A structured v3 criterion whose windows hang on one anchor is
   lowered to the v1 criterion with index-relative windows (`criterion_ir.index_form`), and the compiled SQL of the
   existing generator is run with the index date set to the anchor's date. The interval is
   `[anchor + from_days, anchor + to_days]`, **both end days inside**, on the **local calendar date** of the record
   (`::DATE` of the lake's value, as D-17 says); the lake holds dates as the site wrote them, and no time zone is
   applied in the engine. No second window code exists.
2. **Every S1 rule applies, by the same function** (`_Run._s1_outcome`): an undated record, a unit that cannot be
   read, a proposed fact, a code system no row carries, a patient with no record of the kind.
3. **Anchors.** `index`: the run's index date. `planned_start`, `screening`: given by the caller per patient
   (`CascadeConfig.anchors`), never derived. `event`: the first or the last dated event of the event atom up to the
   index date.
4. **An unknown anchor date gives unknown** (`anchor_date_unknown`), never a guess: no date given for the patient,
   no event on record, or a matching event with no date (which one was first or last cannot be told).
5. **A window that reaches past the day of the run** (a planned start next week, an event ten days ago with a
   30-day window) is answered from the records only where a later record cannot change the answer: a record that
   already meets it and stays inside. Anything else is unknown (`verify_at_anchor`), never "met" and never "not
   met". This is spec v4 §6.2.4's table (DM-07).
6. **Device and allergy.** No lake table holds either kind, for either lake source (`lake.flatten.SCHEMAS`; the
   OMOP `device_exposure` table exists and nothing loads it; `AllergyIntolerance` is only validated by the adapter).
   A criterion with such an atom answers unknown with `not_in_source` for every patient. No reader was added.
7. **The flip date.** For a criterion a patient passes or fails by the records: the first day after the anchor's
   date on which, with the records as they are, the answer is the opposite one, or is open only because nothing is
   in the window any more (a result too old). With the closed 28-day window `[A-28, A]`, a last dose on day `d`
   gives the flip date `d + 29`. It is found by running the same SQL on the days a dated record enters
   (`d - to_days`) or leaves (`d - from_days + 1`) a window; no date arithmetic decides an answer. It is never
   computed from an undated record: such a record makes the answer on the way unknown and no date is given. Nor
   beside a record dated after the day of the run (an entry error or a plan, not a fact yet). A change that would
   fall on or before the day of the run (an anchor in the past) is not stored as a change to come. The lake rows
   the engine reads carry a date or none; no masked or shifted date exists in them. Cost: at most 64 days are
   tried per patient and criterion, soonest first, in one query per distinct day over the patients who need it.
   Computed for windows on the index date, the planned start and the screening date, for criteria whose atoms are
   records or values in a window. For a planned start it reads "the earliest start for which the washout is over".
8. **Stored where results already are:** `Outcome.flip_date` and `Outcome.anchor` in the trace (left out of the
   trace file when none, so a v1 trace is the bytes it was), and the `flip_date` column of `orch.answers` (D-1360),
   carried on `PatientVerdicts.flips`. **Shown nowhere:** no page, list, export or mail reads it. The watch-list
   card, 10A-11 (review 15 B16-7, owner decision 58), shows it.
9. **Three reason codes** (`tb_common.reasons`, with en, ja and zh-TW labels): `anchor_date_unknown`,
   `verify_at_anchor`, `not_in_source`. **What a user can newly see:** these three values, in the reason column the
   candidate list already has, on a v3 criterion's row only, for the roles that already read that column. No new
   column, page, export or reader. No rule of `code_of` leads to them and only the v3 stage names them, so no v1
   answer can carry one (ruled by the coordinator on 2026-11-20; the integrator's reviewer rules on it too).

## 3. Byte-identity for v1 and v2 rule sets

No stored rule set has a file that says `ir_version` (v2 was never a file format: `ir_semantics` reads a version no
stored criterion carries), so no stored criterion reaches any new code.

- `tests/unit/test_criterion_model_v3_step1.py::test_every_stored_ruleset_is_read_exactly_as_before`: all ten
  stored rule sets (eight shipped, two open-data) load with no v3 criterion, the same criteria and the same hashes.
- Head against master d28f6c03, one script on two worktrees: the five rule sets with a stored patient set
  (GOUT-COH, GZQO, ONC-OSI, RA-BIO, RA-COH; 200 patients each), through the cascade's files (traces, queue, final
  list, stage log, manifest) in both index modes, the verdict rows, the answer-store rows (10,800) and the v1
  evaluator: 65 sha256 lines, identical.
- `make goldens-check`, both lake sources: see the pull request for the run.

## 4. Limits of step 1

- Model v3 is evaluated by the cascade only (SCREEN's default pipeline). MICROBATCH's v1 re-check and
  `TB_SCREEN_PIPELINE=v1` show a criterion v1 cannot write as a person's; a re-check's answer stores no flip date,
  as it stores no rung.
- Sent to a person, not evaluated: windows on two anchors in one criterion; `randomization`; `event_pick: each`;
  macros; v3-only atoms other than the above (line of therapy, change, aggregate, dose: step 2, 10A-6); a v3
  criterion of class `note`, `mixed` or `human` that v1 cannot write.
- No flip date: a criterion that holds an age, a derived score or a medication duration (they change with the day
  for other reasons); an event anchor (time does not move it); more than 64 candidate days for one patient.
  Between two candidate days a record of a grouper's family outside its list can make the answer unknown; the flip
  date is the first day the listed records give the opposite answer.
- A v3 ruleset keeps v1 semantics in S1 (an inclusion's FALSE is "not met"). The switch CAS-19 describes for IR 2
  and later changes answers and belongs behind the equivalence gate (10A-6 onward).
- Nothing supplies a planned start or a screening date yet, so on a box these criteria answer
  `anchor_date_unknown` until a card does.

## 5. Follow-ups, named

0. Ruled by the coordinator on 2026-11-20: items 1 to 3 are follow-ups, not this card.
1. **The compiler emits v3** (washout and window lines with these anchors, device and allergy lines), behind the
   version the ruleset declares: not in this pull request. It needs the extraction prompt, its output schema and
   the post-processing, while pull request #1180 rewrites part of the latter. Card 10A-15 (the library wired into
   the compiler) is the nearest row; the coordinator places it.
2. **Where a patient's planned start and screening date come from: no card in plan 10** (tracks A and D were
   read). The caller's shape is fixed here: `CascadeConfig.anchors = {pid: {"planned_start": date, "screening":
   date}}`, absent means unknown. Spec v4 §6.2.4's "next appointment in the study clinic" is not built: it is a new
   use of appointment data and a guess. The coordinator raises the card.
3. **Device and allergy data in the lake: no card owns it.** Needed: `lake.flatten` reads `AllergyIntolerance`
   and `Device` / `DeviceUseStatement` into two lake tables (patient, code, system, date, status), for the legacy
   source; the OMOP source loads `device_exposure` and an allergy observation and `omop.export` writes the same two
   tables; the erasure registry and the goldens take them; then `PRESENCE` in the SQL generator gets the two
   domains and this stage's `not_in_source` rule goes. Sources: plan card 10B-7 (SS-MIX2 ADT-61 allergies into
   `AllergyIntolerance`) supplies the allergy resources for an SS-MIX2 site; no card supplies devices for any
   source, nor allergies for a CSV or FHIR feed. The coordinator raises it with the integrator.
4. **Showing the flip date**: 10A-11.
5. **The v1 path** (MICROBATCH's re-check) evaluating v3: with 10A-6, when v1 is retired behind the equivalence
   test (commitment C-1).

## 6. Held by

`tests/unit/test_criterion_model_v3_step1.py`: the 28-day washout before a planned start (day 27, 28, 29, a dose
with no date, a dose on the anchor day, two drugs, no planned start, a planned start in the future), the same
washout on the index date, a creatinine window before the screening visit, an infection window after the last
operation, a device and an allergy criterion, the answer-store row, the trace file, the v1 evaluator, the stored
rule sets; a record dated after the day of the run, a change already past, the bound of the flip-date search (100
dated doses), the v1 stand-in that no v1 reader can decide, and the three reason codes. Each expected answer is
written from the protocol sentence quoted in the test. Each rule was removed in turn on a separate worktree and at
least one test failed each time.
