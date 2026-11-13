# Deep review of 2026-11-13: screening and clinical correctness

| Field | Value |
| --- | --- |
| Area | Who is excluded and who is listed: criteria, coded screening, the cascade, judge and verifier, chart facts, code maps, languages, determinism |
| Tree | `master` at `c7dcd5e7`; branch `claude/deep-review-screening` |
| Method | Code read and run on a 4-core machine with no GPU and no Docker. Two sub-reviewers (judge path; languages and code maps), one adversarial reviewer on the fixes. Lane G's results of 2026-11-13 (PR #461, `g3-2026-11-13`, `g7-2026-11-13`) read as evidence. |
| Data | Synthetic only. No secret read. |

Terms used here:

- **Wrong exclusion**: a patient who meets the trial is left off the list. **Wrong inclusion**: a patient who should
  be excluded is listed.
- **Fail closed**: when the data cannot decide, the answer is *unknown* and a person looks ("needs information" or
  tier *review*). This is the product's safe state.
- **Verified**: shown by a command or a test on this tree. **Inferred**: by reading only.
- **Proposed fact**: a fact read from a chart by the model, waiting for a coordinator's Confirm.

## 1. Summary

The fail-closed design holds where it was built: undated diagnoses, unknown code systems, off-list family codes,
budget stops, refusals, a single model and clipped notes all end as *unknown*. The defects found are at the
edges of that design: data that reaches the lake **coded wrongly**, or **dated wrongly**, or a **value set that is
too narrow**. Then the SQL gives a decided answer that is wrong, and nothing flags it.

The three items lane G asked about:

| Item | Root cause | State |
| --- | --- | --- |
| Stage 12 fails (wrong LOINC for urate) | `charts.normalise` kept the model's LOINC over the analyte the chart names (SCR-02) | **fixed** here, with tests |
| Stage 12 fails (undated malignancy) | the prompt asks for a full date; "乳癌（2019年手術）" has a year only, and an undated row never meets "any history" because a criterion with no window still compiles to `d <= index` (SCR-05) | owner's decision (D-TBD-1) |
| Tiers change by one or two patients between runs | three sources in the code, one in the servers: a failed context lookup shrinks the excerpt budget for the run (SCR-18, part fixed); budget stops follow thread timing (SCR-10, run); S4 asks the verifier again (SCR-21); answers at temperature 0 are not bit-stable under batching and the tier is a hard cut on the model's own confidence (SCR-08) | part fixed; rest for lanes A2, B2, D |
| Guided decoding: 1 of 64 answers with other field names | the schema is sent strict on every judge call; the likely cause is an answer cut at `max_tokens` and retried, or a tool's own "judge" schema; either way it ends as unknown (SCR-09) | finding; the audit should keep `finish_reason` |

## 2. Findings

Severity: **Critical** = a wrong exclusion or inclusion of a patient; **High**; **Medium**; **Low**.

