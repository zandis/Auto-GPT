| stage | check | result | detail |
| --- | --- | --- | --- |
| 0 public data in | every source document is one patient (SIGIR 53, MedTxt-CR 123, MedTxt-RR 92) | pass |  |
| 0 public data in | ingest passed | pass |  |
| 0 public data in | lake counts = CSV counts (patients, notes, diagnoses) | pass |  |
| 0 public data in | note text reaches the lake verbatim | pass |  |
| 0 public data in | no chart number column in the lake | pass |  |
| 0 public data in | lake keys are pseudonyms | pass |  |
| 0 public data in | missing birth dates reported, not invented | pass |  |
| 1 criteria, approval and feasibility | S2 paste PUB-CA -> draft waiting for approval | pass |  |
| 1 criteria, approval and feasibility | S2 paste PUB-ONC -> draft waiting for approval | pass |  |
| 1 criteria, approval and feasibility | coordinator ticks a criterion's codes on S20 | pass |  |
| 1 criteria, approval and feasibility | coordinator's approve refused (403) | pass |  |
| 1 criteria, approval and feasibility | S20: criterion labels in Japanese and Chinese saved | pass |  |
| 1 criteria, approval and feasibility | investigator approves PUB-CA; FEAS finishes | pass |  |
| 1 criteria, approval and feasibility | investigator approves PUB-ONC; FEAS finishes | pass |  |
| 1 criteria, approval and feasibility | FEAS PDF, XLSX and JSON | pass |  |
| 1 criteria, approval and feasibility | start = every patient | pass |  |
| 1 criteria, approval and feasibility | age >= 18 = recount from patient.csv | pass |  |
| 1 criteria, approval and feasibility | malignancy = every adult with a cancer code in diagnosis.csv (recount by ICD-10 family, not by the list) | pass |  |
| 1 criteria, approval and feasibility | every cancer code in the data is in the malignancy value set | pass |  |
| 1 criteria, approval and feasibility | funnel never grows | pass |  |
| 1 criteria, approval and feasibility | FEAS ran without a model | pass |  |
| 1 criteria, approval and feasibility | S3 feasibility page | pass |  |
| 1 criteria, approval and feasibility | S3 Refresh re-runs FEAS | pass |  |
| 2 screening (patient list) on real notes | SCREEN PUB-ONC done | pass |  |
| 2 screening (patient list) on real notes | SCREEN PUB-CA done | pass |  |
| 2 screening (patient list) on real notes | screen funnel S0 >= S1 >= S3 >= S4 | pass |  |
| 2 screening (patient list) on real notes | listed = high + review | pass |  |
| 2 screening (patient list) on real notes | note-based exclusion only when two models agree | pass |  |
| 2 screening (patient list) on real notes | cohort list PUB-CA has members, no contact step | pass |  |
| 3 list, S5 and marks | the list has at least three patients | pass |  |
| 3 list, S5 and marks | PI list page | pass |  |
| 3 list, S5 and marks | mark approach | pass |  |
| 3 list, S5 and marks | mark need_info | pass |  |
| 3 list, S5 and marks | mark not_now | pass |  |
| 3 list, S5 and marks | replace a mark: history keeps both | pass |  |
| 3 list, S5 and marks | withdraw a mark | pass |  |
| 3 list, S5 and marks | S5 patient page | pass |  |
| 3 list, S5 and marks | coordinator records a contact outcome | pass |  |
| 3 list, S5 and marks | Approach gives a screening number | pass |  |
| 3 list, S5 and marks | screening log lists the approached patient | pass |  |
| 3 list, S5 and marks | screening log XLSX opens | pass |  |
| 4 N1 / N2 mail | N1 and N2 sent | pass |  |
| 4 N1 / N2 mail | mail carries no chart number | pass |  |
| 4 N1 / N2 mail | mail carries no screening number | pass |  |
| 5 REDCap simulator read-back | S36 Test connection (version shown, token never shown) | pass |  |
| 5 REDCap simulator read-back | S21 project link checked against the data dictionary | pass |  |
| 5 REDCap simulator read-back | Run now: consented | pass |  |
| 5 REDCap simulator read-back | Run now: enrolled, subject number shown | pass |  |
| 6 other screens | crc /home | pass |  |
| 6 other screens | crc /week | pass |  |
| 6 other screens | crc /account | pass |  |
| 6 other screens | crc /help | pass |  |
| 6 other screens | crc /notices/received | pass |  |
| 6 other screens | crc /reports | pass |  |
| 6 other screens | crc /settings/notices | pass |  |
| 6 other screens | pi /home | pass |  |
| 6 other screens | pi /week | pass |  |
| 6 other screens | pi /account | pass |  |
| 6 other screens | pi /help | pass |  |
| 6 other screens | pi /notices/received | pass |  |
| 6 other screens | pi /reports | pass |  |
| 6 other screens | pi /settings/notices | pass |  |
| 6 other screens | admin /home | pass |  |
| 6 other screens | admin /week | pass |  |
| 6 other screens | admin /account | pass |  |
| 6 other screens | admin /help | pass |  |
| 6 other screens | admin /notices/received | pass |  |
| 6 other screens | admin /reports | pass |  |
| 6 other screens | admin /settings/notices | pass |  |
| 6 other screens | banner says public data | pass |  |
| 6 other screens | request menu: this site's studies only | pass |  |
| 6 other screens | clinician names from the records | pass |  |
| 6 other screens | research-office counts | pass |  |
| 6 other screens | research-office XLSX | pass |  |
| 6 other screens | command field: 'PUB-ONC' | pass |  |
| 6 other screens | command field: '69390044' | pass |  |
| 6 other screens | command field: 'help' | pass |  |
| 6 other screens | admin /admin | pass |  |
| 6 other screens | admin /admin?tab=health | pass |  |
| 6 other screens | admin /admin?tab=jobs | pass |  |
| 6 other screens | admin /admin?tab=sources | pass |  |
| 6 other screens | admin /ops/users | pass |  |
| 6 other screens | admin /audit | pass |  |
| 6 other screens | admin /jobs | pass |  |
| 6 other screens | investigator cannot open admin | pass |  |
| 6 other screens | 404 page | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | download XLSX feasibility report | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | download PDF feasibility report | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | download XLSX feasibility report | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | cohort registry export XLSX | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | CASE on a real case report finishes | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | consent explainer draft (ICF upload, EN + JA) | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | Cancel asks to confirm | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | Cancel a waiting job (failed, step cancelled) | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | Retry a failed job creates a new one | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | Retry of a finished job is refused (409) | pass |  |
| 7 exports, CASE, consent explainer, Cancel / Retry | Cancel of a finished job is refused (409) | pass |  |
| 8 audit chain | audit chain verifies | pass |  |