# D-914 A record that is not there never excludes

- **Task:** red of lane G's frozen-commit run (#639, #649, 2026-11-16: on trec2023 all 16 exclusions came from coded criteria, 10 wrong); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - **Cause of nine of the ten:** the patients had no coded row at all (their facts are a questionnaire in a note), so a coded inclusion read FALSE and excluded them. They were not age or sex answers; lane G's earlier reading was corrected on #649.
  - **The per-patient rule:** the runtime reads, once a run, which kinds of record each patient has (`matching.recorded`). For a patient with no row of an atom's kind at all, an excluding answer that atom could have changed reads unknown, with the reason `no_record_of_kind` (en, ja, zh-TW). That is an inclusion's FALSE where a record would make the atom truer, and an exclusion's TRUE where a record would make it falser ("none", e.g. "IGRA positive and not on prophylaxis").
  - **Unchanged:** an answer that keeps the patient stands, so no review is added; the study's own condition keeps its scope rule.
  - It applies on the cascade's S1 and on the SQL engine (NAV, MICROBATCH, CASE). It is D-795 per patient, on the excluding side only.
  - **The tenth:** "within 3 months" compiled as a duration of at least −90 days, met by everyone. A duration of 0 days or less, an age below 0 and a reversed age range are now compile errors, so such a criterion goes to a person (`demote_uncompilable`).
  - **Already true, now tested:** a missing birth date or sex reads unknown.
  - **Goldens:** regenerated from both lake sources. Inclusions' not-met move to unknown for patients with no record of the kind. Two RA-BIO exclusions ("positive and not on prophylaxis") move from met to unknown where no medication is recorded. Some lists gain candidates.
- **Test:** `tests/unit/test_no_record_of_kind.py`.
