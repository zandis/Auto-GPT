# D-917 A condition recorded as resolved never meets an "active" criterion

- **Task:** lane G's scorer review, point 4 (#639, 2026-11-15): SCREEN's compiled SQL read condition rows whatever their clinical status. A resolved cancer therefore still answered an "active malignancy" exclusion TRUE. Placed with lane A2 (backlog of 2026-11-16). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **The IR.** A condition atom may carry `clinical_status`: a non-empty list of FHIR `Condition.clinicalStatus` codes that count (`active`, `recurrence`, `relapse`, `inactive`, `remission`, `resolved`). It is refused on any other domain. It is in the v1 schema (the runtime IR) and in IR 3, and it survives the v1↔v3 round trip.
  - **What counts.** In the atom's window, a row counts as it always did when its status is listed or not recorded. The lake keeps the first coded `clinicalStatus` in `condition.status`, and most hospital sources record none.
  - **What does not count.** A row recorded with another status (resolved, inactive, in remission) cannot settle the atom, the same way an undated row cannot. Where nothing else settles the atom, the answer is unknown, with the reason `condition_not_active` (en, ja, zh-TW), and a person looks.
    - So an "active" exclusion never excludes on a cured condition.
    - An "active" inclusion is never met by one.
    - Neither ever becomes a silent FALSE.
    - A count threshold that the status-blind rows could not reach stays FALSE, as before.
  - **SQL and CQL say the same.** The runtime SQL adds an `<atom>_st` CTE of the other-status rows. The approval's CQL adds an `S_<atom>` definition and reads the status the way the lake does (the first coded `clinicalStatus`, lower case). The test runs both on the same patients, through the local CQL engine.
  - **Who sets it.** `postprocess`, when the criterion's line says the condition is active or current and does not say it is past:
    - active words: active, current, currently, ongoing, 活動性, 活動期, 現在, 治療中, 進行中, 目前, 現患;
    - past words: history, previous, prior, past, former, ever, 既往, 過去, 以前, 病史, 曾.

    The criterion is flagged `clinical_status_from_text` with a warning, so the reviewer sees it. A wrong match costs a review, never an answer, because the rule only ever turns a status-blind TRUE or FALSE into unknown. "History of X" keeps every row.
  - **Nothing shipped changes.** Shipped rulesets keep their approved IR, and none carries the field. Their SQL and CQL are byte for byte what they were (`build_rulesets --check`: equal), and so are the goldens. A protocol compiled from now on gets the field where its line says so. RA-BIO's "一年內有活動性結核病" would get it on a recompile, which needs the owner's re-approval and is not part of this card.
- **Test:** `tests/unit/test_clinical_status.py`.
