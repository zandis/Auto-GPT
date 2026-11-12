# Architecture review, seam `decision`: the screening decision path (2026-11-12)

Master at `3259fb2f` (worktree `/home/user/wt-arch-decision`, read-only). Paths are under `trialbox/`.
"CONFIRMED (run)" = a throwaway test passed on master; "read" = code reading only. Throwaway tests and venv symlinks
are removed.

## 0. Corrections to "what is already known"

- **Snapshot pin is done and is structural.** `Ctx.services` (`services/orchestrator/core.py:131-137`) hands every
  scenario a `PinnedLake` (`services/orchestrator/jobs.py:64-147`, D-383): every `query` and `chunks_search` without a
  snapshot gets the job's pin. So `nav.py`, `microbatch.py:194`, `twpas.py:70`, `facts.py`, `screen.confirmed_facts`
  (`screen.py:603`) and the v1 judge (`evaluate.py:274`, `:302`) no longer read CURRENT inside a job. This is the one
  column of the matrix that is the same on every job path, and it is the model for the rest.
- **The SCREEN goldens do not run the cascade at all.** `tools/goldens.py:267-308` computes
  `screen/<rs>@ci.candidates.json` from `SqlEngine.evaluate` + `structured_candidate` (the v1 structured filter). S0
  (consent), the S1 index-date choice, S2 to S5, `verdicts_of`, tiers, opt-out, the pool and delivery are in no golden.
- **T-652's decision table exists but no engine calls it.** `services/matching/verdict.py` is imported only by the
  equivalence gate (`direction_changes`) and by `tests/unit/test_verdict_table.py`, which checks the two engines'
  own copies against it (parity test, not one code path).
- **Plan §7.5 names `property` and `differential` CI gates; no workflow has such a job** (job names of
  `.github/workflows/trialbox-*.yml`: lint, types, docs, contracts, trace, standards, unit, goldens, data-scan,
  security, shell, images, demo-boot; nightly: mutation, branch-coverage).

## 1. The matrix (rows = paths, columns = shared inputs and rules)

Legend: `=` same single function as the row above; **bold** = differs.

