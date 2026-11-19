# D-1366 The study manifest in a protocol part and a site part (10D-2)

- **Task:** lane A2, plan 10 row 10D-2 (review 14 M14-1, section 3; the owner's decision 47: federation by a signed
  package). · **Date:** 2026-11-19
- **Builds on:** D-301 (terminology release), D-318 (prompt pins), D-442 (score pins), D-364 (versions and IRB record),
  D-555 (a refusal is a returned sentence)
- **What this card does not do, plainly:** nothing refuses anything on the live path today. A site can still edit
  the thresholds in `manifest.yaml` and the box screens on them; nothing outside the tests imports
  `tb_common.study_manifest`. Wiring the refusal into import, approval and load is 10D-4's.
- **Decision:**
  - `tb_common.study_manifest` reads a study folder `rulesets/<ID>/` as it is today in two parts, each with its own
    schema: `schemas/study_protocol.schema.json` (`StudyProtocol`, `tb-study-protocol/1`) and
    `schemas/study_site.schema.json` (`StudySite`, `tb-study-site/1`). Nothing on disk changes and no reader
    changes: `merge(protocol, site)` gives back the same manifest (held for all eight shipped studies against
    `Ruleset.load`), so no migration is needed and no screening result can move.
  - **The protocol part** is what the coordinating centre fixes for every site: the manifest's `id`, `kind`, `title`,
    `trial_alias`, `sponsor`, `version`, `source_documents`, `protocol_version`, `protocol_date`, `language`,
    `index_date_rule`, `library`, `criteria`, `thresholds`, `variants`, `twpas`, `docx_template`, `cohort`,
    `population`, `nct_id`, `terminology_release`, `prompt_pins`, `derived_pins`, `source_last_update`, and
    **`models.judge_prompt`**; and the protocol's files (the list below). A criterion IR file is hashed without its
    review record (who approved it at this site, when, the comment, approved or draft), which is the site's; a
    criterion's "rejected" stays in the protocol part, because dropping a criterion is a site difference, not an
    adaptation (review 14 section 3.3).
  - **The prompt pin is the protocol's, the serving model the site's.** Seven of the eight shipped studies have no
    `prompt_pins`; for them `tb_llm.prompt_registry.manifest_pins` takes the judge's pin from `models.judge_prompt`
    (`judge_v4`), and SCREEN runs that prompt. So `models` is split by key: `judge_prompt` is in the protocol part
    and in the criteria hash; `judge` and `extract` (which model serves, the box's tier) are the site's. A site edit
    that changes `models.judge_prompt` is refused like a threshold; one that changes `models.judge` is taken, and
    `manifest_pins` of the merged manifest is unchanged. A verifier prompt pin does not exist yet; 10D-26 adds it to
    the protocol part.
  - **The compiled SQL and ELM are in the protocol part.** Review 14 calls the SQL "derived; the same at every site
    given the same IR and expansion", and 10D-4 has a partner screen with a rule set compiled elsewhere: the compiled
    form travels with the package and a site does not rewrite it. None of the eight shipped folders' compiled files
    names a person, a department or a mail address.
  - **The site part** is what a hospital sets for itself: `status`, `effective_from`, `irb_reference`,
    `irb_approved_on`, `scopes`, `routing`, `models` without `judge_prompt`, `review`, `equivalence`,
    `terminology_tables`, `terminology_refused`; each criterion's review record (`criterion_reviews`); its own files
    (`tests/equivalence.json`, its equivalence run on its box). It carries the criteria hash of the protocol part it
    goes with. `merge` refuses a protocol part that no longer holds its hash or carries a site key, a site part that
    carries any protocol field or key (`thresholds`, `criteria`, `models.judge_prompt`, …), and a site part of
    another protocol; both parts are validated against their schemas first.
  - **Thresholds are wholly the protocol's here.** Review 14 says the small-cell floor may be raised by a site; that
    bounded adaptation is 10D-5's, on top of this split. Until then a site edit of either threshold is refused.
  - **A site edit** goes through `site_edit(protocol, site, changes)`: a change to a site field is taken (None removes
    it) and validated against the ruleset manifest schema; a change to any protocol field or key is refused with one
    sentence naming it and, for short values, the change ("the threshold thresholds.small_cell from 5 to 3 cannot be
    changed at a site: it is part of the study's protocol, the same at every site that adopted it (criteria hash
    …); the coordinating centre issues a new protocol version for that"). A protocol value sent back unchanged is no
    edit. `apply_site_edit` raises the same sentence as `SiteEditRefused`. `differences(adopted, written)` first
    checks that the adopted part holds its own hash (else its one sentence says it cannot be trusted), then names each
    protocol field and file a folder written at the site changed.
- **The canonical form** (what 10D-3 reproduces byte for byte; `study_manifest.normal`, `dumps`, `text`,
  `file_bytes`, `canonical`):
  1. **JSON values.** Every string, object keys included, in Unicode NFC. A float with no fractional part and an
     absolute value under 2^53 is written as an integer (`5.0` → `5`); any other float as Python's `repr` (the
     shortest text that reads back to the same double: `0.75`, `1e-05`, `1.152921504606847e+18`); NaN and infinity
     are refused. Booleans `true`/`false`, `null` as is. A date or date-time as its ISO text. Serialised as JSON with
     the keys of every object sorted by code point, no spaces (`,` and `:`), non-ASCII written as UTF-8 (not
     `\u` escapes), encoded UTF-8.
  2. **The manifest's fields** are read through the ruleset manifest schema with **defaults made explicit** and
     nulls left out (`thresholds` without `small_cell` reads as `small_cell: 5`), in its JSON form, then split by the
     field lists above.
  3. **Files hashed** (paths relative to the folder, NFC; no other file is hashed, so a stray `notes.txt~` changes
     nothing): `ir/**.json` (a criterion: read through the criterion IR schema, defaults explicit, nulls left out,
     the `review` record removed, or replaced by `{"status":"rejected"}` when rejected, then rule 1);
     `valuesets/**.json`, `cql/elm/**.json`, `tests/expected.json` (parsed, rule 1); `cql/**.cql`, `sql/**.sql`
     (text: UTF-8, NFC, CRLF and CR to LF, trailing line ends cut to exactly one `\n`); `labels.yaml` (parsed as
     YAML, rule 1); `tests/patients.ndjson` (each non-blank line parsed and written by rule 1, each followed by
     `\n`); and the file `docx_template` names when it is in the folder (its bytes). Each file's entry is the
     lowercase hex sha256 of those bytes.
  4. **The criteria hash** is the lowercase hex sha256 of rule 1 applied to the object `{"schema":
     "tb-study-protocol/1", "manifest": {…}, "files": {path: sha256}}` (every key of the protocol part but
     `criteria_sha256`). RA-JAK as shipped hashes to
     `16e7b313accd9b1d0c3fa579949823963b1d333b1f925093a1912ab651e04b87` (held by a test).
