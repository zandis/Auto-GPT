# Alzheimer's slice: spot check of dropped eligible pairs (RTX 5090 pair, judge v3)

AD/dementia/MCI trials of the TREC 2021/22 corpora crossed with the NIST-judged patients: 150 eligible and 65 excluded
pairs, 121 of the eligible ones for topic 2022-50 (a 70-year-old man with NIA-AA Alzheimer's dementia, MRI
hippocampal atrophy, father with AD). The one-5090 pair dropped 46 eligible pairs (30.7 %), 36 of them for topic
2022-50. 15 dropped pairs drawn at random (seed 1) and read by hand:

| Verdict | n | Examples |
|---|---|---|
| Model right, label wrong | 7 | MCI-only trials ("Diagnosis of MCI", "not reaching the level of dementia") for a patient with dementia (3); frontotemporal dementia trial; "dementia onset before 65" for onset at about 70; preclinical trial ("a diagnosis of AD cannot be made"); "persistent hypercortisolism" |
| Criterion of another arm | 5 | "controls: MMSE >= 27", "cohort 2: older adults who test normally", "adults without family history of AD", "cognitively normal controls", an MCI-arm line parsed under exclusion |
| Unclear or model error | 3 | ALS exclusion, gait-disorder exclusion, NIA-AA inclusion for topic 2021-75 |

At most 3 of 15 (20 %, Wilson 7-45 %) are model errors, so the true loss is **about 6 %** as in the other cohorts.
For an AD trial-ready cohort the lesson is the disease stage: NIST often marks a dementia patient "eligible" for an
MCI or preclinical trial, and the models are right to block it. Stage (preclinical / MCI / mild / moderate) and
study arm must be explicit fields of the protocol rules, not free text.
