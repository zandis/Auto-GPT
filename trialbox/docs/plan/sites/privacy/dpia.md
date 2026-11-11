# Data-protection impact assessment (影響評価 / 個資影響評估)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-02 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| For | each hospital's privacy office; the IRB pack (TB-PRV-04) |
| Status | Draft. Risks are rated on the processing of TB-PRV-01 as built on master. The hospital's privacy office adds its own rating on its copy; none is on file and none is waited for (D-311). |
| Method | for each processing step: what could harm a patient, how likely, how bad, the control in the box, the residual risk. Likelihood and impact are low, medium or high. |

## 1. Risks and controls

| Id | Risk to the patient | Steps | Likelihood | Impact | Controls in the box (where) | Residual |
| --- | --- | --- | --- | --- | --- | --- |
| DP-01 | a patient list reaches a person outside the study team | P-04, P-09 | medium | high | mail by link after sign-in, not attachment (D-369); routing check before every send (`libs/tb_common/routing.py`); internal domains only; the export ledger | low |
| DP-02 | identified data leaves the hospital | P-01 to P-13 | low | high | no remote access by design; data-handling rule; the support bundle is scrubbed and scanned (D-405); local models only for patient data | low |
| DP-03 | a chart number is revealed without need | P-05 | medium | medium | reveal only for roles with reveal rights for the study; every reveal audited; the IRB-text gate on cross-department views (D-395); a cap on exports with chart numbers | low |
| DP-04 | a model output is wrong and a person acts on it | P-02, P-04, P-06 | medium | medium | every output cites its passage; a qualified person decides; two models must agree before a note counts against a criterion (D-115, D-117); the intended-use statement on every page and report | medium |
| DP-05 | planted text in a note steers the model | P-02 | low | medium | the injection suite in CI and in `qualify` (D-346); fenced data blocks; invisible text flagged | low |
| DP-06 | an opted-out patient still appears | P-02 to P-06 | medium | medium | the opt-out register (R-06); the worker of T-206a and T-206b is not on master yet, so the notice is not published until it passes (TB-PRV-05) | medium until T-206 lands |
| DP-07 | the box or a disk is lost | all | low | high | site keys under the KEK, which is not on the disk (D-347); encrypted backups to a key the box does not hold (D-126); the lost-box list (RUNBOOK §23) | medium until disk encryption (T-408) |
| DP-08 | an account is taken over | all | medium | high | second factor on every sign-in route; lockout; password history; sign-in events audited | low |
| DP-09 | data kept longer than needed | P-01 to P-11 | medium | low | retention per data kind (SECURITY §6); every deletion audited; destruction procedure TB-PRV-08 | low |
| DP-10 | the vendor sees patient data during support | P-12 | low | high | the supervised remote session rules (RUNBOOK §21); the support bundle holds no patient data | low |

## 2. The four items the card names

| Item | State on master | Risk | What must hold before it is turned on |
| --- | --- | --- | --- |
| Patient profiles (a longitudinal summary per patient) | not built (the profile stack of wave 3) | a profile gathers more about one patient than any single list; it is read again across studies | the profile is D3, built only for patients in an open study's candidate set; every view audited as a reveal of content; kept no longer than the study's candidate lists; this DPIA re-rated |
| The vector store of note passages | not built (T-203a) | embeddings of note text are D3: they can leak words; a nearest-neighbour search can single out a patient | the vectors live on the box only, in the same database as the notes; deleted with the note and on opt-out; never exported (TB-PLAN-05 §9.3, the consortium floor: "no vectors"); a "patients like this one" page only for roles with reveal rights |
| The clinician role (a treating physician who is not on the study team) | not built (T-314) | a clinician sees research lists about their own patients | the clinician sees only their own patients the PI has referred, never a list across patients; no verdict words (TB-IU-01 §2) |
| The steward's access to every note | built: the steward role reads notes to check mapping and conflicts | one role reads all notes of all patients | the steward is named by the hospital, holds no study role, and every note view is audited; the privacy office reads the steward's audit monthly |

## 3. Japan head hospital (the hospital fills)

| Item | Value |
| --- | --- |
| Does the hospital count as an academic research body under APPI (changes the exception used)? | |
| Privacy office rating of DP-01 to DP-10 | |
| Date | |

## 4. CGMH (the hospital fills)

| Item | Value |
| --- | --- |
| Platform risks the hospital adds for the shared B200 server (other tenants, platform administrators) | |
| Privacy office rating of DP-01 to DP-10 | |
| Date | |
