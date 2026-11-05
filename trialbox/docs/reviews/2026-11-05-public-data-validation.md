# TrialBox validation on more public data and at hospital scale (2026-11-05)

Question (Changfu): beyond the 79 eligible pairs of the TrialGPT/SIGIR set, find more data and simulations to
support and validate TrialBox, with Japanese on real text.

All runs: OpenRouter, temperature 0, same `tools/mlbench` judge prompt as every earlier run, US$9 in total. Every rate
below has a 95 % interval from a patient-cluster bootstrap (pairs of one patient are not independent). Raw answers
and scores are committed under `eval/trec_ct`, `eval/medtxt` and `eval/hospital_sim`; the source data is fetched at
run time and never committed.

## Short answer

1. **On 1,200 TREC "eligible" pairs (15x the SIGIR set) the pair rules still hold up, but the raw loss is higher**:
   the one-5090 pair (Gemma 4 26B 4-bit + Qwen3.5-9B, both must block) dropped 19.3 % (16.9-21.9) of NIST-eligible
   pairs, today's Spark pair 24.9 % (21.9-28.1), any single model 31-36 %. A hand check of 30 dropped pairs found that
   only 10 were model errors; 12 were NIST label noise and 5 were criteria of another trial arm. Corrected for that,
   the pair loses **about 6 % of truly eligible pairs (roughly 4-10 %)** when it reads every criterion, in line with
   the 8/79 (10 %) on SIGIR. Under filter first (the LLM reads about 42 % of criteria) the projection is **about
   3.6 % (2.1-5.6 %)**.
2. **Real Japanese text does not cause more wrong exclusions than English; it causes more missed exclusions.** On
   215 real Japanese case and radiology reports (MedTxt, with clinician-made English translations) the pairs block
   stated-absent findings no more often in Japanese (6-9 %) than in English (9-10 %), and those "wrong" blocks are
   mostly tag artefacts (17 of 18 checked were defensible, 1 borderline). What Japanese costs is recall: the one-5090 pair catches
   69 % of present findings in Japanese against 84 % in English. Missed exclusions go to the coordinator, so this
   is the safe direction, but it means more review work for Japanese sites.
3. **Two prompt gaps found and one fixed in test.** Models treat a *suspected* finding as confirmed and exclude on
   it (37-80 % of the time, depending on the model). One added paragraph cuts that to 16-38 % for single models and
   11-22 % for pairs, for a 2-8 point recall cost. Negated exclusions ("Exclusion: No evidence of pituitary adenoma") are the most common model error
   on TREC; a prompt fix helps a little (net 17 fewer dropped pairs, McNemar p about 0.09), not enough: the proper fix
   is to rewrite them at protocol import.
4. **Hospital scale.** The real pipeline (data platform, cascade S0-S5, feasibility pack, recall certificate) passes
   all 16 invariant checks at 2,000, 10,000 and 25,000 synthetic patients, in about 23 ms per patient, growing
   linearly. The in-process test harness needs about 0.5 GB per 1,000 patients and ran out of memory at 50,000 on
   this 16 GB container; see "Hospital-scale simulation".
   Compute is not the bottleneck: model time for a 50,000-patient hospital screening 12 trials a year is a few
   GPU hours. Coordinator review is.
5. **The age/sex filter is right where the data is right.** On TREC it blocked 20 % of NIST-excluded pairs without
   any model, and every "wrong" block on an eligible pair was either label noise (a 34-year-old man marked eligible
   for a 4-21-year trial) or a neonatal trial whose age fields hold gestational age; the filter now leaves
   week-based limits to the reader.

## 1. TREC Clinical Trials 2021 / 2022 (`tools/trec_ct_eval.py`)

Data: 125 NIST patient topics (75 + 50), NIST pair labels (2 = eligible, 1 = excluded), trial texts from NCBI's
TrialGPT corpus, structured age/sex limits from the ClinicalTrials.gov API. Seeded sample: 600 eligible and 250
excluded pairs per year, trials with at most 40 criteria; 1,700 pairs, 1,682 trials, 20,096 criteria, judged one
criterion at a time by the TrialBox prompt.

