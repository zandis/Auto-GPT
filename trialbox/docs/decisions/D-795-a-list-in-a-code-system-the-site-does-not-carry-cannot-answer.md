# D-795 A list in a code system the site does not carry cannot answer

- **Task:** F11 of the first look at a real site export (#639, 2026-11-15); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** once per run the runtime reads which code systems each domain's rows carry (`matching.carried`). A coded atom whose value set has none of them makes the answer it could change unknown, reason `code_system_not_carried`: an inclusion's or exclusion's FALSE that a record would make TRUE, a TRUE that a record would make FALSE ("none"). It runs on the cascade (S1) and on the SQL engine of NAV / MICROBATCH / CASE. An exclusion left unknown keeps the patient (D-18). The approved SQL is unchanged (as D-130).
- **Not here:** drugs from NHI claim lines through the NHI-to-ATC map (D-689 maps medication rows; claim lines are the mapping's, lane E); WHO ICD-10 lists against ICD-10-CM rows by prefix (a compiler change, so the approved rulesets would be recompiled); FEAS counts.
- **Test:** `tests/unit/test_system_not_carried.py`.
