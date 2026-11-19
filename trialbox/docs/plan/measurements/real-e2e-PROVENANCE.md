# Public-data site: what is real and what is derived

Built by `tools/public_site.py`. 268 patients, one per source document (SIGIR 53, MedTxt-CR 123, MedTxt-RR 92).

| What | Where it comes from |
| --- | --- |
| Note text (every word) | **Real.** SIGIR 2016 patient descriptions (CC BY-SA 4.0, Koopman and Zuccon, CSIRO; NCBI TrialGPT release; label corrected 2026-11-19, card 10H-1); NTCIR-16 Real-MedNLP MedTxt-CR case reports and MedTxt-RR radiology reports (CC BY 4.0, Sociocom NAIST) |
| Age | **Derived** from the text where stated (141 exact, 7 from a decade such as 60歳代 -> 65, 120 not stated -> no birth date) |
| Sex | **Derived** from the text where stated (149 of 268) |
| Diagnoses | **Derived** by a fixed EN/JA dictionary to ICD-10, skipping negated, family-history and suspected mentions (149 rows on 127 patients); rule-based, so it can miss or over-read a mention |
| Chart number, visit date, birth month, clinic staff, 89 next-visit appointments | **Placed** (not in the sources; the box needs them to run) |
| Names, ID numbers, phones, labs, medicines, contact consent | **None** (the sources do not give them; nothing is made up) |

## Derived diagnoses

| ICD-10 | Patients |
| --- | --- |
| C34.90 lung cancer | 44 |
| C80.1 malignancy, other site | 24 |
| C18.9 colorectal cancer | 11 |
| C16.9 gastric cancer | 9 |
| I10 hypertension | 8 |
| E11.9 type 2 diabetes | 8 |
| J18.9 pneumonia | 7 |
| E66.9 obesity | 6 |
| A15.9 tuberculosis | 6 |
| Z33.1 pregnancy | 5 |
| E78.5 hyperlipidaemia | 4 |
| J45.9 asthma | 4 |
| C22.0 hepatocellular carcinoma | 3 |
| C50.9 breast cancer | 2 |
| K85.90 pancreatitis | 2 |
| I21.9 myocardial infarction | 1 |
| I63.9 cerebral infarction | 1 |
| B18.2 chronic hepatitis C | 1 |
| I50.9 heart failure | 1 |
| B18.1 chronic hepatitis B | 1 |
| I48.9 atrial fibrillation | 1 |
