# Multilingual criterion-judging set (`judge_ml` seed)

This is the evaluation set for TrialBox's S3 judge task: one patient note plus one eligibility criterion gives a label
and the evidence sentences. `python -m tools.mlbench` runs it against any OpenAI-compatible endpoint.

## Files

| File | Content |
| --- | --- |
| `annotations.jsonl` | 1,015 patient–criterion pairs: 53 SIGIR patients, 103 trials, 356 inclusion and 659 exclusion criteria. Each pair has the physician label (`expert_eligibility`), the physician's evidence sentence ids, the published GPT-4 label and sentences, and NCBI's `training` flag. |
| `notes_en.json` | The 53 notes, as lists of sentences (English original). |
| `notes_zh-TW.json` | The same notes in Traditional Chinese (Taiwan usage). |
| `notes_ja.json` | The same notes in Japanese clinical register. |
| `notes_mixed.json` | The same notes in Taiwanese code-mixed EMR style: Chinese narrative with English terms and abbreviations (`s/p`, `r/o`, `denied`, `PE:`, `Lab:`). |

Every translation keeps the sentence count and order of the English note, so the physicians' evidence ids hold in all four
languages. Checks run at creation:
- the keys match;
- the sentence counts match (326 sentences in each language);
- every number is preserved;
- no Simplified characters appear in zh-TW or mixed.

Criteria stay in English, the way protocols arrive.

## Provenance and licence

The set has four parts, and they do not share one licence (sources read 2026-11-18; card H-37,
`docs/plan/measurements/eval-licence-labels-2026-11-18.md`):

| Part | Files | Licence | Where the source states it |
| --- | --- | --- | --- |
| Patient notes (53 SIGIR 2016 topics, English) | `notes_en.json` | **CC BY-SA 4.0**; "All Rights (including copyright) CSIRO, U.S. National Institute of Standards, U.S. National Institutes of Health 2016" | Koopman B., Zuccon G., *A test collection for matching patients to clinical trials*, SIGIR 2016, CSIRO: https://researchdata.edu.au/a-test-collection-clinical-trials/664508 |
| Translations of those notes, made for TrialBox | `notes_zh-TW.json`, `notes_ja.json`, `notes_mixed.json` | **CC BY-SA 4.0** (adaptations of the notes; share-alike binds them) | as above; licence text https://creativecommons.org/licenses/by-sa/4.0/ |
| Criterion labels, evidence ids, GPT-4 labels, `training` flag | `annotations.jsonl` (fields other than the trial text) | U.S. Government work, public domain notice (NCBI), `LICENSE.NCBI` | https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations (`license_name: public-domain`, LICENSE = the NCBI notice) |
| Trial titles and criterion text | `annotations.jsonl` (`trial_title`, `criterion_text`) | ClinicalTrials.gov terms and conditions; the text is the sponsors', unchanged | https://clinicaltrials.gov/about-site/terms-conditions |

NCBI's release puts the public domain notice of `LICENSE.NCBI` over the file, but NCBI redistributes text that CSIRO
publishes under CC BY-SA 4.0; this repository follows the original publisher's licence for the notes, as the licence register
(`docs/licences/register.csv`, rows `pubacc-sigir-2016` and `pubacc-trialgpt-criterion`) and `NOTICE` section 4
already do. The attribution and the statement of changes are in `NOTICE.md` in this folder. Please cite: Jin Q, Wang Z,
Floudas CS, et al. *Matching patients to clinical trials with large language models.* Nat Commun 15, 9074 (2024); and
Koopman B, Zuccon G. *A test collection for matching patients to clinical trials.* SIGIR 2016.

The zh-TW, ja and mixed notes are machine translations made for TrialBox (Oct 2026) and checked by the counts above. They
are **not** clinician-verified, so use them for model comparison and parity checks, not as clinical ground truth. A clinician review of all 326 sentences per language is required before these sets gate anything (SPEC_v4 §16.5, §16.8).

## The `training` flag

The flag is not a held-out split. In 129 of its 134 `False` rows, GPT-4's label differs from the physician's, and in
all 881 `True` rows the two agree. It is best read as "GPT-4 needed correction", so `mlbench` reports those pairs as a
**hard slice** and does not use the flag for sampling.

## Reference: GPT-4 against the physicians

GPT-4's labels as published, scored with `mlbench` on all 1,015 pairs:

| Metric | Value |
| --- | --- |
| Accuracy | 0.873 (the paper reports 87.3 % criterion-level accuracy) |
| False-block rate | 0.014; Clopper–Pearson 95 % upper bound 0.022 |
| Patient × trial false exclusion | 0.101 (8 of 79 patient–trial pairs that the physician left open); 95 % upper bound 0.175 |

The last row is the patient × trial view: the physician blocks none of the evaluated criteria, but the model blocks at
least one. Even a 1.4 % per-criterion false-block rate loses about 1 in 10 eligible patient–trial pairs, because a trial
has many criteria. This is why TrialBox certifies recall (SPEC §6.14) rather than quoting criterion accuracy.

## Labels

Inclusion criteria use `included`, `not included`, `not enough information` and `not applicable`. Exclusion criteria
use `excluded`, `not excluded`, `not enough information` and `not applicable`.

For screening, `not included` and `excluded` *block* the patient. A model that blocks when the physician did not has
silently lost an eligible patient; `mlbench` reports this as the false-block rate.