| models | eligible pairs dropped (95 % CI) | excluded pairs caught (95 % CI) | $ |
| --- | --- | --- | --- |
| age/sex filter alone (no model) | 1.9 % (23 / 1,200; label noise, see AUDIT.md) | 19.8 % (99 / 500) | 0 |
| Gemma 4 26B | 34.3 % (30.7-38.0) | 71.6 % (65.9-77.4) | 1.05 |
| Gemma 4 26B 4-bit | 31.0 % (27.9-34.1) | 67.2 % (61.9-72.7) | 0.82 |
| gpt-oss-120b | 35.8 % (32.1-39.4) | 70.8 % (64.6-76.7) | 1.05 |
| Qwen3.5-9B | 34.5 % (30.9-38.3) | 66.0 % (60.5-71.4) | 1.03 |
| gpt-oss-120b + Gemma 4 (Spark pair) | 24.9 % (21.9-28.1) | 63.6 % (57.0-70.2) | 2.10 |
| Gemma 4 4-bit + gpt-oss-120b | 21.8 % (19.0-24.6) | 60.8 % (54.5-66.9) | 1.87 |
| gpt-oss-120b + Qwen3.5-9B | 20.8 % (18.0-23.6) | 57.0 % (51.3-62.6) | 2.08 |
| **Gemma 4 4-bit + Qwen3.5-9B (one 5090)** | **19.3 % (16.9-21.9)** | 54.2 % (49.0-59.5) | 1.86 |
| same pair + age/sex filter first | 20.3 % (18.0-22.9) | 59.6 % (54.2-65.2) | 1.86 |

Reading it:
- **The ranking from SIGIR survives a set 15x larger.** Two models that must agree drop 30-45 % fewer eligible
  pairs than either alone, and the one-5090 pair is still the most careful, at the price of catching fewer of the
  excluded pairs (54 % vs 64 %).
- **The raw numbers are not error rates.** TREC labels judge the trial as a whole from a short synthetic topic.
  `eval/trec_ct/AUDIT.md` reads one blocking criterion from each of 30 dropped pairs: 10 model errors, 12 cases where
  the criterion plainly blocks ("Male veterans" for a woman, "No diagnosis of essential tremor" for a confirmed
  essential tremor) yet NIST said eligible, 5 criteria of another arm (healthy controls) applied to patients, 3
  ambiguous. 10/30 has a Wilson interval of 19-51 %.
- **Model error patterns**: 5 of 10 are negated exclusions, 2 are "other X" exclusions applied to the trial's own
  index condition, 3 are blocks with no evidence. Multi-arm trials need arm-aware criteria parsing.
- **Age/sex filter**: CT.gov structured fields exist for all 1,682 trials; age and sex were parsed from all 125 and
  123 of 125 topics. Adding the filter catches 5 more points of excluded pairs and costs 1 point of eligible pairs,
  all of it label noise.

Negation prompt variant (`--variant negation`: read negated exclusions literally, "other" does not cover the index
condition, trial title passed with the criterion), same 1,700 pairs:

| models | dropped, base -> variant | caught, base -> variant |
| --- | --- | --- |
| Gemma 4 4-bit | 31.0 -> 28.6 % | 67.2 -> 65.6 % |
| gpt-oss-120b | 35.8 -> 32.5 % | 70.8 -> 70.8 % |
| Qwen3.5-9B | 34.5 -> 29.9 % | 66.0 -> 63.6 % |
| Gemma 4 4-bit + Qwen3.5-9B | 19.3 -> 17.9 % | 54.2 -> 55.6 % |

For the pair, 59 dropped pairs were kept and 42 kept pairs were dropped (McNemar p about 0.09). Consistent but small;
the prompt alone does not fix negation. Recommendation: normalise negated exclusions to the positive form in
`ir_extract` at protocol import, where a person checks the IR anyway.

## 2. Real Japanese clinical text: MedTxt (`tools/medtxt_eval.py`)

Data: NTCIR-16 Real-MedNLP test collection (Sociocom, NAIST, CC BY 4.0): 148 Japanese case reports (MedTxt-CR,
training split, the test split is not redistributed) and 135 radiology reports (MedTxt-RR), each with an English
translation, every disease/finding tagged positive / negative / suspicious / general. 215 reports whose Japanese
and English tags align are used. Each tagged finding becomes the exclusion criterion "Patients with <finding>."
(English wording, as an international protocol reads) judged against the Japanese original and the English
translation. Items: 659 present, 253 stated absent, 151 suspected (after dropping tags contradicted elsewhere in the
same report), 430 not mentioned (a finding taken from another report).

Share of items where the models block (exclude). Higher is right for "present"; lower is right for the rest.

