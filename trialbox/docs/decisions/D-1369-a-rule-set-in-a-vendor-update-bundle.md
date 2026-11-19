# D-1369 A rule set compiled on the head box reaches a screen-only site box in a vendor-signed update bundle (10D-28)

- **Task:** lane K, plan 10 row 10D-28 (review 19, card 19-9): "interim, for the dry run only: a rule set carried in
  a vendor-signed update bundle (vendor key, not the coordinating investigator's)"; plan 10's third ruling, change 1
  (the owner's workstation card is the head box that reads protocols; the first site's 32 GB box screens).
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-77 (the offline update channel), D-210 (release_seq, compat.json), D-640 (a site box runs only a
  study approved at the site, or installed by an offline update), D-1102 (the rule-set zip caps), D-862 (the stored
  equivalence report)
- **Interim:** the long-term route is the study package signed by the coordinating centre (10D-2 to 10D-4); this
  record is replaced when they land. Nothing here is for the first real study.

## What was found (before building)

1. **What an approved rule set is.** A folder `<ID>/` in the criteria compiler's git repository (`rulesets-data`,
   `criteria_compiler/repo.py`): `manifest.yaml` (`status: approved`, the version, the judge and its prompt pin in
   `models`, the terminology release, the score pins `derived_pins`, the equivalence summary, the site's `routing`),
   `ir/` (one criterion each), `valuesets/` (the codes), `cql/` and `cql/elm/`, `sql/`, optionally `labels.yaml`, and
   `tests/`. The approval is the annotated tag `<ID>/v<version>`; its message says who ("approved by <who>", or
   "(offline update, <by>)"); a tag the first start wrote on a shipped example names nobody and is no approval on a
   site box (D-640, `tb_common.ruleset.seeded_approval`). The working copy the services read is materialized from
   `main`. What pins it at run time: the prompt pin and the score pins (`approval_state`: a drift asks for approval
   again), and the terminology release (`load_approved(terminology=...)`: another release refuses the run until a
   recompile).
2. **`tests/` is not criteria.** A box's compile writes `tests/equivalence.json` there: the percentages and one row
   per disagreeing case (a case label, never a pseudonym, no evidence: D-862). The shipped examples also hold
   `tests/patients.ndjson` and `expected.json`, synthetic patients of site A. Neither is needed to screen.
3. **Export today.** None from a box: the compiler offers a draft zip for review (`review.draft_zip`) and the vendor
   builds the shipped rule sets from the checkout (`tools/build_rulesets.py`, `make_bundle.sh --rulesets DIR`, every
   `*.zip` a payload of kind `ruleset`).
4. **What a bundle may hold** (`tools/verify_update.py`, `schemas/update_manifest.schema.json`): payloads of kind
   model, ruleset, image, refdata, other, host; any other kind fails the schema, and a member not in the manifest is
   refused. Nothing requires an image, a release record or a host tree: `release.json` and `images.lock` are needed
   only with images. **So an update bundle may carry a rule set alone** (review 19's open point, now verified by
   `tests/unit/test_ruleset_in_update_bundle.py`): `tools/sign_bundle.py build` signs it, the verifier accepts it,
   and the update path (`tools/trialbox/update.py`) runs every step on it: a PRODUCTION or VALIDATION box notes "no
   release record" and goes on (D-633 refuses only a record that is dirty or names no commit); the step `rulesets`
   imports each `*.zip` with `criteria_compiler.import_ruleset` (approved, equivalence at or above the site's gate,
   an existing tag never moved). `tools/make_bundle.sh` cannot build one alone: it always exports images and needs
   the release gates. A rule-set-only bundle takes a `release_seq` above the box's (D-210), one number of the
   vendor's sequence.
5. **Approval on the receiving box today.** An installed update's tag "(offline update, <by>)" is an approval a site
   box runs (D-640 lets it stand): no local approval step is required by the code, and none is added or removed here.
   What was missing: the box did not say where such a version came from.
6. **An approved folder is not criteria and codes only** (the first review of PR #1174, B1). The manifest holds the
   site's `routing` (mail addresses), `scopes` (practitioner and department codes), the approval record `review`
   (who, how, when), `effective_from`, the IRB fields and the site's code tables; each criterion's `review` holds the
   reviewer's address, the time and a free-text comment, and `provenance` the model calls. A first version of this
   card carried them whole; they are now removed at export (decision 1).

## Decision


1. **The part: criteria and codes only, by allow-lists** (the third review: by file and by key, never by folder or
   deny-list). `python -m criteria_compiler.export_part <ID> --out <file> (--installed installed.json | --release
   "<bundle id> [(release_seq N)]") [--by NAME]` exports the version of the box's own approval tag as a zip of the
   `import_ruleset` form plus `ORIGIN.json` (`tb_common.ruleset_part`), following the protocol/site split of D-1366
   (10D-2; its field lists are imported from `tb_common.study_manifest`, not copied):
   - **files**, exactly master's `study_manifest.PROTOCOL_FILES` that are criteria and codes, one per name:
     `manifest.yaml`, `labels.yaml`, `ir/<criterion id>.json` (named by its own id), `valuesets/<name>.json` (named
     by its `name`), `cql/<library>.cql` and `cql/elm/<library>.json` (the manifest's `library` and `TB_Common` only;
     an ELM file only beside its CQL), `sql/<ID>.sql`. `tests/` is left out. **Any other file refuses the export**
     (a stray `sql/patients.csv`, `cql/notes.md`, `valuesets/README.txt`, a sub-folder), and the import refuses any
     other member, with a correct record and hash too;
   - **the manifest** keeps D-1366's protocol fields and `status`, but `source_documents` and `docx_template` (file
     names someone chose; the docx is not carried) and `population.notes` (free notes); `source_last_update` must be
     a date, else refused. It loses `routing` and `scopes` (left as empty objects, which the schema requires),
     `review`, `effective_from`, `irb_reference`, `irb_approved_on`, `terminology_tables`, `terminology_refused`;
     `models` keeps `judge_prompt` only; `equivalence` keeps `overall_pct`, `sample_size`, `per_criterion`,
     `failing`, and a criterion id is the only text it may hold (else refused). A field placed in neither part
     refuses; the result must pass the manifest schema (no unknown key at any depth) and is written again as YAML,
     so no comment travels;
   - **each criterion** keeps the fields of `ruleset_part.IR_KEYS` only (the criterion schema's, held equal to it by
     a test, but `provenance`); any other key is dropped; `review` keeps its status (no who, when or comment); a flag
     must be one word of the compiler's (`[a-z][a-z0-9_]*`); the result must pass the criterion schema;
   - **value sets** hold the compiler's keys only, at every level (`resourceType id name title url version status
     compose extension`; `compose.include[]`: `system concept`; `concept[]`: `code display`; `extension[]`: the
     code-family `url` and `valueString`), else the export is refused naming file and key; their bytes travel;
   - **ELM**, by allow-lists at both ends (`tb_common.ruleset_part.elm_allowed`; the re-check of #1174): the top
     level holds `library` only; the library holds `identifier schemaIdentifier usings includes parameters
     codeSystems valueSets codes concepts contexts statements` only; every key below them is one of
     `ELM_NODE_KEYS`, the 81 keys the compiler's ELM holds (the union over the repository's compiled ELM fixtures and
     the pinned translator's output for every rule set's CQL, the generator's `ATOMS` snapshot and `TB_Common`; the
     constant's comment says how). Any other key refuses the export, naming its path (`library.statements.def[0].x`);
     the export removes only the translator's bookkeeping, every `annotation` entry (its copy of the CQL source, its
     options and messages; not read by the engine) and the library's `localId`. The receiving box holds each ELM file
     against the same lists as it stands and refuses any key off them, an annotation included, naming its path: it
     never drops one. Its `library.identifier` may hold `id` and `version` only (else refused); written again as
     compact JSON. ELM is not regenerated: the translator's jars are not on every box;
   - **labels.yaml**: its keys only (`ruleset`, `criteria.<criterion id>.{source, todo_source, en|ja|zh-TW.{label,
     text, todo}}`), text values only, written again as YAML (its comments go);
   - **CQL and SQL** travel as their bytes and are **never stripped** (removing text from code could change what it
     means): every comment is held against what the compiler writes (`criteria_compiler.part_text`: the generated
     header, each criterion's line with that criterion's id, kind and text from the part's own IR, and `TB_Common`'s
     own comments); any other comment refuses the export, naming the file and the line. The scanner knows the
     languages' strings and quoted names.
   - **depth**: a JSON or YAML file nested deeper than 256 is refused before it is parsed (no `RecursionError`).
   The record holds the rule set and version, the file list, what was left out, the approval tag's name, the
   compiling box's release (bundle id, release_seq, commit, from its installed record or from `--release`, which
   takes a bundle id and an optional `(release_seq N)`, nothing else), and the judge prompt and terminology pins,
   **which must equal the manifest's**. It holds **no time**: `part_sha256` (every carried file, path and bytes, and
   every other field of the record) is the same for the same approved version exported again from the same release,
   so the receiving box takes the repeat as the same part. The export refuses a draft, a version with no approval
   tag, an approval that names nobody here (a seeded example, also on a DEV box where it loads), and **any version
   that arrived in an update**. It is audited on the head box, before the part is handed out, as
   **`approve.part_exported`** (who, when, the rule set and version, `part_sha256`, the file count, the release).
   **The approval family** carries both events of this card: the criteria compiler, which runs the export and the
   site-profile command, writes `ai`, `approve`, `compile`, `ctgov` and `llm` (`audit_writer.ROLE_EVENTS`, unchanged);
   a `ruleset` family would be written by a role that may not write it, and the journal would mark each event
   foreign. Exporting an approved version and setting the site's routing and scope for one are acts on an approval;
   no role and no row of `ROLE_EVENTS` changed.
2. **The bundle, vendor key only.** `python -m tools.ruleset_bundle --key <vendor key> --id .. --release-seq ..
   --out .. <part>...` reads each part as the receiving box will and signs with `tools/sign_bundle.py` (Ed25519, the
   vendor key; no new key type, no new payload kind, no schema change). It is valid 30 days by default, at most 90 (a
   release bundle: a year). A rule-set bundle takes one number of the vendor's `release_seq` (runbook §5). Beside a
   release, a part rides in `tools/make_bundle.sh --rulesets DIR` as any rule set zip; that script is unchanged.
3. **Verify and apply.** `tools/apply_update.sh` unchanged: the signature, release_seq and every payload's sha256
   first; then the update path. Before writing anything, `import_ruleset` checks a part
   (`tb_common.ruleset_part.open_part`): every zip member is in `<ID>/` or is `ORIGIN.json`; every record field has
   its strict form (id and version patterns, the approval tag exactly `<ID>/v<version>`, a bundle id, a 40-hex
   commit, no control character anywhere, no unknown field); its pins are the manifest's; the record lists exactly
   the part's files; `part_sha256` matches; every file is exactly what the export writes (the export's allow-lists run
   again on the part and must give back the same bytes: a site field, an unknown key, an annotation, a comment the
   compiler does not write, a file off the list are refused). **A part never installs without its record**: a member
   named `ORIGIN.json` anywhere but the zip's root is refused, and a rule set zip with no record whose manifest has no
   routing or no screening scope (the form of a part's manifest) is refused on the plain path too; every rule set the
   vendor ships has both. Then: a part older than the box's newest approved version of the id is refused; the same version
   again is a no-op only when its tag holds the same `part_sha256`, else refused (a local approval or a shipped
   example of that version included: the dry run uses a new id or version). Any refusal rolls the update back
   (`update.rolled_back`); nothing is tagged.
4. **The receiving site's own routing and scope.** The part has none, and a rule set from another box must never
   screen and send on another site's people or scope. The import takes `routing` and `scopes` only from a profile the
   receiving site set itself: `python -m criteria_compiler.import_ruleset --site-profile <ID> FILE` writes
   `profiles/<ID>.yaml` (routing and scopes only: any other key is refused; checked against the manifest schema) and
   beside it `profiles/<ID>.site-set.json`, which records that file's sha256. The example `profiles/<ID>.yaml` a box
   ships with has no such record, and a profile changed by hand since no longer matches it: both are refused, as is a
   missing `routing.list_to` or `scopes.screen`, naming the command. The command writes **`approve.site_profile_set`**
   (who, when, the rule set, the profile's sha256) **before** the profile: when the audit write fails, nothing is
   written. The installed manifest is the part's with the site's routing and scopes.
5. **The tag and the audit.** The tag of an installed part reads `<ID>/v<version> (offline update, update:<bundle>);
   arrived in a vendor bundle (interim): update:<bundle>; compiled and approved on another box, release <bundle id>
   (release_seq N, commit C), its tag <ID>/v<version>; part sha256 <hash>`, built from checked fields only.
   `update.applied` names the rule sets imported (field `rulesets`), beside the files it already listed.
6. **The box's release stays.** A bundle of rule-set parts only writes `installed.json` with its own bundle id and
   release_seq, and keeps the commit, `dirty`, `rehearsal` and `vuln_mode` of the release it rides on, and that
   release's bundle id as `release_bundle_id` (the code identity, H-19, reads the commit); `apply_update.sh status`
   prints it as `release (code)`. The export reads `release_bundle_id` first.
7. **Not approved here, wherever it shows.** Every version whose tag records an offline update (a part, or a plain
   rule set zip of any update, with or without `ORIGIN.json`) counts as arrived (`tb_common.ruleset_part.arrived`,
   `tb_common.ruleset.arrived_in_bundle`): the console's rule-set lists (overview, administrator pages) add "arrived in
   a vendor bundle (interim): approved elsewhere, not on this box" in en, ja and zh-TW; the sponsor pack README says
   so instead of an "Approved by" line (`GET /rulesets/<id>/detail` carries `arrived_in_vendor_bundle`); the export
   refuses it. The approval mail (`orchestrator/scenarios/approve.py`) is sent only when this box approves a draft it
   compiled; an arrived version has no draft here, and its IRB fields are removed at export, so the mail never prints
   the head box's IRB reference.
8. **Pins and release refused on mismatch** (the second review). `tools/ruleset_bundle.py` writes the bundle's
   `compat.json` from the parts: `vocabulary_release` lists the parts' terminology release when one is pinned (parts
   of two releases cannot share a bundle), and `min_installed_version` is the highest `release_seq` that compiled a
   part, so the existing verifier refuses a box on an older release, or one that records another vocabulary release,
   before anything changes. A box records no vocabulary release today (`compat_check` then only notes it), so the
   import checks again on the box itself (`import_ruleset.box_pins_problem`): the terminology release the part was
   compiled against must be the one the box resolves through, and every prompt it pins must stand in the box's
   registry unchanged (`pin_drift`); otherwise it is refused, with the sentence. The serving model is the site's
   (D-1366), so `model_pin` stays `*`. The full package pins are card 10D-26's.
9. **The cost on a PRODUCTION box, said plainly.** A rule-set-only bundle of a few kilobytes goes through the whole
   update: refused while a job runs, every service stopped, both databases dumped and backed up, the services
   restarted, `doctor --weights` on a GPU box (up to an hour): a full quiet-hour downtime, and one number of the
   vendor's `release_seq`. This card does not skip the backup or the restart (runbook §5 says so).
10. **Who may do it.** No new role, route, console action or matrix row: exporting and writing a site profile are
   commands in the compiler's container (whoever runs host commands there), both audited in the approval family the
   compiler already writes; signing is the vendor's;
   applying is the existing `apply_update.sh` act of the operator. The part holds criteria and codes only; it reads
   no patient data.

## What travels (for the owner to rule on)

Everything not in this list stays on the head box. Free text that still leaves it, all of it the protocol's or the
compiler's by purpose, any of it typed or edited by a person on the head box:

- `manifest.yaml`: `title`, `trial_alias`, `sponsor`, `protocol_version`, `protocol_date`, `language`, `nct_id`,
  `source_last_update` (a date only), `population.disease_stage`, `population.study_arm`, `cohort.disease`,
  `cohort.disease_label`, `cohort.ctgov_condition`, `variants` (named sensitivity variants), `twpas` (NHI form
  settings), `library`, `terminology_release`, `models.judge_prompt`, `prompt_pins`, `derived_pins`; the criteria
  ids, thresholds and equivalence numbers.
- each `ir/<id>.json`: `text`, `label`, `source_ref` (the protocol's section and item, as the parser read it),
  `action` (the suggested to-do), `note_question`, `note_question_source`, `human_question`, `fallback`,
  `suggested_order`, `flags` (compiler words only), `review.status`; the logic's value set names and codes.
- `labels.yaml`: per criterion `source`, `todo_source` and their translations (`label`, `text`, `todo` in en, ja,
  zh-TW).
- `valuesets/*.json`: `title` and each concept's `display` (code system names), besides the codes.
- `cql/*.cql` and `sql/*.sql`: the compiler's comments, which repeat each criterion's `text`; **string literals
  are free text typed by the approver and travel as written**: besides the codes, units and code system URLs the
  compiler writes, a CQL or SQL string literal (`define "X": 'any words'`, `SELECT 'any words'`) is not checked
  (comments are; no literal grammar is held against the compiler's), so whatever a person typed into one on the head
  box leaves it, as does the same text in the ELM's literal values; ELM: define and value set names and those
  literals, without annotations, by its key allow-lists.
- `ORIGIN.json`: the bundle id, release_seq and commit of the compiling release (no free words: `--release` takes a
  bundle id), the pins, the file names (criterion ids, value set and library names).

Removed or refused, for the record: `source_documents`, `docx_template`, `population.notes`, every site field above,
each criterion's reviewer, time, comment and `provenance`, `tests/`, every comment the compiler does not write, ELM
annotations, any key or file nobody placed.

**Where the 30/90-day cap is enforced.** Only when the bundle is signed, in `tools/ruleset_bundle.py`
(`--valid-days`, 30 by default, at most 90). The import does not see the bundle's manifest, and the verifier
(`tools/verify_update.py`) checks `not_after` but no cap: a rule-set-only bundle signed with `tools/sign_bundle.py`
directly can be valid longer. This predates the card and is not changed by it.

## Not in this card, and what the dry run must know

- **New id or version.** A site box that already holds the version (the shipped example on a DEV box included)
  refuses the part; the head box exports a new id or version.
- **Pins must match.** The site box screens only on the same terminology release (else `RecompileNeeded`, and a
  screen-only box cannot recompile) and asks for approval again on a prompt or score pin drift; the head and site
  boxes run the same release for the dry run. The site's code tables are not carried, so the receiving box cannot
  check that the compiled SQL read the same site tables (D-1366 names the same limit for 10D-5).
- **Not run on a container box.** The tests run the real verifier, `Updater` and import on an in-process box; the
  compose box's steps (backup, dumps, restart, `docker compose exec criteria-compiler ... import_ruleset`) are
  unchanged and were not run.
- `tools/trialbox/update.py` `InProcessBox.rulesets` still imports nothing (the update drill's box); unchanged.

## Held by

- `tests/unit/test_ruleset_in_update_bundle.py`: planted names, addresses, a reviewer's comment, practitioner and
  department codes, an IRB reference, an effective date and a site code table are in no byte of the part or of the
  bundle; the part keeps the protocol fields and is reproducible; a file or field nobody placed refuses the export;
  only the box's own approval is exported and the export is audited; a bundle may carry a rule set alone, valid 30
  days; the PRODUCTION site box installs it with its own routing and scope, tags and lists it as arrived, audits
  `update.applied` with it, keeps its commit, takes the same part again as a no-op; without its own routing and scope
  it refuses; a zip without a record is listed as arrived too; a part older than the newest, the same version with
  another hash, the version of a shipped example, a record of the wrong form (each field), a record changed without
  its hash, a stray member, a site field put back, a changed criterion are refused; a bundle changed after signing is
  rejected; the sponsor pack says it arrived.
  The third review: a file off the per-file list refuses the export (six shapes) and the import (three, resealed); a
  CQL `//` or `/* */`, a `TB_Common` or an SQL `--` comment the compiler does not write refuses the export with file
  and line, and the import; YAML comments and ELM annotations are in no byte of the part; an ELM identifier key, a
  value-set key or a nested one refuses; an ELM key off the allow-lists (an extra library key, a key on a statement
  definition, an extra top-level key) refuses the export naming its path, and a part resealed with one is refused at
  the receiving box naming its path; a free file name refuses; the criterion stripper is an allow-list equal to
  the schema less `provenance`, and a part holding an unknown key is refused; a part without `ORIGIN.json`, or with it
  moved, is refused; the shipped example profile and a hand-edited one do not count; `approve.site_profile_set` is
  written before the profile and a failed audit writes nothing; a re-export is the same part and installs as a
  repeat; the record's pins must be the manifest's; deep JSON and YAML are refused; `--release` takes no free words;
  `population.notes` stays and `source_last_update` is a date.
  Also: the bundle's compatibility table carries the part's terminology release and the compiling release as its
  floor, and the verifier refuses a box on another vocabulary release or an older release; the import refuses a part
  whose terminology release is not the box's.
- `tests/integration/test_ruleset_bundle_two_boxes.py`: two in-process boxes on the same synthetic hospital. The head
  box screens the shipped GZQO v1.0.0, then approves v1.0.1, which is not shipped (GZQO-INC-01 at age 60; the draft
  is written by the test, the approval is the compiler's own, which rebuilds the SQL), and screens it; it exports
  v1.0.1, the vendor signs it alone, a box that never held GZQO applies it and screens v1.0.1 by e-mail with the
  routing and scope its operator set with `--site-profile` (the synthetic site's people). Every listed patient, tier and criterion answer equals the head box's v1.0.1 answers and differs
  from the shipped version's. A mutant import that writes the repository's own shipped GZQO files instead of the
  zip's fails it (run once by hand).
- `tests/console/test_ruleset_arrived_in_bundle.py`: the overview marks such a version in en, ja and zh-TW; the
  administrator's page (`admin.html`) and the administrator's home without step 4 (`home_admin.html`) mark it too.
