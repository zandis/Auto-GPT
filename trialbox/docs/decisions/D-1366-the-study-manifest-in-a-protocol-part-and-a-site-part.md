# D-1366 The study manifest in a protocol part and a site part (10D-2)

- **Task:** lane A2, plan 10 row 10D-2 (review 14 M14-1, section 3; the owner's decision 47: federation by a signed
  package). · **Date:** 2026-11-19
- **Builds on:** D-301 (terminology release), D-318 (prompt pins), D-442 (score pins), D-364 (versions and IRB record),
  D-555 (a refusal is a returned sentence)
- **Decision:**
  - `tb_common.study_manifest` reads a study folder `rulesets/<ID>/` as it is today in two parts, each with its own
    schema: `schemas/study_protocol.schema.json` (`StudyProtocol`, `tb-study-protocol/1`) and
    `schemas/study_site.schema.json` (`StudySite`, `tb-study-site/1`). **Nothing on disk changes and no reader
    changes**: `merge(protocol, site)` gives back the same manifest (held for all eight shipped studies against
    `Ruleset.load`), so no migration is needed and no screening result can move.
  - **The protocol part** is what the coordinating centre fixes for every site: the manifest's `id`, `kind`, `title`,
    `trial_alias`, `sponsor`, `version`, `source_documents`, `protocol_version`, `protocol_date`, `language`,
    `index_date_rule`, `library`, `criteria`, `thresholds`, `variants`, `twpas`, `docx_template`, `cohort`,
    `population`, `nct_id`, `terminology_release`, `prompt_pins`, `derived_pins`, `source_last_update`; and every file
    of the folder but the site's own (criteria IR, value sets, CQL and ELM, the generated SQL, labels, the synthetic
    test patients and their expected results), each by the sha256 of its bytes. A criterion IR file is hashed without
    its review record (who approved it at this site, when, the comment, approved or draft), which is the site's; a
    criterion's "rejected" stays in the protocol part, because dropping a criterion is a site difference, not an
    adaptation (review 14 section 3.3).
  - **The criteria hash** (`criteria_sha256`) is the sha256 of the protocol part's one canonical serialisation: JSON of
    `schema`, `manifest` and `files`, keys sorted, no spaces, UTF-8; the manifest in its schema's JSON form (what the
    file sets, dates as ISO text, nulls left out). The same package on two sites gives the same hash whatever each site
    set for itself.
  - **The compiled SQL and ELM are in the protocol part.** Review 14 calls the SQL "derived; the same at every site
    given the same IR and expansion", and 10D-4 has a partner screen with a rule set compiled elsewhere: the compiled
    form travels with the package and a site does not rewrite it. None of the eight shipped folders' compiled files
    names a person, a department or a mail address.
  - **The site part** is what a hospital sets for itself: `status`, `effective_from`, `irb_reference`,
    `irb_approved_on`, `scopes`, `routing`, `models`, `review`, `equivalence`, `terminology_tables`,
    `terminology_refused`; each criterion's review record (`criterion_reviews`); its own files
    (`tests/equivalence.json`, its equivalence run on its box). It carries the criteria hash of the protocol part it
    goes with; `merge` refuses a site part of another protocol and a protocol part that no longer holds its hash.
  - **Thresholds are wholly the protocol's here.** Review 14 says the small-cell floor may be raised by a site; that
    bounded adaptation is 10D-5's ("allowed adaptations"), which adds it on top of this split. Until then a site edit
    of either threshold is refused.
  - **A site edit** goes through `site_edit(protocol, site, changes)`: a change to a site field is taken (None removes
    it) and validated against the ruleset manifest schema; a change to any protocol field is refused with one sentence
    naming the field and, for short values, the change ("the threshold thresholds.small_cell from 5 to 3 cannot be
    changed at a site: it is part of the study's protocol, the same at every site that adopted it (criteria hash
    …); the coordinating centre issues a new protocol version for that"). A protocol value sent back unchanged is no
    edit. A field the manifest does not have is refused. `apply_site_edit` raises the same sentence as
    `SiteEditRefused`. `differences(adopted, written)` names each protocol field and file a folder written at the site
    changed against the protocol part it adopted.
  - Every manifest field is in exactly one part; a test fails a new manifest field until it is placed, and holds the
    schemas' field lists to the module's.
- **Not in this card:** where the site part is stored apart from `manifest.yaml`, the package format and its signature
  (10D-3), import and the register of coordinating-centre keys, and calling `differences` at import, approval and load
  of an adopted study (10D-4), the allowed adaptations and the site-differences page (10D-5), the screen-only package
  items (10D-26). No console page, route, role or export changes; no patient data is read.
- **Held by:** `tests/unit/test_study_manifest.py`.
