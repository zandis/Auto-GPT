# D-1367 The ClinicalTrials.gov intake reads sites, secondary ids, arms, outcomes and design; it stores no names (10D-15)

- **Task:** lane K, plan 10 row 10D-15 (review 14, card M14-14: "CT.gov intake widened: locations with status,
  secondary ids, arms, outcomes, design"; §5.2 of the review: TrialBox read 13 fields from 7 of the record's 13
  protocol modules). · **Date:** 2026-11-19
- **Decision:**
  - **The study gets seven optional fields** (contract `ctgov` 2.2.0, additive; a reader of 2.1.0 is unchanged):
    `locations` (facility, city, state, country, the site's recruitment status), `secondary_ids` (id, type, domain,
    and `registry` / `registry_id` when the id is a jRCT, JapicCTI or UMIN-CTR number), `arms` (label, type,
    description, intervention names), `interventions` (name, type, description, arm labels, other names),
    `primary_outcomes` and `secondary_outcomes` (measure, description, time frame) and `design` (study type,
    allocation, model, primary purpose, masking, who is masked, enrolment type). Phases and the enrolment count stay
    where they were. `criteria_compiler.ctgov.to_study` fills them from the API v2 record in every mode (live,
    offline, cassette); a module the record lacks gives no field (absent, not an empty list).
  - **Other registries' ids** (`tb_common.ctgov_record.registry_of`): jRCT (`jRCT` + an optional category letter +
    9 or 10 digits), JapicCTI (`JapicCTI-` + 6 digits) and UMIN-CTR (`UMIN` + 9 digits), found anywhere in the id's
    text in any case, spaces ignored, and given in the registry's own spelling. `ctgov.registry_ids(study, "jRCT")`
    lists them. EudraCT and CTIS numbers keep the registry's own `type` and no `registry`. The jRCT intake (10D-16)
    joins on this; it is not built here.
  - **No personal names are stored.** `tb_common.ctgov_record.strip_names` drops, from the record TrialBox keeps:
    `centralContacts` and `overallOfficials` (names, roles, phones, e-mails); every location's `contacts`; the
    responsible party's `investigatorFullName`, `investigatorTitle` and `oldNameTitle` (its type and affiliation
    stay); `resultsSection.moreInfoModule.pointOfContact`; and every reference's `citation` (the authors' names; the
    PMID and type stay). It is applied where a record is kept: the reference data pack is built from stripped
    records (`tools/refdata_fetch.py parse_ctgov`), the store strips again when it loads a pack (an older pack), and
    **refdata schema version 4** strips the rows a box stored before. The study never reads these fields, so a live
    answer carries none either. A record is otherwise kept as the registry gave it.
  - **Shown:** nowhere new. The widened fields travel in the compiler's answer (`CtgovSearchResult`) for the pages and
    jobs that already read registry fields; no page, text key or route changes. The feasibility page's text about the
    CT.gov mode is lane J's (10D-17) and is not touched.
  - Class D0 (public registry data, no patient data): the six new contract parts are added to the policy's D0 set.
    No role, route, export or patient read changes.
- **Not in this card:** the NCT field on the protocol page that review 14 lists with M14-14 (the plan's row and the
  card ask for no new page); the jRCT intake (10D-16); `oversightModule`; the registry mirror
  (`services/matching/registry_mirror`), which reads committed fixtures and keeps no new record. The arms, outcomes and
  design belong to the study manifest's protocol part (10D-2, 10D-3); the manifest's schema is not edited here.
- **Proof data:** `tests/fixtures/ctgov/widened/NCT99000101.json`, a synthetic record written to the API v2 format
  with fictional contacts (`example.invalid` addresses, `+1-555-01xx` numbers). No live fetch was made.
- **Held by:** `tests/unit/test_ctgov_widened.py` (cassette → pack → store → read back equal for every widened field;
  a jRCT id found; no name in the pack or the store; version 4 strips a row stored before);
  `tests/unit/test_migrations.py` (refdata version 4).