| Path | Entry | Snapshot | Opt-out register | Consent (lake `consent`) | Ruleset + pins | Criteria engine | Derived / age | Proposed facts, code gaps | Note window, excerpts, "left out" | Judge / verifier, failure | Budgets, unprocessed | Verdict -> status | Writes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SCREEN cascade (default) | `screen.py:743`, `:514-529` | pin, `screen.py:749` | scope: as of job receipt `screen.py:173,511`; again "now" at publish `:756`, list `:678`, pool `:637` | S0: `CONSENT_SQL` last row by date, no date bound, no entered-in-error filter, `rejected` -> out of scope, `contact_ok False` -> excluded `engine.py:265,365-381`, `screen_cascade.py:192-194` | `require_approved` `screen.py:746`; judge prompt pin `screen.py:228`; lexicon from code (`engine.py:238-246`, `cfg.lexicon` never passed `screen_cascade.py:316-332`) | `safe_sql` at one index date `engine.py:419` | inline SQL `date_sub('year')` `generator.py:359,504` | `Coverage`, `Proposed` `engine.py:420-421,476-547` | `window_of` `engine.py:225`; lexicon-hit notes, else top-5 sentences by `HashEmbedder` `engine.py:715-735`, `screen_cascade.py:338`; `excerpt_set` `:589`; notes without a hit/top-5 sentence not counted | `OrchestratorJudge` -> `judge_excerpts` (pair) `screen_cascade.py:78-93`; S4 second opinion `engine.py:954-983`; `check_failures` >10 % fails job `:111` | `max_pairs` 20,000 -> `unknown`/"unprocessed (budget)" `engine.py:901-911` | **`_Run.tiers` `engine.py:1004` + `verdicts_of` `screen_cascade.py:162-200`** | xlsx+json list, referrals, pool, `excluded_*.json`, summary `screen.py:658-878` |
| SCREEN v1 (`TB_SCREEN_PIPELINE=v1`) | `screen.py:556` | = | = | **none** | = | `SqlEngine` `evaluate.py:108` (same `safe_sql`) | = | = (`evaluate.py:115-140`) | **`note_window` `evaluate.py:164` (duplicate); `chunks_search k=5` `:274`; left_out counts only retrieved chunks over budget `:279-292`; full record only when the answer is unknown and <= 100 candidates `:702`** | `judge_excerpts` (pair) `:376`; `check_judge` | **none; `FULL_RECORD_MAX_CANDIDATES=100`** | **`tier` `evaluate.py:621`** | = |
| MICROBATCH new patients | `microbatch.py:290` -> `run_screen(select=)` | pin `:182` | = (via `run_screen`), pool `:298` | = cascade S0 | `require_approved(version=None)` `:173` | cascade | = | = | = cascade | = cascade | night budget in patients `:95`, carried over `:287` | cascade | pool, `new_screened_*.json`, list |
| MICROBATCH re-check | `microbatch.py:214` | pin | as of receipt `:207`; now at pool/list | **none** | = ; **pool rows of any stored version re-tiered `:161,243`** | **v1 `SqlEngine`, time-sensitive criteria only** | = | = | **v1 chunks** | v1 pair; `check_judge` | night budget; not re-checked rows keep old verdicts | **`tier` over stored cascade verdicts + fresh v1 verdicts, with today's `may_block` `:218,244`** | pool `:259`, weekly list |
| NAV | `nav.py:131` | pin `:138` | as of receipt `:113,155`; now at publish `:217` | **none** | `require_approved`; no `require_open` | v1 `SqlEngine`, all kinds `:174` | SQL for the decision; **Python `derived.compute("das28")` for the draft and TWPAS bundle `facts.py:164`** | = v1 | v1 chunks | v1 pair; `check_judge` `:185` | none | **`_ok` + `classify` `nav.py:60-110`: ignores `tier`, `note_block` and the over-budget flag** | NAV xlsx/json, drafts, TWPAS bundle |
| CASE | `case.py:328` | pin `:188` (only with `mrn=`) | as of receipt `:199,348`; **no re-read at publish** | **none** | `require_approved` | v1 `SqlEngine` one pid `:260`; **without a pid every structured criterion goes to the judge on the chart `:268-271`** | = | = v1 | `note_window`; **the whole uploaded chart in the window, no budget, no left_out `:221-232`** | `judge_excerpts`; **no `check_judge`, no note-block** | none | **none: per-criterion verdict printed; a single model's "not met" is printed as not met `:301-306`** | sheet html/json |
| FEAS | `feas.py:30`, `feas_compute.py:281` | pin `feas.py:44` | **none (FG D-278, CR-026 open)** | **none** | `approved_or_none`/`require_approved` | `safe_sql` at month-ends `:282,271`; **inclusion needs `IS TRUE` `:221-226`** | = | **not applied to counts; reported beside them `:315-325`** | no notes (D-101) | none | none | **funnel SQL: unknown inclusion drops, variant "unknown as pass" beside it** | pdf/xlsx/json (aggregate), `raw.json` with prevalent pids (box only) |
| COHORT | `cohort.py:275` | pin `:285` | **none** | **`contactable_pids`: latest statement on or before the quarter end, fail-closed ties `cohort.py:124-152`** | `require_approved` | `safe_sql` at quarter ends, `is True` `:104-121` | = | **not applied** | no notes | none | none | counts only | csv/pdf |
| Console read side | `console/home.py:330-365`, `screening_log.py:187,208,387` | **CURRENT at page view (`deceased_now`, `orchestrator/app.py:647-651`)** | **`OptOutRegister.active()` now, without merged-chart survivors (`optout.py:175` vs `:184`)** | none | stored job outputs of whatever version | none | n/a | n/a | n/a | n/a | n/a | **re-decides who is shown: drops opted-out and deceased rows, adds "sent back" not-matched patients as `review` (`notmatched_pages.py:62`)** | pages, registry promote/export (`candidates.py:121-160`) |

One function on every path (good, keep): `require_approved` (`scenarios/review.py:182`), `safe_sql`
(`compile_sql/overlay.py`), `NoteJudge.judge_excerpts` -> `pair.combine` (`evaluate.py:376`, `libs/tb_common/pair.py`),
`judge_for`/`pinned_judge` (`screen.py:217-237`), `Ctx.publish` (`core.py:173`), the lake pin.