| models | lang | present | stated absent | suspected | not mentioned |
| --- | --- | --- | --- | --- | --- |
| gpt-oss-120b + Gemma 4 (Spark pair) | ja | 87.7 % (85-90) | 8.7 % (5-13) | 66.9 % (58-75) | 6.3 % (4-9) |
| | en | 95.1 % (93-97) | 9.5 % (6-14) | 64.9 % (56-73) | 6.3 % (4-9) |
| Gemma 4 4-bit + Qwen3.5-9B (one 5090) | ja | 69.0 % (65-73) | 6.3 % (3-10) | 41.1 % (33-50) | 3.7 % (2-6) |
| | en | 84.1 % (81-87) | 9.1 % (6-13) | 36.4 % (29-44) | 4.2 % (2-6) |
| Spark pair, "suspected" prompt fix | ja | 82.5 % (80-86) | 8.3 % (5-12) | 17.9 % (12-25) | 4.9 % (3-7) |
| | en | 87.7 % (85-90) | 8.3 % (5-12) | 21.2 % (15-28) | 5.1 % (3-7) |
| one-5090 pair, "suspected" prompt fix | ja | 62.4 % (58-66) | 4.3 % (2-8) | 11.9 % (7-18) | 4.2 % (2-6) |
| | en | 76.2 % (73-80) | 7.1 % (4-10) | 14.6 % (9-20) | 3.3 % (2-5) |

Single models are in `eval/medtxt/results/scores.json`. Reading it:
- **Japanese vs English**: blocks on absent or unmentioned findings are never more than about 1 point higher in
  Japanese than in English, well inside the intervals, and lower for both pairs. Recall on present findings is 5-15
  points lower in Japanese, largest for Qwen3.5-9B (75.6 vs 87.4 %). In TrialBox
  terms a missed exclusion is a patient sent to review, not a patient lost.
- **The "stated absent" and "not mentioned" blocks are mostly not model errors.** A tag is local to one sentence, a
  criterion is about the patient. Of 18 such blocks read by hand (gpt-oss-120b + Gemma 4, English), 17 were
  defensible and 1 borderline (a ground-glass nodule read as a tumour): metastasis negated in one organ but present in another, a lesion resected or resolved (history), a
  synonym of a finding that is present. So these rates are upper bounds on the wrong-exclusion rate.
- **Suspected findings are a real gap.** Without guidance the models read "lung cancer is suspected" as lung
  cancer. The `--variant suspected` paragraph (suspected / possible / rule-out is "not enough information"; resolved
  is history) cuts these exclusions by two thirds and costs 2-8 points of recall. Recommended for `judge_v3.md`.
- Caveat: case reports and radiology reports, not admission notes or discharge summaries. Still no Japanese EHR notes.

## 3. Hospital-scale simulation (`tools/hospital_sim.py`)

### Measured: the real pipeline at growing size

Synthetic hospitals from `tools/synth` (fictional patients with planted truth), the full in-process path of
`tools/cascade_e2e.py` (adapter -> data platform L0-L5 -> cascade S0-S5 -> DL-1 pack -> recall certificate), stub
model, GZQO ruleset, one process per size.

| patients | pipeline time | per patient | peak memory | pass S1 filters | S5 review queue | final list | model calls | checks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2,000 | 40 s | 20 ms | 0.9 GB | 64 (3.2 %) | 42 | 5 | 78 | 16 / 16 |
| 10,000 | 173 s | 17 ms | 3.4 GB | 266 (2.7 %) | 173 | 10 | 277 | 16 / 16 |
| 25,000 | 468 s | 19 ms | 8.2 GB | 654 (2.6 %) | 408 | 31 | 770 | 16 / 16 |
| 50,000 | 805 s | 16 ms | 17.0 GB (12.0 RAM + 5.0 swap) | 1,393 (2.8 %) | 923 | 80 | 1,362 | 16 / 16 |

The recall certificate was issued at every size, including all 50,000 patients.

Every run passed all 16 invariant checks (published, no blocking data-quality defect, lineage complete, monotone
funnel, cascade equals the v1 funnel, small cells suppressed, reproducible, and the rest). Time and memory grow
linearly (about 17 ms and 0.34 MB per patient). The first 50,000-patient attempt was killed at 13.5 GB: the lake
rebuild held every note embedding as a Python list (about 32 KB a chunk). D-103 keeps them as float32 and inserts in
batches, which cut memory by about a third (25,000 patients: 12.1 GB before, 8.2 GB after); the 50,000 run then
finished on this 16 GB container with a 12 GB swap file added. The test harness still holds lake, traces and pack in
one process; the deployed stack splits them, so a real box needs less.

