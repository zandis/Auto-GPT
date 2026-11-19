# Every accuracy report names its gold kind (2026-11-19)

**Reader:** the people who build TrialBox: lane H, whoever writes or reads an accuracy report, and the integrator.
For builders, so in one language.

Plan 10 row 10G-38 (review 20, item 20-15), decision D-1326. No findings.

## What changed

`tools/gold_kind.py` holds the five kinds (`physician`, `generated and checked`, `translated`, `structured truth`,
`enrolment`), the kind of each set the repository's documents state, and the pooling rule: a figure over more than
one part needs one stated kind, or it is refused with a message naming each part and its kind. The accuracy report
writers now write `gold_kind`:

| Report | Where the field is |
| --- | --- |
| `tools/public_accuracy` `score.json` | top level, per set |
| `tools/public_accuracy/replay.py` target 1 | each set in `per_set`; the pooled figure is refused across kinds (`pooled_refused`, `by_gold_kind`) |
| `tools/medtxt_eval.py` `scores.json` | each `single` and `both_must_block` row (its language) |
| `tools/open_cohorts_eval.py` `scores.json` | each cohort |
| `tools/trec_ct_eval.py` `scores.json`, `tools/ad_eval.py` (`trec`) | top level / the TREC part |
| `tools/accuracy_set.py` report | top level |

Stored reports (on master and on artefact branches) are not rewritten. A report without the field is read as
`not stated` (`gold_kind.read`) and is never pooled with anything.

## The kind of each set, and its source

| Set | Gold kind | Source |
| --- | --- | --- |
| MedTxt, ja | physician | review 20 §7.1 ("clinician annotation (published)") |
| MedTxt, en | translated | `eval/medtxt/README.md` (clinician-made English translations); `tools/medtxt_eval.py` (the label is the Japanese annotation's) |
| criterion_ml, en | physician | review 20 §7.1 ("physician labels, translated notes"); `eval/criterion_ml/README.md` (`expert_eligibility`) |
| criterion_ml, ja / zh-TW / mixed | translated | the same; review 20 §1 ("not clinician-checked translations") |
| SIGIR (public_accuracy `sigir`, open_cohorts `sigir`) | physician | `eval/public_accuracy_key/README.md` ("the same physicians' criterion labels"); review 20 §7.6 |
| JMED-Personas (`jmed`) | structured truth | review 20 §7.1 |
| generated charts (stage G3), enrolment logs and shadow mode (G4) | generated and checked; enrolment | review 20 §7.1; no such set in the repository yet |

## Open questions (not stated in the repository: written as None, read as "not stated", never pooled)

1. TREC CT 2021 to 2023 (`trec`, `trec2023`, `eval/trec_ct`, `tools/ad_eval.py`): who made the NIST relevance
   judgements is not stated in the repository (review 20 §1 records only "pair relevance 0/1/2"). Physician?
2. TCGA (`tcga`): the gold is the cancer type of the GDC project. Structured truth?
3. `eval/accuracy` (`tools/accuracy_set.py`): gold planted by templates written for TrialBox, not stated as checked.
   Generated and checked, or none of the five?
4. Chia, TFDA, jRCT and the notes-only sets (`aci`, `maccrobat`, `opentw`, `pmc_zh`): compile agreement or no gold
   at all; review 20 §7.1 calls the TFDA and jRCT check "the regulator's own wording". Out of the five, or a kind?
5. The open_cohorts `sigir` cohort is the same SIGIR 2016 collection as public_accuracy's `sigir` (both the NCBI
   TrialGPT copy); it is given the same kind. Confirm.
