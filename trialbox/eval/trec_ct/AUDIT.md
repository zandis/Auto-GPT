# TREC CT: hand check of 30 eligible pairs the model pair dropped

Pair: Gemma 4 26B 4-bit (`google/gemma-4-26b-a4b-it@fp4`) + Qwen3.5-9B, both must block (the one-RTX-5090 pair).
On TREC CT 2021/22 it dropped 232 of 1,200 NIST-"eligible" pairs (19.3 %), through 306 blocking criteria. One
blocking criterion was drawn at random from each of 30 distinct dropped pairs (seed 11, `tools/trec_ct_eval.py`
data) and read against the topic by Claude, 2026-11-05. Not a clinician review.

| verdict | count | what it means |
| --- | --- | --- |
| model error | 10 | the criterion does not block this patient |
| label noise | 12 | the criterion clearly blocks (e.g. "Male veterans" for a 47-year-old woman), NIST said eligible |
| multi-cohort trial | 5 | the criterion belongs to another arm (healthy controls) but is parsed as applying to everyone |
| ambiguous | 3 | reasonable readers could differ ("and/or" scores, dehydration grade) |

So about a third of the measured loss is the model (10/30, Wilson 95 % 19-51 %). Applied to the 19.3 %: roughly
**6.4 % of truly eligible pairs lost to model errors (95 % about 3.7-9.9 %)**, 7.4 % with the ambiguous ones.
TREC "eligible" labels are not clean enough to quote the raw 19.3 % as an error rate.

The 10 model errors fall into three patterns that a prompt or the IR can fix:

| pattern | n | examples |
| --- | --- | --- |
| negated exclusion read as the condition itself | 5 | "Exclusion: No evidence of pituitary adenoma on MRI" (patient has a macroadenoma); "Negative C. difficile test within 10 days" (patient tested positive); "Patients with no cardiovascular events"; "never treated" (patient on octreotide); "MG diagnosis < 2 months, no prior antimyasthenic medication" (patient on pyridostigmine) |
| "other" than the index condition | 2 | "any other haematological malignancy" for a Burkitt lymphoma patient in a Burkitt trial; "other congenital coagulation disorders" for a haemophilia A patient |
| blocked with no evidence, or wrong sub-type | 3 | "3 or more facial inflammatory lesions of rosacea" (not stated); antidepressant use (not stated); "uncomplicated biliary colic" for gallstone pancreatitis |

Fixes proposed (not yet built): rewrite negated exclusions into positive form at protocol import (`ir_extract`),
so the judge never sees "Exclusion: No X"; pass the trial's index condition to the judge so "other X" excludes only
the others; parse arm headings ("Healthy control subjects:") so arm-specific criteria are not applied to patients.

Separately, the deterministic age/sex check first blocked 25 NIST-eligible pairs. Two were neonatal trials whose age
fields hold gestational age (the filter now leaves weeks-based limits to the reader, 23 remain); the rest are label
noise (e.g. a 34-year-old man "eligible" for a 4-21-year trial).
