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
    `manifest_pins` of the merged manifest is unchanged. The edit is merged per key: `{"models": {"judge": "x"}}`
    leaves `judge_prompt` as the protocol has it (taken); naming `judge_prompt` with another value, or null, is
    refused. A verifier prompt pin does not exist yet; 10D-26 adds it to
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
- **The canonical form** (what 10D-3 reproduces byte for byte, in any language; `study_manifest.dumps`,
  `load_json`, `text`, `file_bytes`, `canonical`, `hashed_paths`). It is the simplest rule that holds: no Unicode
  normalisation anywhere, nothing read through a schema, no Python-specific formatting.
  1. **JSON is written as RFC 8785 (JSON Canonicalization Scheme)**: no insignificant whitespace; object keys sorted by
     their UTF-16 code units; strings as ECMAScript's `JSON.stringify` writes them (`"` and `\` escaped, U+0000 to
     U+001F as `\b \t \n \f \r` or `\u00xx` in lowercase hex, every other code point, U+2028 included, written as
     itself in UTF-8; a lone surrogate refused); numbers as ECMAScript's Number-to-String writes a double (`5.0` →
     `5`, `1e-6` → `0.000001`, `1e-7` → `1e-7`, `1e21` → `1e+21`, `2^60` → `1152921504606847000`, `-0` → `0`); the
     result encoded as UTF-8. Two further refusals, so that every reader reads the same value: an integer beyond
     ±2^53 (`2^53 + 2` is refused; a JSON number with a fraction or exponent is a double), and NaN or infinity. **No
     Unicode normalisation**: strings, codes and keys are their exact code points, so NFC and NFD text hash
     differently, as the engine and the lake (which compare bytes) treat them differently.
  2. **Reading a JSON file:** its bytes, a leading UTF-8 byte-order mark (EF BB BF) removed, decoded as UTF-8 and
     parsed as RFC 8259 JSON; an object naming a key twice, and the literals `NaN`/`Infinity`, are refused.
  3. **Reading a text file:** its bytes, a leading UTF-8 byte-order mark removed, every CR LF and then every lone CR
     written as LF; nothing else changes (no decoding, no normalisation, no trailing-newline rule).
  4. **Files hashed** (paths relative to the folder, as written): every file `Ruleset.from_files` reads, plus what the
     console reads for a study and the package's tests:
     - `ir/**.json`: rule 2, the key `review` removed (or set to `{"status":"rejected"}` when its status is
       `rejected`), then rule 1;
     - `valuesets/**.json`, `cql/elm/**.json`, `tests/expected.json`: rule 2, then rule 1;
     - every other file under `cql/elm/` whatever its extension (`from_files` reads them all, by stem),
       `cql/**.cql`, `sql/**.sql`, `labels.yaml`, `tests/patients.ndjson`: rule 3 (YAML and NDJSON are hashed as
       text, so no YAML 1.1 reading and no line-splitting rule enters the hash);
     - the file `docx_template` names, when it is in the folder: its bytes as they are.
     No other file is hashed (a stray `notes.txt~` changes nothing; `tests/equivalence.json` is the site's). A test
     derives the set of files `Ruleset.from_files` actually opens for each shipped study, with planted files, and
     holds it inside the hashed set, so the two cannot drift. Each file's entry is the lowercase hex sha256 of its
     bytes after its rule.
  5. **The manifest's fields** are what the file writes, read as the engine reads it (PyYAML `safe_load`, then the
     ruleset manifest schema) and written in that schema's JSON form (a date as `YYYY-MM-DD`), nulls left out, **no
     default added**: `thresholds` without `small_cell` hashes differently from one that writes `small_cell: 5`.
     Expanding defaults was dropped because it bound the hash to the schema's defaults, which a later release may
     change; hashing what is written binds it only to the text. A second implementation does not read the YAML: the
     package (10D-3) carries the protocol part as JSON, and the hash is taken over that JSON.
  6. **The criteria hash** is the lowercase hex sha256 of rule 1 applied to the object `{"schema":
     "tb-study-protocol/1", "manifest": {…}, "files": {path: sha256}}` (every key of the protocol part but
     `criteria_sha256`). RA-JAK as shipped hashes to
     `69ae60cdf2d49dd0e903228af12699009b6ed3da5157cda281485d976c7d69d1` (held by a test).
     *2026-11-25 (INT-R1, D-1073): RA-JAK's SQL and CQL were recompiled; as shipped it now hashes to*
     `70e2a0479107a55b81570ec627f6a8d0bb46d6e1e76737c89c3360ca7c16ce01`.
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
