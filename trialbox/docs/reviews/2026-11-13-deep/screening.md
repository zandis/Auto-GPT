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
| Tiers change by one or two patients between runs | the models' answers are not bit-stable under batching at temperature 0, and the tier is a hard cut on a model-stated confidence (SCR-08) | finding; mitigations listed |
| Guided decoding: 1 of 64 answers with other field names | see SCR-09 | finding |

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
| SCR-17 | Low | Date and language small items (see §2.17) | run (sub-reviewer) | no | E |

### SCR-01 Critical: VS_MALIGNANCY misses malignant codes

- **Symptom.** A patient with Merkel cell carcinoma (C4A.x) or a squamous or basal cell skin carcinoma (C44.x) is
  not excluded by "Malignancy within the past 5 years" (RA-JAK-EXC-08) or the RA-BIO malignancy exclusion.
- **Evidence.** `rulesets/{GZQO,RA-JAK,RA-BIO}/valuesets/VS_MALIGNANCY.json`: the listed three-character groups run
  C00 to C96 without C44 and C4A; the family extensions are `C0`, `C1`, `C2`, `C3`, `C40`, `C41`, `C43`, `C45` to
  `C49`, `C5` to `C9` (grouper in `services/criteria_compiler/terminology/.../synonyms.csv`). A code outside list
  and families is a plain non-match, so the SQL says FALSE, not unknown (`compile_sql/generator.py:240-247`).
  Z85 (personal history of malignancy) and D45, D46, D47.1 (malignant by behaviour) are absent too.
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
- **Fix (this branch).** The test the chart names decides the analyte and the stored LOINC. A known serum code on a
  line that does not name that test is dropped (the fact stays, uncoded, for a person to map). A urine test is never
  read as the serum test. A code of another system is not kept on a lab fact. Test:
  `tests/unit/test_chart_fact_codes.py` (13 of 21 cases failed before the first fix; the second round's cases
  failed on the first fix).

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
- **For the owner (D-TBD-1).** Two parts, each changes who is excluded:
  1. Keep a partial date as an interval (year or month). Decide a window when the whole interval is inside or outside
     it; "2019" is outside "within 5 years" of 2026-09 and inside "ever".
  2. For a criterion with no lower bound, count an undated record as inside when the index date is the snapshot's
     day (a record on file is before today). Not when the index date is in the past (FEAS month ends).
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
  remaining calls after a hard fail). No `seed` is sent (`grep seed libs/tb_llm libs/tb_common/llm.py`: none); at
  temperature 0 vLLM is still not bit-stable when the batch differs. The per-run answer cache keys on the patient,
  so it does not race (read, `engine.py:868-873`).
- **Root cause.** Inferred: batch-dependent numerics in the servers, amplified by a hard threshold on a
  self-reported number. Not provable here without a GPU.
- **Fix.** (a) Lane G: run the same setting twice with a server restart between (lane G's B5) and keep each
  flipped patient's two answers and confidences, so the cause is shown, not inferred; (b) lane D: serve with the
  server's batch-invariant mode if the pinned build has it, and measure its cost; (c) lane A2: store the per-patient
  answers of a run beside the list, and compare the next night against them, so a flip is a named event; (d) the
  owner may prefer a band (for example 0.7 to 0.8 is always *review*): a decision, D-TBD-2.

### SCR-09 Medium: guided decoding let one answer through with other field names

See §3 (the judge path sub-review). Lane G P3: `finish_reason` stop, 71 tokens, keys `verdict`, `reason`; backend
`auto`. Whatever the parser does with it, it must end as unknown; §3 says what it does.

### SCR-10 Medium: a budget stop depends on thread timing

`engine.py` `s3.one`: each worker reserves budget under the lock as it reaches a call. With
`TB_SCREEN_LLM_CONCURRENCY` above 1 and a budget that binds, which patients end "unprocessed (budget)" depends on
thread order, so two runs list different patients for review. Safe (never an exclusion), but not repeatable.
`test_cascade_pipeline.py` checks equality across concurrency only without a budget. Fix: reserve in patient order
before dispatch (each patient's first call), or make the last batch sequential. By reading.

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

## 3. Judge and verifier path

(merged from the judge-path sub-review; see the note at the end of this section)

## 4. What is good and should stay

- The fail-closed rules: an undated diagnosis, an off-list family code, an unknown code system, a proposed or
  suspected fact, a budget stop, a refusal and a clipped note all end as unknown; a single model never excludes
  (D-97); the engine's own "review" overrides a computed "high".
- One status function for every path (`matching.decision.status_of`, D-478).
- The excerpt rewrite in #419 (D-641) removes the stitched-note exclusion lane G saw on real models (P1).
- `quotes.quote_key`, era boundary checks, ROC two-digit years only for zh-TW, the slashed-date question, and
  `labvalue`'s refusal to convert silently.
- The LOINCs in use are correct: 3084-1, 2160-0, 4548-4, 2345-7, 29463-7, 98979-8, 62238-1, 33914-3, 50210-4.

## 5. Needless weight

| Duplicate | Where | Keep |
| --- | --- | --- |
| Five date readers | `messy.parse_date`, `dates.parse`, `dates.find`, `refdata_tw.roc`, span regexes | `dates` with a language |
| Two lab-number readers | `messy.parse_number`, `labvalue.parse` | `labvalue` |
| Three unit converters | `messy.ANALYTES` (88.42, 2 decimals), `labunit`/`derived.UNITS` (88.4, 6), `labvalue.MOLAR` | `labunit` |
| Two plausible-range tables | `messy.ANALYTES`, `labvalue.PLAUSIBLE` | one |
| Two negation lists, none in production chart reading | `llm_stub._NEG`, `polarity._CJK_NEGATED` | one, used by `normalise` |
| Two sex maps | `messy._SEX`, inline in `charts.normalise` | `messy._SEX` |

## 6. Decisions for the owner

| Id | Question | Recommendation |
| --- | --- | --- |
| D-TBD-1 | Partial dates and undated records against a criterion with no lower bound (SCR-05) | yes to both parts, with the adversarial review the card needs |
| D-TBD-2 | A confidence band that is always *review*, so a small change in a model's number does not move a patient's tier (SCR-08) | measure first (lane G's repeat runs), then decide |
| — | Re-approval of GZQO, RA-JAK and RA-BIO after the VS_MALIGNANCY fix (SCR-01) and of every ruleset after SCR-03 | yes |

## 7. Not done

No GPU, so nothing about the real models' answers is shown here, only read from lane G's records. The PHI tripwire
and the canary were in the judge sub-review's scope (§3). `tests/integration/test_e2e_simple.py` was run (§8).

## 8. Runs

| Run | Result |
| --- | --- |
| `tests/unit/test_chart_fact_codes.py` | before the fix 13 failed; after it all pass |
| `tests/unit/test_undated_lab_values.py` | 1 passed, 1 expected failure (SCR-03) |