- **Limits for 10D-5, said plainly:**
  - `scopes` is site side (review 14), and it decides who is looked at: two sites with the same criteria hash screen
    different people. That is intended; it is not a difference in who is eligible.
  - `terminology_tables` (a site's own loaded code lists) is site side, but the value-set expansion is compiled into
    `sql/*.sql`, a protocol file. A site that compiles with its own code lists gets different SQL and so a different
    criteria hash: "the same hash on two sites" holds only for sites that screen with the package's compiled SQL as
    it came. The local-code adaptation (review 14 section 3.3: local codes mapped into the package's value sets) has
    to sit outside the hashed SQL; that is 10D-5's to design, not solved here.
  - `labels.yaml` is hashed whole, so a site's local wording of a label changes the criteria hash today; local
    wording as an allowed adaptation is 10D-5's.
  - Every manifest field is in exactly one part (with `models.judge_prompt` named as the one key moved); a test fails
    a new manifest field until it is placed, and holds the schemas' field lists to the module's.
- **Not in this card:** where the site part is stored apart from `manifest.yaml`, the package format and its signature
  (10D-3), import, the register of coordinating-centre keys and calling `differences` at import, approval and load
  of an adopted study (10D-4), the allowed adaptations and the site-differences page (10D-5), the screen-only package
  items (10D-26). No console page, route, role or export changes; no patient data is read.
- **Held by:** `tests/unit/test_study_manifest.py`.
