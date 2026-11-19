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


1. **The part: criteria and codes only.** `python -m criteria_compiler.export_part <ID> --out <file> (--installed
   installed.json | --release "<words>") [--by NAME]` exports the version of the box's own approval tag as a zip of
   the `import_ruleset` form plus `ORIGIN.json` (`tb_common.ruleset_part`). Before anything is hashed, every staff or
   site field is removed, following the protocol/site split of D-1366 (10D-2, PR #1165, read for the split, not used
   as code):
   - the manifest keeps D-1366's protocol fields and `status`; it loses `routing` and `scopes` (left as empty
     objects, which the schema requires), `review` (the approver, how, when), `effective_from`, `irb_reference`,
     `irb_approved_on`, `terminology_tables` and `terminology_refused` (the site's own code tables); `models` keeps
     `judge_prompt` only (the serving model is the site's); `equivalence` keeps its numbers (`overall_pct`,
     `sample_size`, `per_criterion`, `failing`), which the receiving import's gate reads. This is the one site field
     carried, numbers and criterion ids only. A manifest field placed in neither part refuses the export;
   - each criterion keeps its review **status** (approved or rejected) and loses who, when and the comment, and its
     `provenance`;
   - `labels.yaml`, `valuesets/`, `cql/`, `sql/` travel as compiled (D-1366: none of the shipped compiled files names
     a person, a department or an address); `tests/` is left out; any other file refuses the export.
   The record holds the rule set and version, the file list, what was left out, the approval tag's name, the
   compiling box's release (bundle id, release_seq, commit, from its installed record), the judge prompt and
   terminology pins, the time, and `part_sha256`: the sha256 over every carried file (path and bytes) and every other
   field of the record. The export refuses a draft, a version with no approval tag, an approval that names nobody
   here (a seeded example), and **any version that arrived in an update** (a part or any offline update: only a box's
   own approval is carried). It is audited on the head box as `ruleset.part_exported` (who, the rule set and version,
   `part_sha256`, the file count).
2. **The bundle, vendor key only.** `python -m tools.ruleset_bundle --key <vendor key> --id .. --release-seq ..
   --out .. <part>...` reads each part as the receiving box will and signs with `tools/sign_bundle.py` (Ed25519, the
   vendor key; no new key type, no new payload kind, no schema change). It is valid 30 days by default, at most 90 (a
   release bundle: a year). A rule-set bundle takes one number of the vendor's `release_seq` (runbook §5). Beside a
   release, a part rides in `tools/make_bundle.sh --rulesets DIR` as any rule set zip; that script is unchanged.
3. **Verify and apply.** `tools/apply_update.sh` unchanged: the signature, release_seq and every payload's sha256
   first; then the update path. Before writing anything, `import_ruleset` checks a part
   (`tb_common.ruleset_part.open_part`): every zip member is in `<ID>/` or is `ORIGIN.json`; every record field has
   its strict form (id and version patterns, the approval tag exactly `<ID>/v<version>`, a bundle id, a 40-hex
   commit, one line of at most 200 characters for a release in words, no control character anywhere, no unknown
   field); the record lists exactly the part's files; `part_sha256` matches; the manifest and criteria hold no site or
   staff field. Then: a part older than the box's newest approved version of the id is refused; the same version
   again is a no-op only when its tag holds the same `part_sha256`, else refused (a local approval or a shipped
   example of that version included: the dry run uses a new id or version). Any refusal rolls the update back
   (`update.rolled_back`); nothing is tagged.
4. **The receiving site's own routing and scope.** The part has none, and a rule set from another box must never
   screen and send on another site's people or scope. The import takes `routing` and `scopes` from the receiving
   repository's `profiles/<ID>.yaml` (the site profile the box's own compile reads, `Compiler._profile`) and refuses
   the part when they are missing (`routing.list_to` and `scopes.screen` both needed), naming the command that writes
   them: `python -m criteria_compiler.import_ruleset --site-profile <ID> FILE` (checked against the manifest schema,
   audited `ruleset.site_profile_set`). The installed manifest is the part's with the site's routing and scopes.
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
8. **Who may do it.** No new role, route, console action or matrix row: exporting and writing a site profile are
   commands in the compiler's container (whoever runs host commands there), both audited; signing is the vendor's;
   applying is the existing `apply_update.sh` act of the operator. The part holds criteria and codes only; it reads
   no patient data.

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
- `tests/integration/test_ruleset_bundle_two_boxes.py`: two in-process boxes on the same synthetic hospital; GZQO
  approved on the head box, exported, signed alone, applied on a box that never held it, screened there by e-mail
  with its own routing and scope: every listed patient, tier and criterion answer equal to the head box's.
- `tests/console/test_ruleset_arrived_in_bundle.py`: the overview marks such a version in en, ja and zh-TW.