### Projected: a 50,000-patient hospital, 12 trials a year

`python -m tools.hospital_sim project --patients 50000 --trials-per-year 12` combines the measured funnel with the
TREC error rates (bootstrap over TREC patients) and the audit share (Beta(11, 21)). Planning constants are
parameters: 2 truly eligible patients per 1,000 per trial, LLM reads 42 % of criteria, 10 minutes per review,
2,500 tokens/s on the box.

| per year (GZQO-like protocol, one-5090 pair) | point | 95 % range |
| --- | --- | --- |
| patient x trial screens | 600,000 | |
| pass the structured filters (synthetic funnel) | 15,700 | |
| model calls / GPU hours (stub-measured call count) | 18,500 / 1.2 h | |
| review queue / coordinator hours at 10 min each | 9,800 / 1,630 h | |
| truly eligible patient x trial pairs (2 per 1,000) | 1,200 | |
| dropped by the model, raw TREC rate | 129 (10.7 %) | 111-149 |
| dropped by the model, audit-adjusted | **43 (3.6 %)** | 25-68 (2.1-5.6 %) |

Japanese uses the same numbers: on MedTxt the Japanese wrong-block rate was not higher than the English one (ratio
0.78, floored at 1), so the projection does not get worse; the Japanese cost is the lower recall, which lands in the
review queue, not in the dropped count.

The review queue is the cost that matters, and its size here comes from the synthetic generator, which plants many
borderline patients on purpose; a real site's funnel replaces it after the first FEAS run.

## 4. Round 2: two more cohorts, Alzheimer's, Chia, judge v4

Asked the same afternoon: more data, more detail, an Alzheimer's focus. Figures are in `docs/figures/validation`
(`python -m tools.validation_figures`; every plotted number with its interval is in `figure_data.json`).

### More cohorts (`tools/open_cohorts_eval.py`, `tools/ad_eval.py`), RTX 5090 pair, judge v3

| Cohort | Pairs | Criteria | Eligible dropped, raw | Excluded caught | Spot check | True loss, about |
|---|---|---|---|---|---|---|
| TREC CT 2021-22 | 1,200 eligible / 500 excluded | 20,096 | 19.3 % (16.9-21.9) | 54.2 % | 10 errors in 30 | 6.4 % |
| SIGIR 2016, full cohort | 413 eligible | 3,326 | 11.6 % (8.5-15.5) | (no excluded pairs) | none | |
| TREC CT 2023 (structured questionnaires) | 600 / 300 | 12,134 | 35.2 % (27.6-43.7) | 78.3 % | 2 in 12 | 5.9 % |
| Alzheimer's trials x TREC patients | 150 / 65 | 3,184 | 30.7 % (24.0-44.0) | 58.5 % | 3 in 15 | 6.1 % |

The Spark pair (gpt-oss-120b + Gemma 4) drops 12.6 % on SIGIR, 41.2 % on TREC 2023 and 34.0 % on the AD slice; any
single model is 6-20 points worse than either pair on every cohort. The raw rates differ a lot between cohorts
because the labels do: TREC 2023 and the AD slice mark many pairs "eligible" that fail a written criterion (an
uveitic glaucoma patient for a primary open-angle glaucoma trial, an Alzheimer's dementia patient for an MCI-only
trial). Read by hand, the share of drops that are real model errors is about the same everywhere, and so is the true
loss: **about 6 % when every criterion goes to the models**, before filter first. Spot checks are small (12-30
pairs), so treat the adjusted rates as indicative; see `eval/open_cohorts/AUDIT.md` and `eval/ad/AUDIT.md`.

### Judge v4 ablation (suspected findings never exclude, D-96), RTX 5090 pair

| Cohort | Eligible dropped, v3 -> v4 | Excluded caught, v3 -> v4 |
|---|---|---|
| TREC CT 2021-22 | 19.3 % -> 19.8 % | 54.2 % -> 55.2 % |
| SIGIR 2016 | 11.6 % -> 10.4 % | |
| TREC CT 2023 | 35.2 % -> 31.5 % | 78.3 % -> 82.3 % |
| MedTxt suspected findings excluded (en / ja) | 37 / 41 % -> 15 / 12 % | recall of present findings 84 / 69 % -> 76 / 62 % |

v4 costs nothing on the pair cohorts and fixes the suspected-finding error, at a few points of recall on notes.
It is now the default prompt for new rulesets.

### Who decides each criterion (`tools/chia_routes.py`, Chia, CC BY 4.0)