## 2. Findings

### HIGH

**H1. A single model's "not met" becomes an exclusion one run later (the pair invariant, across SCREEN -> pool ->
MICROBATCH). CONFIRMED (run).**
1. SCREEN runs while a note answer may not exclude (no verifier, one model twice, or the canary gate shut:
   `effective_note_block`, `evaluate.py:590-614`). The cascade maps the judge's sure "not met" to a soft fail
   (`engine.py:860-868`, `hard=False`), tier `potential:uncertain` -> `review`.
2. `verdict_of` (`screen_cascade.py:126-159`) writes it as `verdict="fail"`, confidence 0.95, reason `note`. `hard`
   is not a field of `CriterionVerdict`; the pool stores the row (`screen.py:636-655`).
3. Next week MICROBATCH re-tiers every pool row with `tier(rs, ordered, t, note_block=may_block)`
   (`microbatch.py:218,244`), where `may_block` is today's policy. If the pair is now allowed to block, the stored
   single-model fail is a sure note fail: `excluded` (`evaluate.py:641-645`). The patient leaves the weekly list and
   the pool row is overwritten as excluded (`:259`). No second model ever agreed.
   Run: `verdict_of(soft fail)` -> `verdicts_of(...).tier == "review"` -> `tier(..., note_block=True) == "excluded"`.

**H2. NAV drops a patient on one model's note answer, with no review row. CONFIRMED (run).**
`evaluate_patients` computes a tier with the run's note-block, NAV discards it and calls `classify`
(`nav.py:199-201`). `_ok` (`nav.py:60-66`) says "no" for any note fail with confidence >= threshold, whatever
`effective_note_block` says, and "yes" for a pass flagged `notes_over_budget`. A patient with every inclusion met
and one exclusion "present" by a single model gets `name is None` and `missing == []`: on no sheet. Without a
verifier (single-GPU profile, D-95) every NAV exclusion by notes is a single-model exclusion.

**H3. MICROBATCH re-tiers pool rows of another ruleset version as if they were today's. CONFIRMED (run) for the
tier; version handling by reading.** `pool(rs.id)` returns rows with their stored `version`
(`orchestrator/db.py:298-303`); `microbatch.run` never compares it with `rs.version`. `ordered = [new[c.id] for c in
rs.active() if c.id in new]` (`:243`) silently leaves out every criterion the new version added, so a row with all
old criteria met is `high`; `persist_pool` then stamps the row with the new version (`screen.py:639-641`). Nothing
invalidates the pool at approval (`pool_remove` is called only by the opt-out worker). Result: after an amendment the
weekly list shows patients as fully matched against a protocol version they were never evaluated on, until the next
full SCREEN.

**H4. The same note question is answered from different text on each path, and a "not met" from a cut record
excludes on the v1 path too (Excerpts invariant). Read; the cascade half is the known PR #275.**
- Cascade: lexicon-hit notes, else notes holding the top-5 sentences of `HashEmbedder` (a test embedder used in
  production SCREEN, `screen_cascade.py:338`); notes without one are neither shown nor counted (`engine.py:724-735`).
- v1 (NAV, MICROBATCH re-check, SCREEN v1): `chunks_search(k=5)`; `left_out = len(hits) - len(out)` counts only the
  five retrieved chunks that did not fit (`evaluate.py:274-292`). Every other chunk of the window is "not left out",
  so both models agreeing "not met" on five chunks is a hard exclusion (`judge_patient` `:322-341`, `tier` `:641`).
  The full record is read only when the first answer is unknown (`:702`). PR #275's branch touches
  `matching/cascade/engine.py`, not `evaluate.py` (diff stat of `origin/agent/T-203b-s2b-vector-store`).
- CASE: the whole chart, no budget.
So SCREEN (cascade) and the MICROBATCH re-check of the same time-sensitive note criterion on the same snapshot can
disagree, and the re-check's answer overwrites SCREEN's in the pool (`microbatch.py:226-241`).

### MED

