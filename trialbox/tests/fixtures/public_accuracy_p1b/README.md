# Launch P1b's answer key, a small slice (D-1104)

`jmed_key_slice.json` is taken from launch P1b's stored jmed set (run `box-20261116T074927Z-3b2f5e38`): for 13
patient x criterion rows, the label of key v1 as the run's `built/gold/criteria.jsonl` held it, the label key v2 gives
(`tools.public_accuracy.sets.jmed_stratum`), whether the box excluded the patient on that line in the run, and the
note's sentences that name diabetes (糖尿病) or hypertension (高血圧): the only sentences the truth is read from. The
sentences are the judge's excerpts of the run, which are the patient's whole note. The patient ids are the source's.

The patients are synthetic: JMED-Personas-100k by Sociocom (NAIST), `huggingface.co/datasets/sociocom/JMED-Personas`,
licensed CC BY 4.0. Keep this attribution with any copy. Used by `tests/unit/test_h2_answer_key_versions.py`.

## `replay_slice.json` (card H-4, D-1111)

A slice of the same run's stored sets for `tests/unit/test_h4_replay_2026_11_17.py`. It holds seven sigir protocols
and the two jmed protocols, over the patients their stored answers and gold rows name. For each, it keeps the gold
ids, pairs and criterion rows, the stored answers (state, error, draft, verdicts), the job ids, and the model calls
of those jobs (`raw-traces.json`: the user message and the reply only). Chart numbers are offsets from the set's
`site.SET_OFFSETS` and are made at run time. The pseudonyms are the box's. The jmed judge calls, which quote the
notes, are left out.

The sigir data is public: SIGIR 2016 (NCBI TrialGPT, `eval/criterion_ml/LICENSE.NCBI`), with protocol text from
ClinicalTrials.gov. The jmed patients are synthetic: JMED-Personas-100k by Sociocom (NAIST),
`huggingface.co/datasets/sociocom/JMED-Personas`, licensed CC BY 4.0. Keep both attributions with any copy.
