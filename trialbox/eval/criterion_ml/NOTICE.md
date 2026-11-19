# Attribution and licence notice for `eval/criterion_ml`

This folder holds material under two licences and one set of terms. Read 2026-11-18 (card H-37).

## SIGIR 2016 patient descriptions — CC BY-SA 4.0

- Files: `notes_en.json` (the 53 patient descriptions, split into sentences) and its adaptations `notes_zh-TW.json`,
  `notes_ja.json`, `notes_mixed.json`.
- Work: *A test collection for matching patients to clinical trials*, Bevan Koopman and Guido Zuccon, SIGIR 2016;
  published by CSIRO: https://researchdata.edu.au/a-test-collection-clinical-trials/664508
- Copyright notice as published: "All Rights (including copyright) CSIRO, U.S. National Institute of Standards,
  U.S. National Institutes of Health 2016."
- Citation as the publisher gives it (read 2026-11-19, card 10H-1): Koopman, Bevan; Zuccon, Guido (2017): A Test
  Collection for Matching Patient to Clinical Trials. v4. Commonwealth Scientific and Industrial Research
  Organisation. https://doi.org/10.4225/08/58e2e83d92c2b
- Licence: Creative Commons Attribution-ShareAlike 4.0 International, https://creativecommons.org/licenses/by-sa/4.0/
  (legal code: https://creativecommons.org/licenses/by-sa/4.0/legalcode). The material is provided as-is, without
  warranties, as the licence's Section 5 states.
- Obtained through the NCBI TrialGPT release (Hugging Face `ncbi/TrialGPT-Criterion-Annotations`, the `note` field).
- Changes made upstream, by NCBI's TrialGPT benchmark: every one of the 53 notes ends with a sentence NCBI added,
  "The patient will provide informed consent, and will comply with the trial protocol without any practical
  issues." It is not part of CSIRO's descriptions; it is kept because NCBI's evidence ids count it.
- Changes made by this project: `notes_en.json` stores each note (with NCBI's added sentence) as a list of
  sentences, in the numbering NCBI's evidence ids refer to; no other word is changed. `notes_ja.json`,
  `notes_zh-TW.json` and `notes_mixed.json` were translated by this project (machine translations, October 2026,
  sentence for sentence, not clinician-verified; `mixed` is a Taiwanese code-mixed rendering). These three files
  are adapted material, offered under CC BY-SA 4.0 with the attribution and copyright line above.

## TrialGPT criterion annotations — U.S. Government work (public domain notice)

- Files: `annotations.jsonl` (physician labels and evidence sentence ids, GPT-4 labels and sentences, the
  `training` flag).
- Source: NCBI / NLM, https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations; notice in `LICENSE.NCBI`.
- Cite: Jin Q, Wang Z, Floudas CS, et al. *Matching patients to clinical trials with large language models.*
  Nat Commun 15, 9074 (2024).

## Trial titles and criteria — ClinicalTrials.gov terms

- Fields `trial_title` and `criterion_text` of `annotations.jsonl`: text of ClinicalTrials.gov study records,
  unchanged, as NCBI published them. ClinicalTrials.gov (U.S. National Library of Medicine) terms:
  https://clinicaltrials.gov/about-site/terms-conditions. The eligibility text is the sponsors'; no rights are
  claimed in it.
