# D-1242 The feasibility page states the box's ClinicalTrials.gov mode instead of "no connection" (10D-17)

- **Task:** lane J, plan 10 row 10D-17 (review 14, item M14-16; `docs/plan/47-plan-10-2026-11-18.md`): the page that
  says "no registry connection" states the box's mode, in three languages. Exit: a text test per mode. PR #1156.
  · **Date:** 2026-11-19
- **What was wrong:** with no competing trials entered, section 9 of the feasibility report said "TrialBox has no
  jRCT or ClinicalTrials.gov connection; the coordinator types them" (`feas.ct.none`, en, ja, zh-TW). That is untrue
  on a box whose ClinicalTrials.gov mode is `live` (the criteria compiler searches clinicaltrials.gov) and misleading
  on an `offline` box (it holds ClinicalTrials.gov records from the signed update). It is the only console text that
  speaks of a registry connection.
- **Decision:**
  - **The mode is the one the box already has**: `TB_CTGOV_MODE`, `live`, `offline` or `cassette`
    (`services/criteria_compiler/ctgov.py`, D-140), unset read as `offline`, as the compiler reads it. No mode is
    added. A value the compiler refuses reads as `unknown`, and the page then says the setting is not one of the
    three and sends the reader to the administrator; it never guesses a mode.
  - **One sentence per mode, in en, ja and zh-TW** (`feas.ct.none.live`, `.offline`, `.cassette`, `.unknown`;
    `feas.ct.none` is removed). Each says what this box reaches: live, clinicaltrials.gov, no jRCT; offline and
    cassette, neither, by design, and "nothing is wrong". It also says where the box's ClinicalTrials.gov records come
    from (offline: the reference data in each signed update; cassette: synthetic records shipped with the software,
    a demonstration or test box). Every mode keeps the fact that matters for the list: no registry fills it, and the
    coordinator types the trials.
  - **No new read, route or reader.** The console takes the value from its environment, where `deploy/.env` already
    put it through `env_file`. `deploy/docker-compose.yml` now also gives the console `TB_CTGOV_MODE` from the same
    expression as the criteria compiler (`${TB_CTGOV_MODE:-offline}`), so the two services cannot differ. The page,
    its route, who may open it and the sponsor copy are unchanged, apart from this sentence (the sponsor copy shows the
    same sentence it showed before, now true).
  - **Nothing else depends on the mode.** The home page, the reports page and the feasibility page in both views
    render the same bytes in every mode, apart from the one sentence.
- **Held by:** `tests/console/test_ctgov_mode_text.py` (one text test per mode per language, the unknown value, the
  console's modes equal to the compiler's, the compose value shared with the compiler, and the render check).
