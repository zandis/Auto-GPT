# D-980 The screen report names the model that answered, and its language field says what it is

- **Task:** G12 of the integrator's second review of the P1b run (#639, 2026-11-16).
  - The SCREEN report named the judge by the configured default (`config.py`), not the model that answered.
  - Every screen JSON said `language: zh-TW` for English and Japanese notes.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision**
  - **The model that answered.** The note judge keeps the names each model answered under, for the judge and the verifier (`NoteJudge.served`). The run's `judging` record names the one that served most, on the v1 path (`judging_info`) and the cascade's. With no answer yet it names the configured model, as before.
  - **The language field, as the integrator decided.** `provenance.language` is the report's language: the site's report language, which the console asks for as "Language of reports". The schema now says so (`feasibility_result.schema.json`), and its value is unchanged.
- **Not in this card.** Two things go to NOTE-LANGUAGE-THRESHOLDS, which the integrator ranked next; the owner confirmed charts are mainly English at a zh-TW site:
  - the language of the notes that were read;
  - the cascade's use of the site locale for its S2 thresholds (`engine.py`).
- **Test:** `tests/unit/test_report_names_what_served.py`.