On Chia's 12,337 expert-annotated criteria of 1,000 trials, a fixed rule on the entity labels gives: structured
filter **54 % (52-55)**, LLM reads the notes 30 % (29-31), a person decides 16 % (14-18). Negated exclusions, the
commonest model error, are 5.8 % of exclusion lines and can be rewritten at protocol import. An LLM router agreed with
the entity rule on 61 % of 600 criteria (kappa 0.34), so the split is a band, not a point: 42-58 % filter.

### Alzheimer's trials on ClinicalTrials.gov (400 interventional phase 2/3 trials since 2015, 9,381 criteria)

Routed by gpt-oss-120b: filter 42 %, LLM 28 %, person 30 %. The person share is higher than in Chia because AD
protocols carry many study-partner (340), consent or capacity (543) and logistics (525) criteria. Cognitive and
functional scores (767 criteria: MMSE, CDR, ADAS-Cog) and amyloid or tau biomarkers (221) mostly need the notes or
reports, because a site rarely holds them as coded values; APOE and age are filterable. For a trial-ready cohort this
says which fields to capture as structured data up front (MMSE/CDR with date, amyloid PET or CSF status, APOE, study
partner availability) so that most AD criteria move from "LLM" or "person" to "filter".

### Synthea: an Alzheimer's trial-ready cohort from coded data (`tools/synthea_ad_cohort.py`)

Synthea (Apache-2.0) generated 14,865 synthetic people aged 55-90 at start (10,001 alive and 50-90 on 5 Nov 2026).
The coded criteria of an early-AD protocol (modelled on lecanemab Clarity AD, NCT03887455) were applied twice, in
Python and in DuckDB SQL, and every patient's flags agree. 852 have an Alzheimer's diagnosis; only 38 have a current
MMSE of 22-30 and 29 pass every coded exclusion (2.9 per 1,000 adults). The MMSE is the bottleneck: 449 of the 852
have no MMSE in the last 12 months and 52 none at all, against 313 whose score is too low. Amyloid status, MRI
findings and the study partner are not coded and go to the LLM (reports) or a person. For a trial-ready cohort this
is the case for capturing a dated MMSE or MoCA routinely: re-testing the 449 with a stale score is the largest single
gain. Synthea's disease model is coarse (no MCI, no amyloid), so treat these as a worked example, not prevalence.

## Data not used

- **n2c2 2018 Track 1 (cohort selection)**: 288 real discharge-summary records, 13 criteria. Needs a signed DUA on the
  DBMI portal (Harvard). Worth doing: it is the only public set with real longitudinal notes and per-criterion labels.
- **n2c2 2018 Track 1** (update): Changfu's Hugging Face bucket holds the BigBio loader only; `train.zip` and
  `n2c2-t1_gold_standard_test_data.zip` are still to be uploaded.
- **ADNI / J-ADNI**: the natural AD cohort (amyloid PET, CSF, MMSE, CDR over time). Needs an ADNI data-use
  application; J-ADNI through NBDC. Neither can be fetched from here.
- **MIMIC-IV notes**: credentialed PhysioNet access and CITI training.
- **CHIP-CTC** (Chinese criteria classification): a Hugging Face mirror exists, but the licence is unclear (CBLUE
  registration), so it was not used.
- **Japanese EHR notes**: none public. MedTxt is the closest; real admission notes need a partner site (Osaka).

## Reproduce

```bash
python -m tools.trec_ct_eval fetch && OPENROUTER_API_KEY=... python -m tools.trec_ct_eval run --models <m> [--variant negation]
python -m tools.trec_ct_eval score
python -m tools.medtxt_eval fetch && OPENROUTER_API_KEY=... python -m tools.medtxt_eval run --models <m> [--variant suspected]
python -m tools.medtxt_eval score
TB_ENV=TEST PYTHONPATH=libs:services:. python -m tools.hospital_sim scale --sizes 2000 10000 --trials GZQO
python -m tools.hospital_sim project --patients 50000 --trials-per-year 12
python -m tools.open_cohorts_eval fetch && OPENROUTER_API_KEY=... python -m tools.open_cohorts_eval run --cohort sigir --models <m>
python -m tools.chia_routes
OPENROUTER_API_KEY=... python -m tools.ad_eval trec --models <m> ; python -m tools.ad_eval ctgov --router openai/gpt-oss-120b
python -m tools.ad_eval score && python -m tools.open_cohorts_eval score && python -m tools.validation_figures
```