**M1. Three places turn verdicts into a status, and they disagree on four rules. Read (+ H1, H2 runs).**
`engine._Run.tiers`+`verdicts_of`, `evaluate.tier`, `nav.classify`; CASE has none. Differences: (a) a low-confidence
"met": cascade keeps it as `pass`/strong unless the pair's floor of 0.5 caught it (`_map` checks the confidence
floor only on the excluding side, `engine.py:858`), `tier` sends a pass below the 0.75 threshold to review
(`evaluate.py:654`); (b) `contact: deny`: cascade excludes, v1 lists (D-441 "not done"); (c) the soft/hard flag (H1);
(d) the over-budget flag: cascade and `tier` -> review, NAV -> "yes".

**M2. Consent has three rules and five paths that apply none. Read (known in part).** Cascade S0 takes the last row
by date with no "on or before the run date", no `entered-in-error` filter and no tie rule, and DuckDB sorts an
undated row last, so an undated statement is the newest (`engine.py:265,365-381`); `optout.registry_rule`
(`optout.py:209`) and `cohort.contactable_pids` treat it as the oldest and fail closed on ties. v1 SCREEN, MICROBATCH
re-check, NAV, CASE and FEAS do not read `consent`; they depend on the opt-out worker having copied refusals into
the register (`datacore/optout_worker.py:129-137`), i.e. on a tick having run after the ingest.

**M3. The register is read by two different functions. Read.** Jobs use `opted_out()` (with merged-chart survivors,
`optout.py:257-275`); the console pages use `OptOutRegister.active()` (`home.py:339,1557`, `screening_log.py:187,208,
387`), which does not add the surviving pid (`optout.py:175-186`). A merged chart whose old number opted out is off
every new list but still shown from stored `candidate_list_*.json`. `opted_out()` also returns the empty set when
`TB_DB_URL` is unset (`:262-263`), which is the state of most unit tests and of the goldens.

**M4. FEAS counts and SCREEN lists are different populations by rule, not only by scope. Read.** For the same
snapshot: FEAS drops an inclusion with no value (`IS TRUE`, `feas_compute.py:224`), SCREEN keeps it for review
(`engine.py:525-528`); FEAS counts opted-out and consent-refused patients, SCREEN removes them; FEAS ignores the
F-10 code-gap and proposed-fact overrides, SCREEN turns those answers to unknown; FEAS evaluates at month-ends and
takes the best month, SCREEN at the run date. A patient can be on the SCREEN list and outside the FEAS count, and
the reverse. T-216 and FG D-278 each own one of these; nothing states the relation or tests it.

