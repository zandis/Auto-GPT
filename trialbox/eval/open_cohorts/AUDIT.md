# TREC CT 2023: spot check of dropped eligible pairs (RTX 5090 pair, judge v3)

The one-5090 pair (Gemma 4 26B 4-bit + Qwen3.5-9B, both must block) dropped 211 of 600 NIST-eligible pairs (35.2 %).
TREC 2023 topics are structured questionnaires, and its "eligible" label is looser than 2021/22 (the patient often
fails a written criterion). 12 dropped pairs drawn at random (seed 2) and read by hand:

| Verdict | n | Examples |
|---|---|---|
| Model right, label wrong | 7 | "Primary open angle glaucoma" for uveitic glaucoma (2); "Age 18-29" for a 39-year-old; "history of ketoacidosis" with ketoacidosis history yes; DMARDs within 3 months while on hydroxychloroquine; "not requiring ICU" for a ventilated patient; inclusion "stroke within 2 years" with stroke history never |
| Criterion of another arm | 3 | "Healthy control"; "Donor has Hgb SS"; healthy close contacts of COVID-19 cases |
| Model error | 2 | "No prior history of cancer" / "history of cancer other than..." applied to the breast cancer the trial is for (the same "other X vs index condition" pattern as eval/trec_ct/AUDIT.md) |

Model errors are 2 of 12 (17 %, Wilson 5-45 %), so the true loss is about 35.2 % x 0.17 = **about 6 %**, the same as
the 2021/22 audit (10 of 30). Small sample: treat as indicative.
