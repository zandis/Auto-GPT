# D-1367 The ClinicalTrials.gov intake reads sites, secondary ids, arms, outcomes and design; it stores no names (10D-15)

- **Task:** lane K (plan: A2), plan 10 row 10D-15 (review 14, card M14-14: "CT.gov intake widened: locations with
  status, secondary ids, arms, outcomes, design"; §5.2 of the review: TrialBox read 13 fields from 7 of the record's
  13 protocol modules). · **Date:** 2026-11-19
- **Decision:**
  - **The study gets seven optional fields** (contract `ctgov` 2.2.0, additive; a reader of 2.1.0 is unchanged):
    `locations` (facility, city, state, country, the site's recruitment status), `secondary_ids` (id, type, domain,
    and `registry` / `registry_id` when the id is a jRCT, JapicCTI or UMIN-CTR number), `arms` (label, type,
    description, intervention names), `interventions` (name, type, description, arm labels, other names),
    `primary_outcomes` and `secondary_outcomes` (measure, description, time frame) and `design` (study type,
    allocation, model, primary purpose, masking, who is masked, enrolment type). Phases and the enrolment count stay
    where they were. `criteria_compiler.ctgov.to_study` fills them from the API v2 record in every mode (live,
    offline, cassette); a module the record lacks gives no field (absent, not an empty list).
  - **A malformed record drops only itself:** in the widened fields a module or part that is not an object is read as
    empty, an item of a list that is not an object is left out, a text field that is not a string is left out (a
    facility that is not a string drops that site), and one string where a list of strings belongs is a list of one
    (never split into characters). A record whose fields read before this card are of a shape the contract refuses
    (a number as age or title, a word as enrolment count, a list as sex, a bad date) is left out of the search's
    answer, with a warning that names its NCT id and nothing of its content; the other records are answered.
  - **Other registries' ids** (`tb_common.ctgov_record.registry_of`), from the forms the repository's own Japan data
    and registry check show (`services/console/sitestore.py`, the jRCT samples in the fixtures): jRCT = `jRCT` + 10
    digits, or `jRCTs` + 9 digits; JapicCTI = `JapicCTI-` + 6 digits; UMIN-CTR = `UMIN` + 9 digits. **Assumed:** `s`
    is the only category letter (the only one those data show); another letter is not recognised. Any case, one
    optional space or hyphen after the prefix, and the number must stand on its own (no letter or digit before or
    after it). `refdata_jp._JRCT_ID` (the hospital's jRCT download, which accepts more shapes) is not changed here.
    **A field naming two different registry numbers** (`"UMIN000012345 and jRCT2031260123"`) is recognised as
    neither: which number the field stands for is not known, and a wrong join is worse than none; its text stays in
    `id`. The same number written twice is one. `ctgov.registry_ids(study, "jRCT")` lists them. EudraCT and CTIS
    numbers keep the registry's own `type` and no `registry`. The jRCT intake (10D-16) joins on this; it is not
    built here. **For 10D-16:** only the category letter `s` is recognised here, while
    `services/console/sitestore.py:257` accepts any letter; whether jRCT issues other letters is not verified.
  - **No personal names are stored.** `tb_common.ctgov_record.strip_names` drops, from the record TrialBox keeps:
    `centralContacts` and `overallOfficials` (names, roles, phones, e-mails); every location's `contacts`; the
    responsible party's `investigatorFullName`, `investigatorTitle` and `oldNameTitle` (its type and affiliation
    stay); the `name` of the lead sponsor and of each collaborator whose `class` is `INDIV` (a person), in any case and
    with spaces around it ignored, alike in Python and in version 4's SQL (an organisation's name stays, and a party
    with no class is kept as an organisation, the API's default); `resultsSection.moreInfoModule.pointOfContact`; and every reference's `citation` (the
    authors' names; the PMID and type stay). The study's `sponsor` is none when the lead sponsor is a person, in every
    mode. It is applied where a record is kept: the reference data pack is built from stripped records
    (`tools/refdata_fetch.py parse_ctgov`), the store strips again when it loads a pack (an older pack), and
    **refdata schema version 4** strips the rows a box stored before, in one UPDATE that rewrites only the rows holding
    something to drop (a box with the full registry rewrites only those). Its SQL names every path and key of
    `ctgov_record`, and a test holds it to them. A record is otherwise kept as the registry gave it.
  - **What stays (not cleaned):** free text (brief and detailed summaries, arm and intervention descriptions, outcome
    descriptions, the eligibility text) may name a person; so may `seeAlsoLinks` labels and a facility named after a
    person (a hospital's name is kept). Old pack tarballs already on a box (the update bundles and the pack kept for a
    restore) keep the records they were built with; loading one again strips it, and a new pack replaces them.
  - **Shown:** nowhere new. The widened fields travel in the compiler's answer (`CtgovSearchResult`) for the pages and
    jobs that already read registry fields; no page, text key or route changes. The feasibility page's text about the
    CT.gov mode is lane J's (10D-17) and is not touched.
  - Class D0 (public registry data, no patient data): the six new contract parts are added to the policy's D0 set.
    No role, route, export or patient read changes.
- **Not in this card:** the NCT field on the protocol page that review 14 lists with M14-14 (the plan's row and the
  card ask for no new page); the jRCT intake (10D-16); `oversightModule`; the registry mirror
  (`services/matching/registry_mirror`), which reads committed fixtures and keeps no new record. The arms, outcomes and
  design belong to the study manifest's protocol part (10D-2, 10D-3); the manifest's schema is not edited here.
- **Proof data:** `tests/fixtures/ctgov/widened/studies.json`, two synthetic records written to the API v2 format
  with fictional contacts (`example.invalid` addresses, `+1-555-01xx` numbers), a person as collaborator and, in the
  second, a person as lead sponsor and two registry numbers in one field. No live fetch was made.
- **Held by:** `tests/unit/test_ctgov_widened.py` (cassette → pack → store → read back equal for every widened field;
  a jRCT id found and look-alikes refused; no name in the pack or the store, an older pack's names stripped on load;
  version 4 strips the rows stored before and rewrites no clean row; its SQL names every path; malformed parts and a
  single string read safely; a record the contract refuses left out alone; a person known in any case and spacing);
  `tests/unit/test_migrations.py` (refdata version 4).