**M5. A patient's status depends on how many other patients are in the run. Read.** `FULL_RECORD_MAX_CANDIDATES =
100` (`evaluate.py:47,702`): with 101 candidates nobody gets the full-record read. `max_llm_items`
(`engine.py:901`): who is "unprocessed" depends on thread order. Both fall to `unknown` (safe side), but T-694's
batching and T-689's replay will change these counts, so lists will move when the batch size moves.

### LOW

- L1. `approved_or_none` picks the version in force on `ctx.orch.today()` (`review.py:32`), the job uses
  `ctx.today()` (the job's run date, `core.py:151`): a job resumed after midnight can run day N's dates on day
  N+1's ruleset.
- L2. Two `PinnedLake` classes (`jobs.py:64`, `rerun.py:32`); the re-run one drops `snapshot` in `chunks_search`
  (`rerun.py:42`) and is only correct because `Ctx.services` wraps it again.
- L3. Reasons travel as `Reason` codes on v1 and as English engine strings matched by substring on the cascade
  (`reasons.py:56-81,211`); rule order decides ("not judged: ... did not fit" is `notes_over_budget` only because
  that rule comes first).
- L4. `window_of` (`engine.py:225`) and `note_window` (`evaluate.py:164`) are two copies of one rule.
- L5. Affirmative semantics (`absent_is_unknown`) exists only in the cascade; v1 has no such rule. Not reachable
  today: runtime criteria carry no `ir_version` (`engine.py:211-214`), so every production run is `v1`. Latent.
- L6. NAV shows a DAS28 from the Python reference (`facts.py:164`) beside a decision made by SQL.

## 3. Answers to the four questions

**(1) Same patient, same snapshot, different status:** H1 (run order + policy at re-tier), H2 (NAV vs any tier),
H3 (pool version), H4 (text shown), M1a-d, M2 (consent only on the cascade), M5 (run size). On one list and not
another: M2/M1b (`contact: deny` listed by NAV and v1, not by the cascade), M3 (console vs job), H2. Counted by FEAS
and not listed by SCREEN, or the reverse: M4.

**(2) Where each §7.4 invariant is enforced**
| Invariant | Enforcement points | One place? |
|---|---|---|
| Unknown never excludes | `evaluate.eligibility:464`, `structured_candidate:558`, `tier:621`; `SqlEngine` overrides `:129-140`; cascade `_s1_coded:500`, `_s1_outcome:476`, S2 `:660`, S2b `:748-763`, `_map:827`, `tiers:1004`; `verdicts_of`; `nav._ok`; FEAS `_pass:221`; COHORT `is True` | no: 6 |
| Proposed facts never count | `flatten` keeps them out of coded tables; `SqlEngine:136-140`; cascade `:476-491`; FEAS and COHORT rely on the first only | no: 3 |
| Units, impossible values | SQL generator + `safe_sql` (every runtime path); CQL generator (compile time); Python `derived` (NAV drafts, stored rows) | runtime yes; three implementations |
| Engines agree | `run_gate` at approval (`service.py:329`): SQL vs CQL, 200 site patients, one index date | one place, two of three engines |
| The pair | `pair.combine` via `judge_excerpts` (one place); "may it exclude": `evaluate_patients:683`, `screen_cascade.py:313` -> `_map:860`, `microbatch.py:218`; NAV and CASE: nowhere; S4 separately `engine.py:954` | answer yes; consequence no |
| Excerpts | v1 `judge_patient:322-341`; cascade `excerpt_set:589` + `_map:847-857`; CASE: nowhere | no: 2 + a gap |
| Opt-out | `drop_opted_out`, `opted_out_now` x3 (`screen.py`), `nav.py:113,217`, `case.py:199`, `microbatch.py:207`, cascade S0, `cohort.py:124`, console x5, `candidates.py:157`, `notmatched_sample.py:65`, `edc/service.py` x6, the worker; FEAS: nowhere | no: about 20 call sites, 3 rules |

**(3) Clinical arithmetic: what is compared**
- Compared: SQL vs CQL booleans per criterion at approval on the site's own sample (`gate.py:140-160`); five
  synthetic ALT cases for the UTC day boundary and censored values (`equivalence/edge.py`); Python vs SQL on
  published worked examples of the scores (`tests/unit/test_derived_scores.py`). In CI the CQL side is a fake
  `FhirEvaluator` (`test_equivalence_gate.py` docstring) or HAPI recordings when a JDK is present (`test_cql_eval.py`).
- Not compared: age (`date_sub('year')` vs `AgeInYearsAt` vs `derived.age_at`, `derived.py:337`) on 29 February
  births or on the birthday itself; the age used inside eGFR vs the age atom; window edges (index - N days, both
  ends) outside the ALT case; unit conversion across all three; impossible values across all three; derived scores
  in CQL; the day boundary for anything but one Observation time. The Python reference is in no gate. The gate
  samples real patients, so a boundary case is compared only if the site happens to hold one.

**(4) What the goldens and `test_safety_properties.py` exercise**
- Goldens: FEAS funnel; the v1 structured filter (`SqlEngine` + `structured_candidate`); lake tables. No cascade, no
  judge, no register, no consent, no tier, no pool, no delivery.
- `test_safety_properties.py`: `pair.combine` (pure); v1 `evaluate_patients`/`tier` with an answer engine; cascade
  S1 on a fake lake; SQL engine and cascade S1 on a small real lake for proposed facts and code gaps; S2 to S4 with
  `_Judge` (`:783-794`), which answers by role and criterion text and quotes the first excerpt whatever the text says.
- So no test can currently fail on: Excerpts (the judge's answer does not depend on what was cut); the pair across
  a stored pool row (H1); NAV's or CASE's use of a note answer (H2); opt-out or consent on FEAS/COHORT; the consent
  rule of S0 against the register's; any path-against-path difference (M1, H4); pool version (H3); age and window
  boundaries across engines; the cascade's index-date choice against FEAS's month-ends beyond one named funnel.

## 4. Architecture verdict

- **R1 (H1, H2, H3, M1): a verdict has no owner once it leaves the engine.** The status of a patient is recomputed
  by whoever holds the verdict list (three functions, plus the console), and the verdict contract does not carry
  what the rule needs (was it a pair, was it final, which version). Structural.
- **R2 (M2, M3, M4-opt-out, L1): each path gathers its own inputs.** Register, consent, policy and "today" are read
  by each scenario with its own call and its own rule; only the snapshot is handed over by `Ctx`. Structural; the
  snapshot pin shows the fix works.
- **R3 (H4, M5, L4): the text a model reads is chosen by the caller, not by the judge.** Two excerpt builders and
  CASE's none, with different meanings of "left out". Structural.
- **R4 (§3.3, §3.4): the tests follow the modules, not the paths.** Each engine is tested against its own fake;
  nothing runs one patient through every path. Structural in the test plan, an accident in each test.
- L2, L3, L5, L6 are accidents of implementation.

## 5. Proposed change (cards)

**AD-1 Decision context (M).** Goal: one object a path must build to read anything that decides.
`services/orchestrator/decision_context.py` (new), built once in `Ctx` next to `pinned_services`
(`jobs.py:150-170`): `lake` (the pin, as now), `register.at_receipt` / `register.now()` (one function, with
survivors), `consent` (one rule: `optout.registry_rule`, giving `refused` and `no_contact` as of the run date),
`ruleset` with its pins (prompt, terminology release, lexicon hash, derived-definition versions), `note_block`
(computed once per job), `threshold`, `run_date`, and a `fingerprint()`. Call sites that change: `screen.py:173-206,
511,637,678,756`; `nav.py:113-128,155,217`; `case.py:199-211`; `microbatch.py:207,218`; cascade S0 takes the consent
state from `CascadeConfig` instead of querying (`engine.py:365-381`); `cohort.py:124-152`; console pages use the same
register function (`home.py:339,1557`, `screening_log.py`); `review.py:32` uses the job's date. Acceptance: a lint
test in the style of `test_audit_one_writer.py` fails on `opted_out(`, `FROM consent`, `effective_note_block(` or
`.snapshot()` outside the module; the D-441 tests pass unchanged. Goldens: unchanged (they do not reach these
reads). Depends on: D-441 (merged). Absorbs: the "contact: deny on v1" and "FEAS/COHORT read the register" items of
D-441 "not done" (FG D-278, CR-026) as one more call site each; L1, L2.

**AD-2 One function from verdicts to status (M).** Goal: `matching/decision.py: status_of(rs, verdicts, policy) ->
Status(tier, actions, n_unknown, excluded_by)`, built on `matching/verdict.py`. `CriterionVerdict` gains what the
rule needs: `basis` (`coded | pair | single | human`), `final` (false when notes were left out or the answer was
soft) and the ruleset version at row level. Moves: `evaluate.tier:621-663`, `engine._Run.tiers:1004-1028`, the tier
half of `verdicts_of:187-198`, `nav._ok:60-66`; `evaluate.eligibility`/`structured_verdict` and `engine._s1_coded`
call `verdict.structured` instead of being parity-tested against it; CASE prints `Status` per criterion. Acceptance:
the three throwaway cases of H1, H2, H3 as permanent tests; `test_verdict_table.py` parity tests become direct
tests. Goldens: unchanged (they hash `PatientEvaluation`, not verdict rows); `candidate_list` contract gains fields
(contracts job). Depends on: nothing. Changes: T-652 (completes "one decision table shared by the engines"), T-216
(FEAS's unknown rule becomes a `policy` of the same function instead of a second SQL rule).

**AD-3 Pool rows are bound to their version and basis (S).** `microbatch.py:161,243`: a row whose `version` differs
from `rs.version` is not re-tiered; it is re-screened as a new patient (within the night budget) or shown as
"awaiting re-screen". A non-final verdict is never upgraded by a re-tier. Acceptance: amendment test (v1 pool, v2
approved, MICROBATCH lists nobody as `high` on unevaluated criteria). Depends on AD-2 for the fields; can land first
with the version check alone. Changes: T-624 (its e2e case gains the amendment step).

**AD-4 One excerpt builder (M).** `matching/excerpts.py: excerpt_set(window_notes, evidence, budget) -> (shown,
left_out)` where `left_out` counts every window note not shown in full; used by the cascade, `NoteJudge._chunks/
_record` and `ChartJudge`; budget from `NoteJudge.budget` (`evaluate.py:252`). Acceptance: AD-6. Goldens: unchanged.
Depends on: PR #275 (lands first; this card moves its rule to v1 and CASE). Changes: T-203b (the vector store is a
ranking input of the builder, not a second builder), T-696 (the budget and the pinned embedder land here once),
T-694 (batches call the builder per patient and drop the text).

**AD-5 Path-independence test (M).** `tests/property/test_path_independence.py`: one small `LakeLocal` world (the
`prop_world` fixture), one pair of text-reading scripted models (`tests/judge_kit.py: quoting`), then SCREEN v1,
SCREEN cascade, MICROBATCH new, MICROBATCH re-check, NAV, CASE with a chart number, FEAS and COHORT membership, and
the console's list. Asserts: per criterion the same verdict; per patient the same status; an opted-out or refused
pid in no published bytes of any path (scan every `Ctx.publish`); the differences that are decisions (FEAS at
month-ends, FEAS's unknown rule until T-216) are a named table in the test, each with its decision number. Staging:
lands first with today's differences listed as expected-failures by finding id, so master stays green and the table
only shrinks. Depends on: nothing. Changes: T-207 / PR #262 (its acceptance test: with the flag on, every path
reads stored scores, with it off none), plan §7.5 (`property` job).

**AD-6 Judge-in-the-loop property test (M).** `tests/property/test_judge_in_loop.py`: an oracle pair whose answer
is a function of the text it is shown. Properties over generated charts and budgets: cutting never turns kept or
unknown into excluded (compare against the oracle on the full window); removing a note never excludes; a failed,
missing or same-build verifier never excludes; a single model never excludes on any path including a later re-tier.
Run over both pipelines, NAV and CASE. Would fail today on H1, H2, H4. Depends on: nothing; AD-4 turns it green.
Changes: T-689 (replayed pairs must give the same statuses: one more property), T-694 (batch size 1, 100, 1000 give
the same statuses: closes M5).

**AD-7 Three-engine boundary table (S-M).** Extend `equivalence/edge.py` from 5 ALT cases to a generated table:
29 February births, index on the birthday and the day before, both window ends, 23:30Z and 00:30 local, each unit
conversion, each impossible value, each score. Run through `tb_common.derived`, the generated SQL on DuckDB and CQL
(`tools/cql_eval` with a JDK, else the recordings). This is the `differential` job of plan §7.5. Depends on: FG D-275
for the age rule. Goldens: unchanged.

**Order that keeps master green:** AD-5 and AD-6 first (expected-failure tables) -> AD-3 version check -> AD-1 as a
pure move (same values, lint on) -> AD-1 consent rule (behaviour change, own decision) -> AD-2 -> AD-4 after PR #275
-> AD-7. PR #262 and PR #275 should not merge before AD-5/AD-6 exist, or each adds one more per-path difference.

## 6. Not read

`services/criteria_compiler/service.py`, `review.py`, `semantics.py`, `unit_check.py`, the CQL templates and
`compile_sql/generator.py` beyond the age and base lines; `libs/tb_common/derived.py` beyond its header and
`age_at`; `derived_store.py`, `flags.py`, `labunit.py`; `matching/coverage.py`, `proposed.py`, `coded_values.py`,
`cascade/judge.py`, `s2b_semantic.py`, `certificate.py` (only their call sites); `twpas.py` beyond its lake call;
`scenarios/consent.py`, `trials.py`, `feas_profile.py`; the EDC and mail write paths; `lake/client.py` and
`store.py`; console pages beyond the opt-out and deceased filters; the integration tests; PR #262 and PR #275
beyond the file list of their local branches (which may be stale). L5's "not reachable" rests on runtime criteria
having no `ir_version`; I did not read the compiler's output to confirm it for every ruleset.
