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
   all 16 invariant checks at 2,000 and 10,000 synthetic patients and runs in about 32 ms per patient. The in-process
   test harness ran out of memory at 50,000 patients (13.5 GB on a 16 GB box); see "Hospital-scale simulation".
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

SCALE_TABLE

Every run passed all 16 invariant checks (published, no blocking data-quality defect, lineage complete, monotone
funnel, cascade equals the v1 funnel, small cells suppressed, reproducible, and the rest). Time grows linearly.
The 50,000-patient run was killed at 13.5 GB resident on this 16 GB container: the test harness keeps the whole
lake, traces and pack in one process. That is a harness limit, not the deployed stack (separate lake and services),
but the per-patient memory of the cascade and pack should be measured on the real box before a 50k-patient site;
added to the follow-ups.

### Projected: a 50,000-patient hospital, 12 trials a year

`python -m tools.hospital_sim project --patients 50000 --trials-per-year 12` combines the measured funnel with the
TREC error rates (bootstrap over TREC patients) and the audit share (Beta(11, 21)). Planning constants are
parameters: 2 truly eligible patients per 1,000 per trial, LLM reads 42 % of criteria, 10 minutes per review,
2,500 tokens/s on the box.

PROJECT_TABLE

The review queue is the cost that matters, and its size here comes from the synthetic generator, which plants many
borderline patients on purpose; a real site's funnel replaces it after the first FEAS run.

## Data not used

- **n2c2 2018 Track 1 (cohort selection)**: 288 real discharge-summary records, 13 criteria. Needs a signed DUA on the
  DBMI portal (Harvard). Worth doing: it is the only public set with real longitudinal notes and per-criterion labels.
- **Synthea**: the spec's 300k scale population. Downloading and running the Synthea jar was blocked in this cloud
  session; the in-repo generator stands in. Running it on the Spark or a Docker host needs a yes from Changfu.
- **Japanese EHR notes**: none public. MedTxt is the closest; real admission notes need a partner site (Osaka).

## Reproduce

```bash
python -m tools.trec_ct_eval fetch && OPENROUTER_API_KEY=... python -m tools.trec_ct_eval run --models <m> [--variant negation]
python -m tools.trec_ct_eval score
python -m tools.medtxt_eval fetch && OPENROUTER_API_KEY=... python -m tools.medtxt_eval run --models <m> [--variant suspected]
python -m tools.medtxt_eval score
TB_ENV=TEST PYTHONPATH=libs:services:. python -m tools.hospital_sim scale --sizes 2000 10000 --trials GZQO
python -m tools.hospital_sim project --patients 50000 --trials-per-year 12
```
