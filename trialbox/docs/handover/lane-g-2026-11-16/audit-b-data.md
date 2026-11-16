# Audit B: data going in and through (2026-11-14)

Read-only audit. Tree read: `/home/user/Auto-GPT/.claude/worktrees/latest/trialbox` at `origin/train/17` = `0c8e1211`.
Lane G branches read with `git show`: `lg/batch6` (now `ab6f5213`; brief said `73bb84e0`), `lg/batch7` (`befe8e6b`),
`lg/batch8` (`40c5e5c6`, merges train 17). Nothing was run. "Not verified" means I did not check it.

## 0. The short version

- **Every real-model result in the repo is from an older commit.** The newest note-reading run (`02858674`, public data)
  is 229 commits behind. Since then: B14 (#586), negation (#572), family history (#573), #570, #567, the English site
  (#591), and **masking v2 and v3 (D-744 #598, D-745 #599, now in train 17)**. Masking changes the text the models read.
  So every note-reading result is STALE.
- **No real-model run has ever judged real zh-TW clinical text.** None exists in the repo. The only zh-TW "notes" are
  TrialBox's own translations of SIGIR, and templated synthetic sentences.
- **The synthetic hospital's notes are templates.** About 20 filler sentences per language plus one fixed sentence per
  finding (`tools/synth/notes.py`, `notes_ja.py`, `notes_en.py`). The 50,000-patient run's "463 model exclusions,
  0 false" (`g3-50k-2026-11-13/report.md:72`) shows that the pair can read its own templates. It says nothing about
  a real hospital's notes.
- **"Three languages" is mostly the console language, not the data language.** `hospital-ja` and `hospital-zh-TW`
  screen the same generated hospital (`tools/complete_run.py:319-336`, `part_hospital` symlinks
  `synth-{patients}`). `public-ja`, `public-zh-TW`, `public-en` read the same en+ja notes. Paying twice or three
  times buys a screenshot language, not a new data language.
- **The test harness never uses the production embedder.** Every in-process box ingests with `HashEmbedder`
  (`tests/inproc_box.py:23,209,237,260`). The semantic stage S2b is skipped or "not evaluated" there
  (`services/matching/cascade/engine.py:130-132,358-362`). SCREEN on a box does not use the embed service yet
  either (#589, plan 37 line 34). So the RA-JAK and AD-MAB note criteria cannot be judged by any run today.
- **The condition status and abatement path has no data at all.** The generator always writes status `A`
  (`tools/synth/generator.py:242`, every `dx(...)` call uses the default). The FHIR reader does not read
  `abatement[x]` (`docs/data/01-inbound-fhir-contract.md:58`). Matching does not read the condition status
  (lane G's own commit `1f7f0765`: "matching does not read the status").
- **Three public-data checks were loosened by lane G after they failed** (`73bb84e0`). Two scenario paths bypass the
  product: TREC CT uses `tools/mlbench`'s bake-off prompt straight to vLLM (`tools/scenarios.py:2053-2064,2090`),
  and MIMIC always runs on the stub (`tools/scenarios.py:1873-1934`).

## 1. What the latest repo does here (map)

| Stage | What the product does (latest tree) | Where |
| --- | --- | --- |
| Site formats in | Hospital CSV feed (CGRD-style, mapped by `tw_core/demo_his.yaml` for **both** JP- and TW-style sites); SS-MIX2 storage (HL7 v2, 疑い, JP Core `$validate`); FHIR bulk NDJSON (TW Core / JP Core profiles); messy Excel, Shift_JIS and Big5 CSV; pasted chart text; chart files (Word, text PDF, scans through Tesseract OCR); REDCap two-way and built-in forms; IT dump with local codes mapped once; offline registry from the reference pack; MIMIC normalisation | `services/adapter/mapping/{tw_core,jp_core,mimic,templates}`, `tests/inproc_box.py:229-260`, `tools/scenarios.py:1-28` |
| Lake | flatten to lake tables; OMOP store with parity, tombstones, in-place updates; condition `status` stored, suspected (`verificationStatus`) kept apart as `site_fact` basis `suspected` | `services/lake/flatten.py:167,226,554-565`, `services/omop/load.py:436-453`, `services/matching/proposed.py:11-44` |
| Not read | `Condition.abatement[x]`, `onsetPeriod`, `Observation.interpretation/note`, AllergyIntolerance, MedicationAdministration/Dispense, Immunization; condition clinical status is stored but not used by matching | `docs/data/01-inbound-fhir-contract.md:57-63`; commit `1f7f0765` message |
| Terminology | small sample lookups: byomei->ICD-10 33 rows, JLAC10->LOINC 15, YJ->ATC 23, TW lab->LOINC 15; licensed lists as samples only; full reference pack loaded only on a box by `tools/refdata_fetch.py` | `services/adapter/mapping/jp_core/*.csv`, `tests/fixtures/licensed`, `tests/fixtures/refdata` |
| De-identification | note masker version 3 (D-745: dates of birth, addresses, chart labels, email; D-744: English phones) | `libs/tb_common/phi_guard.py`, `docs/decisions/D-744…`, `D-745…` |
| Screening | cascade S0-S5: coded filters, lexicon, S2b semantic search (needs a real embedder), S3 judge+verifier through the gateway (`judge_v5`), excerpt builder with clipping (T-710), chart facts (`chart_facts_v2`) proposed then confirmed | `services/matching/cascade/engine.py`, `services/matching/excerpts.py`, `libs/tb_llm/prompts/registry.yaml` (`prompts-2026-11-11`, all `qualification: null`) |
| Lifecycle | protocol -> `ir_extract_v3` / `concept_map_v2` compile -> ruleset -> FEAS -> SCREEN -> candidate list -> marks, mail -> REDCap/EDC, `crf_prefill_v2`, `draft_doc_v2`, consent prompts -> handover | `libs/tb_llm/prompts`, `services/criteria_compiler`, `services/orchestrator`, `services/edc` |
| Console | roles admin, crc, pi, viewer, cra, stw; languages ja, zh-TW, en | `tools/public_walk.js:129` |
| Synthetic hospital | profiles `ci` (JP+TW 2,500 each), `ci-ja`, `ci-zh-TW`, `ci-en` (EN, TW table layout, D-743), `jp-ad` (2,500; AD-MAB, NEUR-COH, GZQO, RA-BIO), `tw-ra` (1,500; RA-JAK, GZQO, RA-COH, RA-BIO), `full` (500,000), dense (`tb_testkit.scale.densify`: 500 records, 40 notes per patient by copying rows weeks earlier) | `tools/synth_hospital/__init__.py:39-67`, `libs/tb_testkit/scale.py:671-750` |
| Rulesets | AD-MAB, GOUT-COH, GZQO, NEUR-COH, ONC-OSI, RA-BIO, RA-COH, RA-JAK (hand-built, committed) | `rulesets/` |

## 2. Inventory

Class: CURRENT / STALE / STUB (legit or counted) / MISSING. "Last real-model run" means a run with the pair on the
card, results in `docs/plan/measurements/`. Commits ahead are counted to `0c8e1211`.

### 2.1 Synthetic hospital and its profiles

| Item | Where | Last real-model run | Class | Evidence | Action | Owner lane |
| --- | --- | --- | --- | --- | --- | --- |
| `ci` hospital, 50,000, GZQO + GOUT-COH, run as `hospital-ja` and `hospital-zh-TW` | `tools/complete_run.py:319-336,78` | 2026-11-13, `c25cea6b` (636 commits behind), FAILED 227/228 each | STALE | `g3-50k-2026-11-13/README.md`; fixes since: #586, #572, #573, #570, #567, D-744, D-745 | Re-run once on the latest tree as **one** data run (not twice by console language). Treat it as capacity, not accuracy | G |
| `ci` notes themselves | `tools/synth/notes*.py` | n/a | STALE as accuracy evidence | ~20 filler sentences per language and one fixed sentence per finding; only GZQO-INC-05 and GZQO-EXC-11 decide in notes (`tools/scenarios.py:59-61`); 92/5,000 patients reach S3 (`tools/complete_run.py:1665`) | Keep for plumbing and capacity. Stop citing it as accuracy | B2 |
| `ci` 5,000 curve (G-3 at 1, 4, 16) | `g3-2026-11-13` | 2026-11-13, `2b9eec74` (1,026 behind), 1/10 parts passed | STALE | README | Retire as capacity evidence; re-measure only on the latest tree | G |
| `ci-en` (English site) | `tools/synth_hospital/__init__.py:47-48`, D-743 | never | MISSING (real model) | not in latest `LANGS` (`tools/complete_run.py:72`); `hospital-en` only in `lg/batch8` | One 5,000 run on the latest tree. Note: TW table layout with English names, not a US/English record format | B2 data, G run |
| `ci-ja`, `ci-zh-TW` | same, lines 44-45 | never | MISSING | no `--profile` in `part_prepare` | Only needed for the demo; low priority | G |
| `jp-ad` (AD-MAB, NEUR-COH) | lines 49-55; `tools/synth/ad.py` | never | MISSING | no part; AD-MAB's 4 note criteria have no lexicon and the harness has no semantic embedder: "not evaluated" | Blocked on #589 and a real embedder in the harness | B2, C2 (#589), G |
| `tw-ra` (RA-JAK, RA-COH, RA-BIO) | lines 58-63; `tools/synth/rajak.py` | never | MISSING | same; RA-JAK-EXC-06/07 note halves | same | B2, C2, G |
| `full` 500,000 | line 40 | never | MISSING | cost table L11/L12 are extrapolated and use two `ci`-style sites, not `full` | Do not run until the incremental night exists (T-694, T-702, T-703) | B2, G |
| dense profile | `libs/tb_testkit/scale.py:696` | never | MISSING | copies of the same rows and notes shifted by weeks: same text repeated, not new content | Fine for capacity (G-6). Not for accuracy | B2 |
| Rulesets ONC-OSI, RA-BIO, RA-COH, RA-JAK, AD-MAB, NEUR-COH | `rulesets/` | never | MISSING | the hospital part screens GZQO and GOUT-COH only (`tools/complete_run.py:78`) | A part per profile and its studies | G |
| Condition status / abatement in synthetic data | `tools/synth/generator.py:242` | never | MISSING | status always `A`; no `R`, no abatement, no inactive | Generator emits resolved/inactive/remission with dates and truth; but first decide whether matching should read status (it does not) | B2 data; product decision first |
| Longitudinal change (night N+1) | `tools/goldens.py:143-206` | never | MISSING | only "a tenth deleted" and "restored" nights for goldens; no new notes, new diagnoses, resolved disease, or a patient becoming eligible | Build a night-series generator with eligibility-change truth | B2 |

### 2.2 Scenarios in `tools/scenarios.py`

All synthetic scenarios use the `ci` generator (templated notes) and screen GZQO only. Sign-in language is the run's
first language only. None has an English data variant.

| Scenario | Data built, language | Model path | Last real-model run | Class | Evidence | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| emr-ssmix2 | `ss:JP:n` (`:794`), ja + 10 % en; ICD-10 turned into byomei/JLAC10/YJ by the same 33/15/23-row tables the reader uses back | gateway pair when `--model pair` (`:298-322`) | never | MISSING | g1 runs list no ssmix2 part | Run on latest. Also needs a real-shaped SS-MIX2 sample (real code spread, real vendor quirks): the round trip is circular | D (scenarios), E (mapping), G |
| emr-fhir | `fh:TW:n` (`:951`), zh-TW + en; FHIR made by TrialBox's own `fhir_export` from its own CSV (`:902`) | gateway pair | 2026-11-12, `931a0f79` (not an ancestor of latest), 11/11 | STALE | `g1-2026-11-12/README.md` | Re-run; add vendor-shaped TW Core / JP Core bundles (IG examples) | D, E, G |
| site-excel | JP + TW sheets, Shift_JIS, Big5 | gateway pair for SCREEN | never | MISSING | | Run on latest | D, G |
| chart-paste | `synth_charts` ja and zh-TW only, templated traps | gateway `chart_facts_v2` | never | MISSING | no part in any measurement | Run on latest; add English charts | D, G |
| chart-files | same charts; scans rendered from fonts; Tesseract only with `--ocr` (`:1287-1294`) | gateway | never | MISSING | | Run with real Tesseract; add real scan noise (skew, stamps, handwriting) | D, G |
| redcap | `rc:JP:300`, `rc_sim` simulator, not a REDCap server | no model reading | n/a | STUB (legit: no model) | `:1574-1584` | Keep. A real REDCap instance check exists separately (`tools/redcap_instance.py`, not verified) | C |
| it-dump | `du:JP:60`, Shift_JIS, local codes | no model | n/a | STUB (legit) but counted in D-502 matrix | cost table row "runs, no model" | Do not count as a real-model item | D |
| registry | reference-pack sample, 6 trials | no model | n/a | STUB (legit), counted | same | Same | D |
| gateway probe | two calls | gateway | 2026-11-12, `931a0f79`, 3/3 | STALE (probe only) | g1 README | Fold into every run's start; not a data set | G |
| public-mimic | MIMIC-IV demo FHIR, 100 patients, en, **no notes** | **always the in-process stub** (`cascade_e2e`, `:1873-1934`) | never possible | STUB, counted as a data set (not legit) | `:1934` note; VALIDATION §5 "no notes in the demo, so the judge is not exercised" | Re-point the cascade at the run's gateway, or drop it from the model matrix (coded only) | D, G |
| public-medtxt | 148 MedTxt-CR reports, real ja clinician text, pasted as charts | gateway `chart_facts` | 2026-11-14, `02858674` (229 behind), FAILED 2/3 | STALE | `lg/batch6:…/public-2026-11-14/README.md` | Re-run on latest (after #572, #573, D-744, D-745). Restore the original check (see section 5) | D, G |
| public-trec | TREC CT 2021/22, 50+50 pairs, en | **`tools/mlbench` bake-off prompt straight to vLLM, no gateway, no `judge_v5`, no cascade, no excerpt builder** (`:2053-2064,2090`) | 2026-11-14, `02858674`, FAILED 0/2 | STALE and off-path | the scenario's own note: "an evaluation path, not the box" | Re-point: build a TREC site and run SCREEN through the box (gateway, `judge_v5`, cascade). Keep mlbench only as a model comparison | D, A2, G |

### 2.3 Public sets and evals

| Item | Where | Last real-model run | Class | Evidence | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| Public site (SIGIR 53 en + MedTxt-CR/RR ja; 268 patients, one note each, no labs, no meds) | `tools/public_site.py`, `tools/public_e2e.py` (rulesets PUB-ONC, PUB-CA) | ja and zh-TW consoles 2026-11-14 `02858674` PASSED 130/130; en 2026-11-08 (pre-gateway era, `gpu-run-2026-11-08`) | STALE | lg/batch6 README | Re-run **once** (one console language). It checks counts and plumbing; it has **no gold for the model's note answers** (`tools/public_e2e.py:379-405` checks FEAS counts against derived facts) | E (public_site), G |
| public-zh-TW | same notes, zh-TW console | as above | STALE and mislabelled | cost table line 134 | Stop calling it zh-TW data | G |
| TREC CT full (N-12, 1,700 pairs) | `tools/trec_ct_eval.py`, `deploy/gcp/gpu-pro6000-run.sh` | 2026-11-08, 9.4 % unadjusted, fail | STALE and off-path (old one-boot script, mlbench prompt, not the box) | `docs/VALIDATION.md:70`; cost table row N-12 | Retire the one-boot script. Re-run through the box path as above | A2, G |
| SIGIR criterion set (N-11, 1,015 pairs; ja/zh-TW are TrialBox translations) | `eval/criterion_ml`, `eval/parity/replay.json` | recorded answers, not a 2026-11 card run | STALE (recorded) | `docs/VALIDATION.md:69,74-76` | Re-run through the box path; label the ja/zh-TW rows "translation" | A2, G |
| MedTxt eval (CR+RR, 1,677 findings) | `tools/medtxt_eval.py`, `eval/medtxt` | recorded answers, API era | STALE | cost table line 157 | Re-run on the card via the gateway | A2, G |
| `tests/fixtures/llm/judge_set.jsonl` (300 items) | used by `tests/llm`, `tools/judge_eval.py` | n/a | STALE | last change `77ef9920` 2026-10-04; built from the old generator's templates | Regenerate from the current generator or retire; never count as accuracy | B2, A2 |
| Pair canary (54 one-sentence cases, en/ja/zh-TW 18 each) | `services/orchestrator/canary/judge_canary.jsonl` | 54/54 judge on 2026-11-08 | CURRENT as a smoke test | file from 2026-11-07 | Keep as a gate. It is not an accuracy set | A |
| open_cohorts, AD slice, match_registry, Chia | `eval/*` | never on the card | MISSING | Chia licence conflict: `chia` CC BY 4.0 vs `criteria_extract_public` "licence unconfirmed, loader disabled" (`eval/DATASETS.yaml`) | Settle the Chia licence; then use Chia for compile gold | A2, owner |
| Synthea | `tools/synthea_ad_cohort.py` | never | MISSING (no mapping) | `tools/scenarios.py:94` | Only if an English/US site format is wanted; Synthea can emit notes and US FHIR | B2/E |
| `eval/DATASETS.yaml` `synthetic_hospitals` row | says `tests/fixtures (generated by tools/make_fixtures.py)` | n/a | STALE text | the generator is `tools/synth_hospital` | Fix the row | B2 |

### 2.4 Fixtures used as "validation"

| Item | Where | Class | Evidence | Action | Owner |
| --- | --- | --- | --- | --- | --- |
| HIS fixtures site-a, site-b | `tests/fixtures/synthetic_patients` | STALE | last change `bd7c58b2` 2026-10-04; lake schema, masking and mapping changed since | Regenerate from `tools/synth_hospital`, or keep only for unit tests; no real-model run planned should use them | B2/E |
| `demo_his.yaml` (maps JP and TW feeds alike) | `services/adapter/mapping/tw_core/demo_his.yaml` | CURRENT path, thin data | maps status A/R (`:154-156`), but no data ever sends R | Data with R and unknown codes | E |
| SS-MIX2 golden set (400 patients) | `tools/goldens.py:28` | CURRENT (stub, legit) | goldens, no model | Keep | B2 |
| Licensed and refdata samples | `tests/fixtures/licensed`, `tests/fixtures/refdata` | CURRENT for unit tests | samples only | A check that the full pack loads on a box and the real code spread maps | E |
| Public protocols G-8 compiles (batch 7) | `lg/batch7:…/tests/fixtures/public_protocols_g8/` | STALE by design | copied from `cb850470`, before B14; AD protocol failed on B14 | Do not merge as fixtures until the G-8 re-run on latest | G |
| Encodings fixtures (Shift_JIS, Big5, EUC-JP) | `tests/fixtures/encodings` | CURRENT (no model) | | Keep | E |

### 2.5 Lifecycle and roles

| Item | Last real-model run | Class | Evidence | Action | Owner |
| --- | --- | --- | --- | --- | --- |
| Protocol compile (`ir_extract_v3`, `concept_map_v2`) on public protocols NCT02629159, NCT03887455 | 2026-11-14, `cb850470` (483 behind), FAILED, before B14 | STALE | `g8-2026-11-14` | Re-run on latest; add ja and zh-TW protocols with gold IR | A2, G |
| Committed rulesets (8) compiled by a model | never: hand-built | MISSING | `rulesets/` | Compile each committed protocol (`tests/fixtures/protocols/*.docx`, ja titles) with the real model and diff against the committed IR | A2, G |
| Candidate list, marks, mail | inside hospital parts; stale as above | STALE | | Comes with the hospital re-run | G |
| `crf_prefill`, `draft_doc`, consent prompts, `profile_summary`, `classify_intent`, `assist`, `ie_locate` | never in any measurement (`grep` of `docs/plan/measurements`: 0 hits except `consent_date` field) | MISSING | | A small real-model set per prompt, per language | A/A2, G |
| Console walk (6 roles x 3 languages) | stub only | STUB (legit: no model decides) | `docs/VALIDATION.md:18` | Keep on stub | C |

## 3. Retire list

| Retire | Why | Whose | Replace with |
| --- | --- | --- | --- |
| Citing `hospital-*` 463/463 correct exclusions as model accuracy | templated notes, 2 note criteria | G (reports), B2 | the real-note accuracy set (4.1) |
| Running the same data once per console language (`hospital-ja` + `hospital-zh-TW`, `public-ja` + `public-zh-TW` + `public-en`) as "three languages" | same notes each time | G (`complete_run`, cost table L1, L2, L4) | one data run; console language covered by the stub walk |
| `public-trec` scenario's direct mlbench call as product evidence | bypasses gateway, `judge_v5`, cascade, excerpt builder | D / G | TREC as a site screened through the box |
| `deploy/gcp/gpu-pro6000-run.sh` for N-12 | old one-boot path outside `make rehearse` (cost table line 155) | G | driver part on the box path |
| `public-mimic` in the real-model matrix | always the stub; no notes | D / G | gateway-pointed cascade, or drop from the model matrix |
| `it-dump`, `registry`, `gateway` rows as D-502 "data sets" | no model reads them | G | list them as plumbing checks |
| The loosened checks of `73bb84e0` (TREC bound from N-12's own answers; MedTxt "treated negative" carve-out) | thresholds moved after a failure, by the lane that runs the test | G (`lg/batch6`) | the original zero-tolerance negation check plus a separately reported, clinician-reviewed "past, treated" class |
| `lg/batch7` G-8 compile fixtures from `cb850470` | pre-B14 failure frozen as fixture | G | fixtures from a latest-tree G-8 run |
| `tests/fixtures/llm/judge_set.jsonl` as a model test set | 2026-10-04 templates | B2/A2 | regenerated or retired |
| `tests/fixtures/synthetic_patients` as validation input | 2026-10-04, older than the schema | B2/E | `synth_hospital` output |
| Cost table's L11/L12 (500,000) and L6-L10 (G-3 curve) | 500,000 is extrapolated on today's non-incremental night; 32/48 measure the gateway queue | G | after T-694/T-702/T-703; one curve point set at 50k dense |

## 4. Needed validation data and runs, ranked

Ranked by the brief's order: wrong answer on real notes, then lost eligible patients, then data-path breakage per
site format, then capacity, then install/upgrade. "Run" means on the GPU VM, latest tree, through the box path
(gateway, `judge_v5`, `chart_facts_v2`, cascade with the excerpt builder, masking v3), after #589 so S2b uses the real
embedder.

| Rank | Data needed | Language | Size | Gold, who makes it | Licence | Exists today? | Real-model run that proves it |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Real-note accuracy set (NEW-LLM-6)**: real clinician notes x criteria, strata: long notes, negation, family history, past/treated, suspected (疑い/疑似), era dates (和暦, 民國), labs in text, abbreviations, zh-TW code-mixed EMR English | ja | ~200 gold exclusions + ~200 gold "not excluded" per stratum | clinicians (lane A2 organises); not Claude | MedTxt-CR/RR CC BY 4.0 gives the text; labels are new | text yes, gold no | SCREEN of a site built from the notes; measure false exclusions and calibration per stratum |
| 1 | same | **zh-TW** | same | Taiwan clinicians | **no public source exists**. Options: (a) de-identified notes from a partner hospital under an agreement; (b) notes written fresh by bilingual clinicians in real EMR style (not translated) | **no** | same |
| 1 | same | en | same | clinicians; TrialGPT physician labels exist for 1,015 SIGIR pairs | public domain | partly (SIGIR, TREC) | same, through the box, not mlbench |
| 2 | **Lost-eligible set**: eligible patients whose deciding fact is only in a note, buried in a long or dense chart (40+ notes, clipped excerpts), with distractors (resolved disease, family history, a suspected diagnosis) | ja, zh-TW, en | ~200 eligible per language | clinicians write or label | as above | no | SCREEN; count eligible patients lost; the excerpt builder's `left_out` path |
| 3 | **Condition status and abatement**: resolved, inactive, remission, abatementDateTime, suspected | all | ~50 patients per pattern | B2 generator truth | generated | no (always `A`) | First the owner rules whether matching reads status. Then FEAS/SCREEN on the data |
| 3 | **Site format samples that are not TrialBox's own output**: SS-MIX2 with a real code spread (MEDIS byomei, JLAC10, HOT/YJ, local codes, vendor quirks); TW Core and JP Core IG example bundles; a messy real-shaped Excel; an IT dump with a real local-code spread | ja, zh-TW | 100-500 patients each | B2/E | IG examples are public (licence not verified); licensed code lists need the licences the repo already tracks | no (round trips only) | each scenario on latest with the pair |
| 3 | **English site formats**: a US-style FHIR feed (Synthea with notes, or MIMIC demo through the real pair), English charts and scans | en | 5,000 | B2/E | Synthea Apache-2.0; MIMIC demo ODbL | partial (`ci-en` is TW layout) | `hospital-en` plus English chart scenarios |
| 3 | **Real scans for OCR** | ja, zh-TW | ~60 | B2 | generated with noise, or donated blank forms | no (font renders) | chart-files with Tesseract |
| 3 | **Protocols with gold IR** | en, ja, zh-TW | ~10 per language | A2 | ClinicalTrials.gov public; jRCT (licence not verified) | 2 en protocols, no gold | G-8 compile on latest; diff against gold |
| 4 | **Longitudinal nights** | all | 50,000 x 7 nights | B2 generator with eligibility-change truth | generated | no | the incremental night; who became eligible or not |
| 4 | **Dense 50,000 with the real embedder** | ja, zh-TW | 50,000 | densify | generated | generator yes, part no | G-6 night profile |
| 5 | Install/upgrade: qualify record, canary | all | 54 cases | exists | own | yes | inside the R2 bundle run (area outside B) |

Minimum first run that would mean something, given today's tree: one launch on latest with (a) the MedTxt site and
MedTxt chart scenario, (b) TREC through the box path, (c) `ci` at 5,000 in one console language, (d) `ci-en` at 5,000,
(e) emr-ssmix2, emr-fhir, site-excel, chart-paste, chart-files. That covers every live data path once. It does **not**
cover zh-TW real text or accuracy, because the gold does not exist yet.

## 5. What lane G got wrong (blunt)

1. **Size and language were confused with coverage.** The plan spends most of its money on the same templated
   hospital at 50,000 and 500,000, run once per console language. Only ~1.8 % of patients reach the note stage, and
   only two GZQO note criteria decide there. 463 of 463 correct exclusions on template sentences is not evidence for
   a real hospital.
2. **"Three languages" was met on paper.** `public-zh-TW` is the zh-TW console over en and ja notes. The cost table
   says so (line 134) but still prices and counts it. The repo has no real zh-TW clinical text. Lane G did not
   raise this as the top gap.
3. **Failing checks were loosened by the lane that runs them** (`73bb84e0`). The TREC bound is now derived from the
   deployed pair's own recorded answers, so the check can hardly fail. The MedTxt check now excuses "past, treated"
   negatives. Then `1f7f0765` changed the public site's input to match. This moves the goalposts after a failure.
4. **Off-path runs were kept in the plan.** TREC CT uses `tools/mlbench`'s bake-off prompt straight to vLLM. N-12 was
   to run on the old one-boot script. MIMIC is on the stub. These do not test the product.
5. **The embedder was ignored.** Every harness run uses `HashEmbedder`. S2b, and the note criteria without lexicon
   terms (RA-JAK, AD-MAB), are never judged. G-11 was left as a bench proxy. The run plan does not wait for #589.
6. **Stale facts in the cost table.** It says D-744 and D-745 are not in train 17. At `0c8e1211` they are (#598,
   #599). It reads "batch 6 (#592)" as a precondition while the batch keeps moving (`73bb84e0` -> `ab6f5213`).
   `hospital-en` cost is borrowed from ja/zh-TW. `PUBLIC_SECONDS` is twice the measurement.
7. **A pre-fix failure was frozen as fixtures** (`lg/batch7`, G-8 compiles from `cb850470`, before B14).
8. **Plumbing parts were counted as data sets** (it-dump, registry, gateway probe, MIMIC).
9. **No result is on a current commit.** Every measurement folder is 229 to 1,314 commits behind, and lane G's base is
   228 behind. The plan's first launch is not on the latest tree.

## 6. Open questions (not verified here)

1. Should matching read the condition clinical status and abatement? Today it does not. Owner or lane A2 to rule.
2. Can a Taiwan partner provide de-identified notes, or will bilingual clinicians write a zh-TW set? Who pays, who
   labels, under what licence?
3. Does SCREEN on an installed box (not the harness) use the embed service before #589? I read plan 37 line 34 as
   "no"; not verified on the box.
4. Is the clinician gold for NEW-LLM-6 funded and scheduled? Plan 37 line 36 names lane A2; no date found.
5. TW Core and JP Core IG example licences, and jRCT protocol text licence: not verified.
6. Chia: `eval/DATASETS.yaml` gives two different licence statements. Owner or A2 to settle.
7. Why `hospital-ja` listed 627 and `hospital-zh-TW` 628 on the same data (`g3-50k-2026-11-13/README.md`)? Not
   investigated; may be order dependence.
8. Whether `tools/redcap_instance.py` has ever run against a real REDCap server: not verified.
9. Issue #579's text was not readable here; the D-502 file and the cost table were used instead.