| Id | Sev. | Finding | Verified | Fixed here | Owner lane |
| --- | --- | --- | --- | --- | --- |
| SCR-01 | Critical | VS_MALIGNANCY misses C4A (Merkel cell carcinoma) and C44, outside both list and families: a silent FALSE | run | no (approved rulesets) | E, then A2 for re-approval |
| SCR-02 | Critical | A chart's lab fact kept the model's LOINC: urate stored as creatinine, BUN as creatinine, urine as serum | run | **yes** | E |
| SCR-03 | Critical | An undated lab result falls out of every window test: a dated normal value decides alone | run (strict xfail test) | no (both generators) | A2 with E |
| SCR-04 | High | Chart facts: a negated, family or suspected mention becomes the patient's own proposed diagnosis | run (by the sub-reviewer) | no (schema and prompt) | A2 |
| SCR-05 | High | A year-only date is lost; an undated confirmed history never meets "any history of" | run | no (owner) | owner, then A2 |
| SCR-06 | High | The chart prompt asks for the visit date, not the condition's date | read | no (prompt) | A2 |
| SCR-07 | High | The stub chart reader dates facts from the section above, which D-470 forbids: stage 12 passes on the stub only | read + run | no | A2 |
| SCR-08 | High | Tiers are not stable across runs: hard cut at 0.75 on the model's own confidence | read + lane G's evidence | no | A2, D (serving) |
| SCR-09 | Medium | Guided decoding: one answer outside the schema | see §3 | no | D |
| SCR-10 | Medium | Which patients a budget stop leaves unprocessed depends on thread timing | read | no | B2 |
| SCR-11 | High | Sheet lab cells with a flag ("8.8 H") or a censored value ("<2.0") are dropped without a check | run (sub-reviewer) | no | E |
| SCR-12 | High | The sheet path has no specimen guard: "尿中尿酸" is read as serum urate | run (sub-reviewer) | no | E |
| SCR-13 | Medium | Converted values are rounded to 2 decimals before comparison (7.004 stored as 7) | run (sub-reviewer) | no | E |
| SCR-14 | Medium | Value sets of HbA1c and urate hold one LOINC each (17856-6, 59261-8, 14933-6 read as absent) | read | no | E |
| SCR-15 | Medium | Taiwan ICD codes are kept as written: lower case or dotless codes miss the list | read | no | E |
| SCR-16 | Low | Terminology maps "uric acid" but not "urate" (no mapping found) | run | no | E |
| SCR-17 | Low | Date and language small items | run (sub-reviewer) | no | E |
| SCR-18 | High | One failed `GET /v1/models` keeps "context unknown" for 300 s; the cascade then freezes the 2,500-token default for each criterion for the whole run | run | **part** (`tb_common.llm`) | A2 (`engine.budget_of`, in open PRs) |
| SCR-19 | High | `AgreementJudge` never checks the verifier's quote; with `run_cascade`'s default `note_block=True` a hallucinated verifier "fail" confirms an exclusion (tools only, not SCREEN) | run (verifier half) | no (`judge.py` in #419) | A2 |
| SCR-20 | High | `CascadeConfig.note_block` defaults to True: a direct caller with one model excludes on it (tools, scale gate) | read + existing test | no (`engine.py` in open PRs) | A2 |
| SCR-21 | Medium | S4 asks the verifier the question S3's pair already put to it: a second sample that differs turns "strong" into "S3/S4 disagree" | read | no | A2 |
| SCR-22 | Medium | Two judge parsers: SCREEN accepts fenced JSON and a repair turn, `GatewayJudge` calls it `schema_invalid`; tools and e2e do not measure production | run (sub-reviewer) | no | A2 |
| SCR-23 | Medium | A PHI-tripwire refusal or `schema_invalid` reads as "abstained" on the cascade (`engine.py:917`) | read | no | A2 |
| SCR-24 | Medium | `decision.answer_of` lets a "fail" with no `basis` exclude (`decision.py:110`): a new path that forgets the basis gets single-model exclusions | read | no | A2 |

### SCR-01 Critical: VS_MALIGNANCY misses malignant codes

- **Symptom.** A patient with Merkel cell carcinoma (C4A.x) or a squamous or basal cell skin carcinoma (C44.x) is
  not excluded by "Malignancy within the past 5 years" (RA-JAK-EXC-08) or the RA-BIO malignancy exclusion.
- **Evidence.** `rulesets/{GZQO,RA-JAK,RA-BIO}/valuesets/VS_MALIGNANCY.json`: the listed three-character groups run
  C00 to C96 without C44 and C4A; the family extensions are `C0`, `C1`, `C2`, `C3`, `C40`, `C41`, `C43`, `C45` to
  `C49`, `C5` to `C9` (grouper in `services/criteria_compiler/terminology/.../synonyms.csv`). A code outside list
  and families is a plain non-match, so the SQL says FALSE, not unknown (`compile_sql/generator.py:240-247`).
  Z85 (personal history of malignancy) and D45, D46, D47.1 (malignant by behaviour) are absent too.
- **Run.** The adversarial reviewer ran the shipped rulesets on a small lake (onset 2025-06-01, index 2026-11-09):
  RA-JAK-EXC-08, RA-BIO-EXC-04 and GZQO-EXC-07 give FALSE for a C44 or C4A patient and TRUE for C43; an undated C44
  is FALSE too, as the undated check uses the same list. For GZQO ("except non-melanoma skin cancer") leaving C44 out
  is right; C4A is debatable there. For RA-JAK and RA-BIO it is a wrong inclusion.
- **Root cause.** One shared grouper drops C44 for GZQO's "except non-melanoma skin cancer", and C4A was never
  added. The exception belongs to one criterion, not to the value set.
- **Fix.** Add a family `C4A` and `C44` to the grouper; express "except non-melanoma skin cancer" as a per-criterion
  exclusion; treat Z85 and D45 to D47 as off-list family members (unknown, not FALSE). Re-compile and re-approve the
  three rulesets.

### SCR-02 Critical (fixed): a chart's lab fact was stored under the model's LOINC

- **Symptom.** Lane G P5: stage 12's urate came back with another LOINC, so "urate at least 7.0 in the last year"
  did not see it. Worse cases, run here on master: term 尿酸 with code 2160-0 was stored as creatinine 8.1 mg/dL;
  クレアチニン 80 µmol/L with code 3084-1 was divided by the urate factor and stored as urate 1.34; "BUN 18" with
  2160-0 was stored as creatinine 18. Once a coordinator taps Confirm, a renal exclusion reads it.
- **Root cause.** `services/sitesetup/charts.py` `normalise`: `analyte = LOINC_ANALYTE.get(code) or analyte_of(term)`
  and the code was replaced only when empty. The prompt itself says the code is given "when you are sure".
- **Fix (this branch).** A LOINC of one of the five tests TrialBox stores (urate, creatinine, HbA1c, glucose,
  weight), or of the same test in another unit (urate's 14933-6, creatinine's 14682-9, HbA1c's IFCC 59261-8,
  glucose's 14749-6 and 15074-8), is kept only on a line whose term names that test, and is then stored as the
  test's own code in the unit it is converted to. On any other line it is dropped and the fact stays uncoded, for a
  person to map. Any other LOINC the model gave is kept as given (fasting glucose, urine creatinine, pleural
  glucose, an OGTT value). A term that names another specimen or another quantity (尿 but not 尿酸, a urinalysis
  line "UA-PRO", pleural fluid, CSF, 体重変化, 出生体重, a ratio) never gets a serum code. A code of another system is
  not kept on a lab fact. A made-up code is kept as given: it matches no shipped value set, so the patient stays
  "needs information".
- **Review.** The first version of this fix was broken by the adversarial reviewer: it re-coded urine creatinine
  as serum creatinine (an eGFR near 0 after Confirm), "UA-PRO 30" as urate 30, and fasting, OGTT and pleural glucose
  as plain glucose. Those cases are tests now. Test file `tests/unit/test_chart_fact_codes.py`: 33 of 49 cases fail
  on master, all pass on the branch.
- **Not fixed (same family).** The sheet path has the same specimen gap (SCR-12). A lab fact whose term names an
  analyte but has a missing or unknown unit is dropped, not kept for a person (unchanged).

### SCR-03 Critical: an undated lab result falls out of the window test

- **Symptom.** A dated HbA1c of 6.1 % and an undated 11.2 % read as "clear" on "HbA1c above 10 %"; a dated urate of
  6.5 and an undated 8.8 read as "not met" on "the latest urate at least 7.0". The first is a wrong inclusion, the
  second a wrong exclusion.
- **Evidence.** `tests/unit/test_undated_lab_values.py` (strict expected failure). `compile_sql/generator.py`
  `_obs_source` joins on `in_window('o.effective::DATE', w)` and has no undated branch (the presence atom has one,
  lines 223-247, DUMP-01). The CQL generator (`compile_cql/generator.py` `_obs_value`) does the same, so the
  equivalence gate agrees with the wrong answer. Derived values (`_latest_component`, eGFR) share it.
- **Where undated values come from.** A chart line with no date (D-470 keeps it undated), a sheet row without a day,
  an old system's import.
- **Fix.** As DUMP-01 for presence: an undated row that would change the answer makes it unknown; for `latest`, the
  answer stands only when every undated row gives the same answer. Both generators, then re-compile the approved
  rulesets. The test turns green and its marker is removed.

### SCR-04 High: chart facts have no guard for negation, family history or suspicion

- **Symptom.** Quotes "悪性腫瘍なし", "家族歴：母 乳癌" and "肺癌の疑い" each give an ordinary proposed condition
  (C80.1, C50.9, C34.9). One Confirm tap excludes the patient. A suspected diagnosis from a chart does not get the
  `suspected` basis that SS-MIX2 and FHIR records get (D-142).
- **Root cause.** The only deterministic negation list is in the stub (`llm_stub/handlers.py` `_NEG`). Production
  relies on the prompt; the `chart_facts` schema has no field for negated, subject or certainty.
- **Fix.** Add `negated`, `subject` and `certainty` to the schema and prompt (a new version, qualified on the pair,
  D-359); in `normalise`, drop a negated or family fact and give a suspected one the basis `suspected`. Show the
  marker beside the quote on the review list. A quote-level word check alone is too crude: "乳癌（2019年）、母：糖尿病"
  holds 母 and the patient's own cancer.

### SCR-05 High: a year-only date is lost, and an undated history never settles (lane G P5)

- **Symptom.** All six hospital parts of lane G: 10000005's confirmed "乳癌（2019年手術）" is undated and the patient
  stays "needs" against "Any history of malignancy".
- **Evidence.** `messy.parse_date` and `dates.parse` return nothing for "2019年", "2019年3月", "民國108年",
  "令和元年" (run). `semantics.window` gives `Window(None, 0)` to a criterion with no window, and `in_window`
  compiles it to `d <= index` (`compile_sql/generator.py:92-96`), which NULL never meets.
- **Safe today.** The adversarial reviewer confirmed the result is always "needs information", never a wrong
  answer (run: undated-only gives NULL; dated plus undated gives TRUE on "any").
- **For the owner (D-TBD-1).** Two parts, each changes who is excluded:
  1. Keep a partial date as an interval (year or month). Decide a window when the whole interval is inside or outside
     it; "2019" is outside "within 5 years" of 2026-09 and inside "ever".
  2. Count an undated record as inside only for `any` and `none`, anchor `index`, `to_days >= 0`, no lower bound,
     and an index date equal to the snapshot's day; SQL and CQL alike. The reviewer's counterexamples to a wider
     rule: with `count>=` an undated copy of a dated diagnosis is counted twice (a wrong inclusion); `to_days < 0` or
     an event anchor cannot place an undated record; an index date before the snapshot would count later records.
  Until he rules, the coordinator can give the date with Correct, and the stage-12 check cannot pass on a model that
  follows the prompt (SCR-07).

### SCR-06 High: the chart prompt asks for the wrong date for past history

`libs/tb_llm/prompts/chart_facts_v2.md`: `date` is "the day of the visit, test or prescription". A model that obeys
dates "乳癌（2019年手術）" to the visit day, 2026-09-25: inside "malignancy within 5 years", a wrong exclusion after
Confirm. `tests/unit/test_g1_b1_chart_fact_dates.py` already names this harm for the section heading. Fix: ask for
the date of the fact itself (onset, diagnosis, operation, result) and a partial date as written; a new prompt
version, qualified (inferred by reading; not run on a real model here).

### SCR-07 High: the stub chart reader does what D-470 forbids

`services/llm_stub/handlers.py` `chart_facts` dates every fact "of the line or of the last dated line above it".
D-470 rejected exactly that. So stage 12 passes on the stub and fails on every real model that follows the prompt:
the CI gate tests a behaviour the product forbids. Fix: the stub dates a fact only from its own line (as
`LiteralReader` in `test_g1_b1_chart_fact_dates.py` does), and stage 12's scripted coordinator gives 10000005's
cancer its date with Correct, or the check expects "needs" until D-TBD-1 is ruled.

### SCR-08 High: the tier is not stable across runs

- **Symptom.** Lane G P4: six runs, same 55 patients listed, one or two change between *high* and *review*; three
  list hashes; call counts 243 to 246 per run.
- **Evidence.** The tier is `decision.status_of` (`services/matching/decision.py:94-146`): a note answer counts as
  "yes" only when the model's own `confidence >= 0.75` (`screen_cascade.DEFAULT_POLICY`). A flip between 0.7 and 0.8
  moves a patient between tiers. The varying call counts follow from varying answers (CAS-3 stops a patient's
  remaining calls after a hard fail). The gateway forces temperature 0, `top_p` 1 and a fixed seed
  (`models/routing.yaml:17`); vLLM is still not bit-stable when the batch differs. The per-run answer cache keys on
  the patient, so it does not race (read, `engine.py:868-873`).
- **Root cause.** Four sources, in order of what the code can settle: SCR-18 (a run sized on the small default
  after one failed lookup gives other excerpts and other `left_out` counts), SCR-10 (only with a budget set),
  SCR-21 (a second verifier sample), and batch-dependent numerics in the servers amplified by a hard threshold on a
  self-reported number. Which one moved lane G's two patients is not shown: the run kept the list, not the
  answers.
- **Fix.** (a) Lane G: run the same setting twice with a server restart between (lane G's B5) and keep each
  flipped patient's two answers and confidences, so the cause is shown, not inferred; (b) lane D: serve with the
  server's batch-invariant mode if the pinned build has it, and measure its cost; (c) lane A2: store the per-patient
  answers of a run beside the list, and compare the next night against them, so a flip is a named event; (d) the
  owner may prefer a band (for example 0.7 to 0.8 is always *review*): a decision, D-TBD-2.

### SCR-09 Medium: guided decoding let one answer through with other field names

Lane G P3: `finish_reason` stop, 71 tokens, keys `verdict`, `reason`; backend `auto`. The product sends the schema
strict on every judge call (`judge.py:133`, `client.py:135`; `additionalProperties: false`, five fields required;
the gateway refuses a schema whose sha is not the registry's, `gateway/core.py:567-576`). So on that call the
server did not apply it. Two code paths give "other field names" without a server fault: an answer cut at
`max_tokens` and retried once (`client.py:299-312`, `llm.py:438-447`; `test_judge_answer_cut_twice.py` traces lane G's
earlier 1 of 64 to this), and the tools that send their own schema under the same name "judge"
(`tools/bakeoff_live.py:205`, `tools/bakeoff.py:195`, `tools/mlbench.py:211` with no schema). The probe's
`finish_reason` stop rules out the first for this answer. Safe either way: both parsers turn unknown keys into
unknown, never met or not met (run). Fix (lane D): keep `finish_reason` and the schema error codes in the gateway's
call audit (today only `schema_valid`, `core.py:737`), name the structured-output backend, and give the tools'
schemas their own names.

### SCR-10 Medium: a budget stop depends on thread timing

`engine.py` `s3.one`: each worker reserves budget under the lock as it reaches a call. With
`TB_SCREEN_LLM_CONCURRENCY` above 1 and a budget that binds, which patients end "unprocessed (budget)" depends on
thread order, so two runs list different patients for review. Safe (never an exclusion), but not repeatable.
`test_cascade_pipeline.py` checks equality across concurrency only without a budget. Fix: reserve in patient order
before dispatch (each patient's first call), or make the last batch sequential. By reading.

### SCR-18 High (part fixed): one failed lookup sizes a whole run's excerpts

`tb_llm.GatewayClient.contexts()` returns `{}` when `GET /v1/models` fails (`client.py:179`); `LlmClient.context_tokens`
kept that "unknown" for 300 s; `engine.budget_of` (`engine.py:625-632`) keeps the 2,500-token default for each
criterion for the rest of the run. With a context of about 30,000 tokens that is a different excerpt set, different
`left_out` counts, and so different tiers. Fixed here: `tb_common.llm` keeps only a known context
(`tests/unit/test_context_unknown_not_kept.py`, failed before). Left for lane A2 (`engine.py` is in nine open PRs):
`budget_of` should not keep the default, and a run that cannot tell its context should say so in its record.

### SCR-19 to SCR-24 (judge path)

The production SCREEN path (`NoteJudge` and `tb_common.pair.combine`) turns a disagreement, a missing verifier, the
same model twice, a verifier quote not found, a refusal, a timeout and an outage into unknown (77 existing tests run
by the sub-reviewer). The defects are in the cascade's own judges, used by tools, the scale gate and tests: they do
not measure what production does (SCR-22), and two of them can exclude where production would not (SCR-19, SCR-20).
The canary only decides whether a note answer may exclude; a failing canary publishes with note exclusions off and
says why (`canary_gate.py:96-121`). The PHI tripwire runs on D0 to D2 calls only, so SCREEN's D3 judge calls are not
screened (`gateway/core.py:493-498`): by design, recorded here so nobody assumes otherwise.

### SCR-11 to SCR-17

| Id | Evidence | Fix |
| --- | --- | --- |
| SCR-11 | `messy.parse_number` rejects "8.8 H", "９．１Ｈ", "<2.0"; `_lab_cell` returns early (`messy.py:574`) with no check; `labvalue.parse` reads them | use `labvalue.parse`; carry the comparator |
| SCR-12 | `messy.analyte_of("尿中尿酸(mg/dL)")` gives `urate`; `intake.py:165-172` sets `term` to the analyte name | specimen guard in `analyte_of`; keep the header as `term` |
| SCR-13 | `messy.convert` rounds to 2 decimals (`messy.py:265`); 416.6 µmol/L becomes 7, failing "> 7.0"; 88.42 here, 88.4 in `derived.UNITS` | one converter (`labunit`), 6 decimals |
| SCR-14 | VS of HbA1c: 4548-4 only; urate: 3084-1 only | add 17856-6, 59261-8 (with its unit rule), 14933-6 with conversion |
| SCR-15 | `adapter/mapping/engine.py:991` keeps a code as written | upper-case and dot ICD-10-CM at ingest |
| SCR-16 | `Terminology().map("observation", "urate")`: no mapping found; "uric acid" maps | add the synonym |
| SCR-17 | `dates.find` lacks 昭和/S; `find("BP 120.5.3")` gives 2031-05-03; ROC years to 199 accepted with no future check; `parse_date` takes no language; `polarity._CJK_NEGATED` flags 未満, 非小細胞肺癌 (noise only); `\bUA\b` can mean urinalysis | small cards |

## 3. What is good and should stay

- The fail-closed rules: an undated diagnosis, an off-list family code, an unknown code system, a proposed or
  suspected fact, a budget stop, a refusal and a clipped note all end as unknown; a single model never excludes
  (D-97); the engine's own "review" overrides a computed "high".
- One status function for every path (`matching.decision.status_of`, D-478).
- The excerpt rewrite in #419 (D-641) removes the stitched-note exclusion lane G saw on real models (P1).
- `quotes.quote_key`, era boundary checks, ROC two-digit years only for zh-TW, the slashed-date question, and
  `labvalue`'s refusal to convert silently.
- The strict judge schema bound to the registry sha at the gateway; a cut-twice answer is unknown; same-model
  detection (`pair.same_model`); the canary gate closed by default outside DEV and TEST.
- The LOINCs in use are correct: 3084-1, 2160-0, 4548-4, 2345-7, 29463-7, 98979-8, 62238-1, 33914-3, 50210-4.

## 4. Needless weight

| Duplicate | Where | Keep |
| --- | --- | --- |
| Five date readers | `messy.parse_date`, `dates.parse`, `dates.find`, `refdata_tw.roc`, span regexes | `dates` with a language |
| Two lab-number readers | `messy.parse_number`, `labvalue.parse` | `labvalue` |
| Three unit converters | `messy.ANALYTES` (88.42, 2 decimals), `labunit`/`derived.UNITS` (88.4, 6), `labvalue.MOLAR` | `labunit` |
| Two plausible-range tables | `messy.ANALYTES`, `labvalue.PLAUSIBLE` | one |
| Two negation lists, none in production chart reading | `llm_stub._NEG`, `polarity._CJK_NEGATED` | one, used by `normalise` |
| Two sex maps | `messy._SEX`, inline in `charts.normalise` | `messy._SEX` |
| Two judge parsers | `matching.cascade.judge`, `tb_common.llm` | `tb_common.llm` |
| Three judges with their own pair rules | `GatewayJudge`, `AgreementJudge` (tools and tests only), `NoteJudge` | `NoteJudge` |
| S4's second verifier question | `screen_cascade.py:100-102` | reuse S3's answer |
| Three schemas named "judge" | `tools/bakeoff*.py`, `tools/mlbench.py` | distinct names |

## 5. Decisions for the owner

| Id | Question | Recommendation |
| --- | --- | --- |
| D-TBD-1 | Partial dates and undated records against a criterion with no lower bound (SCR-05) | yes to both parts, with the adversarial review the card needs |
| D-TBD-2 | A confidence band that is always *review*, so a small change in a model's number does not move a patient's tier (SCR-08) | measure first (lane G's repeat runs), then decide |
| — | Re-approval of GZQO, RA-JAK and RA-BIO after the VS_MALIGNANCY fix (SCR-01) and of every ruleset after SCR-03 | yes |

## 6. Not done

No GPU, so nothing about the real models' answers is shown here, only read from lane G's records.
`tests/integration/test_e2e_simple.py` could not pass here: the FEAS compile needs the CQL translator, and
`make jvm-deps` cannot resolve its jars from Maven Central through this machine's proxy (slf4j 2.0.13, jackson
2.21.8 "not found"). The 35 unit test files that import the site set-up (766 tests) and the cross-card list (229)
pass. For lane G: on the next GPU run, keep each listed patient's answers and confidences, run one setting twice
with a server restart between, and record whether any `GET /v1/models` failed.

## 7. Runs

| Run | Result |
| --- | --- |
| `tests/unit/test_chart_fact_codes.py` | before the fix 13 failed; after it all pass |
| `tests/unit/test_undated_lab_values.py` | 1 passed, 1 expected failure (SCR-03) |
| `tests/unit/test_context_unknown_not_kept.py` | before the fix 1 failed; after it both pass |
| 35 unit files importing `sitesetup` | 766 passed, 3 skipped |
| `make cross-card` | 229 passed |
| ruff, ruff format, mypy (touched files), doclint, decisions index, data scan, `security_scan sast` | clean |
| `tests/integration/test_e2e_simple.py` | not passed here: CQL translator jars unavailable (§6) |
